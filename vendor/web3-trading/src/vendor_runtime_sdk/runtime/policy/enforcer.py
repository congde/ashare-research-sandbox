# -*- coding: utf-8 -*-
"""PR-F7 — :class:`PermissionEnforcer`.

Per :doc:`docs/CoderAgent-多文件任务完成率根因修复方案` §3.F7.

Compares the active session :class:`PermissionMode` against a tool's
``required_permission`` and emits a structured
:class:`EnforcementResult`.

Three call patterns:

* :meth:`check` — caller already knows the required mode (e.g. for a
  pre-classified bash command).
* :meth:`check_for_tool` — caller hands over the tool object; the
  enforcer reads ``tool.required_permission`` (defaulting to ReadOnly
  if unset, so unmigrated tools cannot accidentally escalate).
* :meth:`check_with_required_mode` — caller passes a dynamically-
  resolved required mode (used by F8 bash command-classification
  pipeline).

This module is purely additive: it does not replace the existing
:mod:`runtime.policy.engine` (PolicyEngine) or
:mod:`runtime.policy.permission` (PermissionResolver).  Both stay in
force; F7 sits *next* to them as a strongly-typed companion the HITL
layer can read directly.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from vendor_runtime_sdk.runtime.policy.permission_mode import EnforcementResult, PermissionMode

logger = logging.getLogger(__name__)


class PermissionEnforcer:
    """Stateless enforcer.

    Each instance is bound to an *active mode* (the session-level
    privilege envelope). Tool calls are admitted iff
    ``active_mode >= tool.required_permission``.
    """

    def __init__(self, *, active_mode: PermissionMode = PermissionMode.WorkspaceWrite) -> None:
        if not isinstance(active_mode, PermissionMode):
            raise TypeError(
                f"active_mode must be PermissionMode, got {type(active_mode).__name__}"
            )
        self._active_mode = active_mode

    @property
    def active_mode(self) -> PermissionMode:
        return self._active_mode

    # ── Core check ─────────────────────────────────────────────────────

    def check(
        self,
        *,
        tool_name: str,
        required_mode: PermissionMode,
        reason_hint: str = "",
    ) -> EnforcementResult:
        """Compare ``active_mode`` against ``required_mode``."""
        if self._active_mode >= required_mode:
            return EnforcementResult.allow(
                tool=tool_name,
                active_mode=self._active_mode,
                required_mode=required_mode,
            )
        reason_lines = [
            f"Tool {tool_name!r} requires {required_mode.name}; "
            f"current session is in {self._active_mode.name}.",
        ]
        if reason_hint:
            reason_lines.append(f"Detail: {reason_hint}")
        return EnforcementResult.deny(
            tool=tool_name,
            active_mode=self._active_mode,
            required_mode=required_mode,
            reason=" ".join(reason_lines),
        )

    def check_for_tool(self, tool: Any) -> EnforcementResult:
        """Read ``tool.required_permission`` and delegate to :meth:`check`.

        Tools that never declare ``required_permission`` default to
        :attr:`PermissionMode.ReadOnly` — the safest possible default
        for a new / unmigrated tool. Operators can spot tools missing
        the declaration in the audit log because their EnforcementResult
        will tag them at the bottom of the ladder regardless of what
        they do.
        """
        required = getattr(tool, "required_permission", PermissionMode.ReadOnly)
        if not isinstance(required, PermissionMode):
            # Defensive: if a tool subclass mistypes the field, default
            # to ReadOnly rather than crash.
            logger.warning(
                "PermissionEnforcer: tool %s has invalid required_permission "
                "%r (expected PermissionMode); defaulting to ReadOnly",
                getattr(tool, "name", type(tool).__name__),
                required,
            )
            required = PermissionMode.ReadOnly
        tool_name = getattr(tool, "name", type(tool).__name__)
        return self.check(tool_name=tool_name, required_mode=required)

    def check_with_required_mode(
        self,
        *,
        tool_name: str,
        required_mode: PermissionMode,
        reason_hint: Optional[str] = None,
    ) -> EnforcementResult:
        """Like :meth:`check` but with a caller-supplied
        ``required_mode`` (used by F8's bash-command classifier when
        the required mode depends on the command itself, not the tool
        class)."""
        return self.check(
            tool_name=tool_name,
            required_mode=required_mode,
            reason_hint=reason_hint or "",
        )


def enforce_for_tool_call(
    tool: Any,
    *,
    active_mode: Optional[PermissionMode] = None,
    milestone_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Run a per-tool-call F7 enforcement check and return the outcome
    as a flat metadata dict.

    Designed for tools that don't manage active_mode resolution
    themselves — they call this helper at the top of ``execute()``::

        f7 = enforce_for_tool_call(self)
        if f7 and f7.get("outcome") == "denied":
            return ToolResult(success=False, error=..., metadata=f7)

    Returns:
        ``None`` when the ``coder_permission_mode_v2`` toggle is off
        (legacy path stays in force).  ``None`` is also the fail-soft
        return for any internal error so a buggy enforcer never blocks
        production traffic.

        Otherwise a dict with::

            {
              "f7_enforcer": True,
              "outcome": "allowed" | "denied",
              "active_mode": <PermissionMode.name>,
              "required_mode": <PermissionMode.name>,
              "reason": <str>,  # empty when allowed
            }

    Resolution order for ``active_mode``:
      1. Explicit ``active_mode=`` keyword (BashExecTool's pattern).
      2. ``resolve_active_for_milestone(milestone_id)`` when
         ``milestone_id`` is provided (plan-mode clamps to ReadOnly).
      3. The :data:`runtime.policy.permission_mode._ACTIVE_PERMISSION_MODE`
         ContextVar (default WorkspaceWrite).

    Sprint 6 PR-4b — toggle gate ``coder_permission_mode_v2`` removed:
    V2 lattice is the only permission path; flipping the toggle off
    used to disable F7 silently while leaving the resolver V2-only,
    which produced a confusing "no rollback + no F7" state.  F7 now
    runs unconditionally — the resolver and enforcer are both V2.
    """
    try:
        if active_mode is None:
            from vendor_runtime_sdk.runtime.policy.permission_mode import resolve_active_for_milestone

            active_mode = resolve_active_for_milestone(milestone_id)
        result = PermissionEnforcer(active_mode=active_mode).check_for_tool(tool)

        # Sprint 10 PR-6 (T2.3) — plan-mode denial reason injection.
        # When a tool call is denied AND the milestone is in plan-
        # mode, surface a structured ``plan_mode_blocked`` marker so
        # the LLM gets a clear signal "you're in plan mode; you can
        # plan but not execute".  Otherwise the generic "requires X
        # privilege" reason looks like a session-level access denial
        # rather than a stage-level one.
        reason = result.reason
        if result.outcome == "denied":
            try:
                from vendor_runtime_sdk.runtime.policy.permission_mode import (
                    is_plan_mode_active_for_milestone,
                )

                if is_plan_mode_active_for_milestone(milestone_id):
                    reason = (
                        f"plan_mode_blocked: {reason}"
                        if reason
                        else "plan_mode_blocked"
                    )
            except Exception:  # pragma: no cover — defensive
                pass

        meta = {
            "f7_enforcer": True,
            "outcome": result.outcome,
            "active_mode": result.active_mode.name,
            "required_mode": result.required_mode.name,
            "reason": reason,
        }
        # Telemetry: only emit on denial — allow events would be too noisy.
        if result.outcome == "denied":
            _emit_f7_denied_span(
                tool_name=getattr(tool, "name", type(tool).__name__),
                meta=meta,
            )
        return meta
    except Exception:  # pragma: no cover — defensive
        logger.warning(
            "enforce_for_tool_call: unexpected error; defaulting to allow",
            exc_info=True,
        )
        return None


def _emit_f7_denied_span(*, tool_name: str, meta: Dict[str, Any]) -> None:
    """Fire-and-forget SpanEvent + counter bump for F7_DENIED. Fail-soft."""
    try:
        from vendor_runtime_sdk.runtime.telemetry import SpanEvent, SpanType, get_recorder

        recorder = get_recorder()
        recorder.record_span_event(
            SpanEvent(
                span_type=SpanType.F7_DENIED,
                metadata={
                    "tool": tool_name,
                    "active_mode": meta.get("active_mode"),
                    "required_mode": meta.get("required_mode"),
                    "reason": meta.get("reason"),
                },
            )
        )
        recorder.inc_f7_denied()
    except Exception:  # pragma: no cover — defensive
        pass


__all__ = ["PermissionEnforcer", "enforce_for_tool_call"]
