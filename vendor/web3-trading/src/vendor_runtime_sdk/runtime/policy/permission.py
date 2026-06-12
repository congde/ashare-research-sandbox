# -*- coding: utf-8 -*-
"""
PermissionResolver — Sprint 6 V2 single-lattice resolver (PR-4b final form).

Two-layer evaluation:

  Layer 1: PolicyEngine    (highest priority — explicit allow/deny/ask
                             from operator-authored rules; safe-evaluated
                             against tool_name + args + dynamic context)
  Layer 2: PermissionMode  (5-step lattice on the V2 enum:
                             ReadOnly < Prompt < WorkspaceWrite
                             < Allow < DangerFullAccess)

PR-4b removed:
  * Legacy 3-step cascade Step 2 (``permission_policy + tier``)
  * Legacy 3-step cascade Step 3 (``safety_tags`` → mode mapping)
  * Legacy 3-level :class:`PermissionMode` enum
    (``READ_ONLY / DEFAULT / FULL_ACCESS``)
  * ``_strictest`` / ``_decide_by_tier`` / ``_decide_by_permission_policy``
  * ``_legacy_session_to_v2_active_mode`` bridge
  * ``coder_permission_mode_v2`` toggle gate (V2 is unconditional)
  * ``always_ask`` / ``manual_only`` short-circuits
    (replaced by ``Prompt`` lattice level + explicit deny rules)
  * ``session_tier`` parameter (lattice carries the same signal)

Tools declare ``required_permission: PermissionMode`` directly.
The 17 production tools migrated in PR-2; new tools that miss the
declaration default to :attr:`PermissionMode.ReadOnly` (the safest
floor) via :class:`agent.tools.base.BaseTool`.

PolicyEngine semantics for HITL preservation (Sprint 6 PR-4a review):
  * If a tool declares ``required_permission == Prompt`` AND the
    PolicyEngine emits ``allow`` with a rule_id, the resolver
    downgrades the verdict to ``ask``.  This preserves the operator-
    authored HITL contract even when an upstream allow rule would
    otherwise short-circuit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional

from vendor_runtime_sdk.runtime.policy.engine import PolicyDecision, PolicyEngine
from vendor_runtime_sdk.runtime.policy.permission_mode import PermissionMode, RiskLevel

logger = logging.getLogger(__name__)


# Canonical ``ask`` reason strings — centralised so HITL UI / audit
# log consumers see consistent wording across all code paths.
ASK_REASON_LATTICE_PROMPT = (
    "V2 lattice: required=Prompt — HITL approval required"
)
ASK_REASON_POLICY_ENGINE_PROMPT_DOWNGRADE = (
    "PolicyEngine allow rule downgraded to ask: tool declares "
    "required_permission=Prompt (HITL contract preserved)"
)
ASK_REASON_IM_AUTO_EXECUTE = (
    "Feishu IM channel: operator-bound session — tool auto-approved "
    "(set LARK_IM_REQUIRE_TOOL_APPROVAL=true to require card approval)"
)


# ── Resolution result ──────────────────────────────────────────────────────────


@dataclass
class ResolutionResult:
    """Final permission verdict."""

    allowed: bool
    action_type: str  # allow / deny / ask
    reason: str = ""
    rule_id: Optional[str] = None  # set when PolicyEngine fired a rule
    # HITL Redesign — populated when ``action_type == "ask"`` so the
    # ApprovalCard can render risk badges and inline-edit the right
    # subset of arguments. ``editable_args`` is a tuple of parameter
    # names; empty tuple == read-only payload.
    risk_level: RiskLevel = RiskLevel.LOW
    editable_args: tuple = ()

    def __bool__(self) -> bool:
        return self.allowed


# ── PermissionResolver ─────────────────────────────────────────────────────────


class PermissionResolver:
    """
    Resolves whether a tool call is permitted by applying the V2
    two-layer evaluation (PolicyEngine + PermissionMode lattice).

    Parameters
    ----------
    policy_engine : PolicyEngine | None
        If None, Layer 1 is skipped (treat as no-match).
    session_mode : PermissionMode
        The session's privilege envelope.  Default
        :attr:`PermissionMode.Prompt` mirrors the Claude-Code mental
        model: every MEDIUM/HIGH-risk tool fires the HITL ApprovalCard
        until the user explicitly upgrades the session (via the
        "always allow this session" button).  Plan-mode contexts clamp
        further via
        ``runtime.policy.permission_mode.scoped_active_permission_mode``.

        Pre-Sprint-7 default was ``WorkspaceWrite`` which silently
        auto-allowed every workspace-level tool (``write_file``,
        ``patch_apply``, ``web_fetch``, etc.) on a fresh session because
        ``WorkspaceWrite >= WorkspaceWrite`` is True — defeating the
        whole HITL UX redesign.  See bug-fix log @
        terminal /7.txt:174 ``HITL-DEBUG: tool=write_file allowed=True
        action=allow rule=None`` (the smoking-gun trace).
    """

    def __init__(
        self,
        policy_engine: Optional[PolicyEngine] = None,
        session_mode: PermissionMode = PermissionMode.Prompt,
    ) -> None:
        if not isinstance(session_mode, PermissionMode):
            raise TypeError(
                "session_mode must be a PermissionMode (V2 5-step lattice); "
                f"got {type(session_mode).__name__}"
            )
        self._engine = policy_engine
        self._session_mode = session_mode

    def resolve(
        self,
        tool_name: str,
        args: dict,
        context: Optional[Dict] = None,
        tool=None,  # BaseTool instance for metadata access
    ) -> ResolutionResult:
        """
        Determine whether the tool call should be allowed.

        Parameters
        ----------
        tool_name : str
        args : dict
        context : dict | None
            Additional eval context for PolicyEngine (hour, retry_count, etc.)
        tool : BaseTool | None
            Read ``required_permission`` from this object.

        Returns
        -------
        ResolutionResult
        """
        eval_ctx = dict(context or {})
        eval_ctx.setdefault("tool_name", tool_name)
        eval_ctx.setdefault("args", args)

        # ── Layer 1: PolicyEngine ───────────────────────────────────────────
        if self._engine is not None:
            decision: PolicyDecision = self._engine.evaluate(eval_ctx)

            if decision.action_type == "deny":
                return ResolutionResult(
                    allowed=False,
                    action_type="deny",
                    reason=decision.reason or "PolicyEngine denied the action",
                    rule_id=decision.rule_id,
                )
            if decision.action_type == "allow" and decision.rule_id is not None:
                # Sprint 6 PR-4a review CRITICAL: a PolicyEngine ``allow``
                # rule MUST NOT silently bypass the tool's declared
                # ``required_permission == Prompt`` HITL contract.
                # Downgrade to ``ask`` and emit a WARNING so operators
                # see the near-miss.
                required = _required_for(tool)
                if (
                    required == PermissionMode.Prompt
                    and not _lark_im_auto_execute_enabled(eval_ctx)
                ):
                    logger.warning(
                        "PolicyEngine rule %r matched ``allow`` for tool %r "
                        "but the tool declares required_permission=Prompt "
                        "— downgrading to ``ask`` to preserve HITL "
                        "contract.  If this rule was intended to bypass "
                        "HITL, raise the tool's required_permission to "
                        "WorkspaceWrite or higher.",
                        decision.rule_id, tool_name,
                    )
                    return ResolutionResult(
                        allowed=False,
                        action_type="ask",
                        reason=ASK_REASON_POLICY_ENGINE_PROMPT_DOWNGRADE,
                        rule_id=decision.rule_id,
                        risk_level=_risk_for(tool),
                        editable_args=_editable_args_for(tool),
                    )
                return ResolutionResult(
                    allowed=True,
                    action_type="allow",
                    reason="PolicyEngine explicitly allowed",
                    rule_id=decision.rule_id,
                )
            if decision.action_type == "ask":
                if not _lark_im_auto_execute_enabled(eval_ctx):
                    return ResolutionResult(
                        allowed=False,
                        action_type="ask",
                        reason=decision.reason or "PolicyEngine requires confirmation",
                        rule_id=decision.rule_id,
                        risk_level=_risk_for(tool),
                        editable_args=_editable_args_for(tool),
                    )
            # degrade / no-match → fall through to Layer 2

        # ── Layer 2: PermissionMode lattice ─────────────────────────────────
        if _lark_im_auto_execute_enabled(eval_ctx):
            return ResolutionResult(
                allowed=True,
                action_type="allow",
                reason=ASK_REASON_IM_AUTO_EXECUTE,
                risk_level=_risk_for(tool),
            )

        required = _required_for(tool)

        # ``Prompt`` is the HITL gate level — fires ``ask`` regardless
        # of how privileged the session is.  Checked BEFORE the >=
        # comparison so high-privilege sessions don't bypass HITL.
        if required == PermissionMode.Prompt:
            return ResolutionResult(
                allowed=False,
                action_type="ask",
                reason=ASK_REASON_LATTICE_PROMPT,
                risk_level=_risk_for(tool),
                editable_args=_editable_args_for(tool),
            )

        if self._session_mode >= required:
            return ResolutionResult(
                allowed=True,
                action_type="allow",
                reason=(
                    f"V2 lattice: session={self._session_mode.name} "
                    f">= required={required.name}"
                ),
            )

        # Session can't satisfy the required tier.  Two cases:
        #
        #   (a) Session is :attr:`PermissionMode.ReadOnly` — the user
        #       explicitly opted out of ALL risky operations.  Hard-deny
        #       so a misbehaving LLM can't escalate by spamming HITL
        #       prompts to fatigue the operator.
        #
        #   (b) Session is :attr:`PermissionMode.Prompt` (default) or
        #       higher — promote to ``ask`` so the ApprovalCard fires.
        #       This is the Claude-Code "ask before risky things"
        #       semantic.  Pre-fix this returned ``deny`` which the
        #       LLM saw as a hard wall; HITL never had a chance.
        if self._session_mode == PermissionMode.ReadOnly:
            return ResolutionResult(
                allowed=False,
                action_type="deny",
                reason=(
                    f"V2 lattice: session={self._session_mode.name} opted out "
                    f"of risky operations; required={required.name}"
                ),
            )
        return ResolutionResult(
            allowed=False,
            action_type="ask",
            reason=(
                f"V2 lattice: session={self._session_mode.name} < "
                f"required={required.name} → HITL approval requested"
            ),
            risk_level=_risk_for(tool),
            editable_args=_editable_args_for(tool),
        )

    # ── Session mode ──────────────────────────────────────────────────────────

    def set_session_mode(self, mode: PermissionMode) -> None:
        if not isinstance(mode, PermissionMode):
            raise TypeError(
                f"set_session_mode requires a PermissionMode, got {type(mode).__name__}"
            )
        self._session_mode = mode

    @property
    def session_mode(self) -> PermissionMode:
        return self._session_mode


# ── Helpers ──────────────────────────────────────────────────────────────────


def _required_for(tool) -> PermissionMode:
    """Read the tool's ``required_permission``, defaulting to ReadOnly
    (the safest floor) when the field is missing or wrongly typed."""
    if tool is None:
        return PermissionMode.ReadOnly
    required = getattr(tool, "required_permission", PermissionMode.ReadOnly)
    if not isinstance(required, PermissionMode):
        logger.warning(
            "tool %r declared required_permission=%r which is not a "
            "PermissionMode — defaulting to ReadOnly (safest floor).",
            getattr(tool, "name", type(tool).__name__), required,
        )
        return PermissionMode.ReadOnly
    return required


def _risk_for(tool) -> RiskLevel:
    """Read the tool's ``risk_level`` for HITL UI surfacing.

    Falls back to :attr:`RiskLevel.LOW` for tools that haven't migrated
    to the new metadata field (covers third-party MCP wrappers and
    legacy local tools)."""
    if tool is None:
        return RiskLevel.LOW
    return RiskLevel.coerce(getattr(tool, "risk_level", RiskLevel.LOW))


def _lark_im_auto_execute_enabled(eval_ctx: Optional[Dict] = None) -> bool:
    """True when the current dispatch channel should skip Prompt-lattice
    HITL cards.

    PR-E6b (SDK extraction §5 PR-E6b): lark.im_permissions is now
    accessed via the PermissionChecker Protocol. The legacy lark.* call
    continues via the _LegacyLarkPermissionChecker fallback so runtime
    behaviour is unchanged in Phase 0. Phase 2 removes the fallback
    when lark/ leaves the engine import surface.
    """
    try:
        from vendor_runtime_sdk.runtime.protocols.permission_checker import get_permission_checker

        return bool(get_permission_checker().im_auto_execute_enabled(eval_ctx))
    except Exception:
        # Mirror prior fail-soft default — IM dispatch defaulted to
        # auto-execute when the env helper raised; otherwise False.
        return bool((eval_ctx or {}).get("source") == "lark_bot")


def _editable_args_for(tool) -> tuple:
    """Read the tool's ``editable_args`` whitelist as a tuple of
    parameter names. Defaults to empty tuple (= read-only payload).

    Wrong-typed declarations (e.g. operator wrote a list instead of a
    tuple) are tolerated — we coerce to a tuple of strings and drop
    anything that isn't a string. Defensive because this metadata is
    surfaced directly to the frontend ApprovalCard and bad input here
    must never break the gate."""
    if tool is None:
        return ()
    raw = getattr(tool, "editable_args", ())
    if isinstance(raw, str):
        return (raw,)
    try:
        return tuple(str(item) for item in raw if isinstance(item, str))
    except TypeError:
        return ()
