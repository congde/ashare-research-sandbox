# -*- coding: utf-8 -*-
"""PR-F7 — :class:`PermissionMode` 5-tier enum + :class:`EnforcementResult`.

Per :doc:`docs/CoderAgent-多文件任务完成率根因修复方案` §3.F7.

Borrowed from claw-code's ``permissions.rs``: a strongly-typed 5-step
ladder of permission modes plus a per-tool ``required_permission``
declaration replaces the legacy ``"always_ask" | "always_allow"`` binary
+ ``tier: int`` ad-hoc model.

Strict ordering (lowest → highest privilege):

    ReadOnly < Prompt < WorkspaceWrite < Allow < DangerFullAccess

* **ReadOnly** — read_file / glob / grep / list_directory.  No mutation.
* **Prompt** — gate that the resolver MUST surface to the user (HITL).
* **WorkspaceWrite** — write_file / edit_file / patch_apply inside the
  workspace boundary.  Path containment still enforced separately.
* **Allow** — any path write (still sandboxed, but workspace boundary
  no longer enforced).  Reserved for trusted CLI / power-user flows.
* **DangerFullAccess** — bash, network, system calls.  Effectively the
  shell.

A tool's ``required_permission`` declares the *minimum* mode under
which it may execute.  The :class:`PermissionEnforcer`
(``runtime.policy.enforcer``) compares the active session mode to the
required mode and emits an :class:`EnforcementResult`.

This module is purely additive — it ships behind
``coder_permission_mode_v2`` (default OFF), and ``BaseTool``'s legacy
``permission_policy`` / ``tier`` fields are untouched for the rollback
path.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Any, Dict, Literal, Optional


class RiskLevel(str, Enum):
    """HITL UI risk classification.

    Drives ApprovalCard visual treatment (badge colour) and is used by
    UX heuristics (e.g. ``high`` defaults focus to the *Reject* button,
    ``low`` defaults to *Allow once*). Strings — never integers — so the
    SSE wire format and Mongo persistence stay human-readable.

    Tools self-declare ``risk_level: RiskLevel = ...`` at class level.
    The default is :attr:`RiskLevel.LOW` because the safest fallback
    for an unmigrated tool is to surface an inconspicuous badge — every
    high-risk tool in the registry already overrides the default.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @classmethod
    def coerce(cls, value: Any) -> "RiskLevel":
        """Best-effort conversion. Unknown / wrong-typed inputs fall
        back to :attr:`LOW` rather than raising — HITL telemetry must
        never fail-loud just because a tool reported a bad label.
        """
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            normalised = value.strip().lower()
            for member in cls:
                if member.value == normalised:
                    return member
        return cls.LOW


class PermissionMode(IntEnum):
    """5-step privilege ladder. Higher integer ⇒ broader access.

    The integer values are stable across releases so they can be
    persisted to checkpoints / DB without coupling to enum names.
    """

    ReadOnly = 0
    Prompt = 1
    WorkspaceWrite = 2
    Allow = 3
    DangerFullAccess = 4

    @classmethod
    def from_str(cls, value: str) -> "PermissionMode":
        """Case-insensitive name → enum, accepting snake_case variants.

        Raises :class:`ValueError` on unknown names so caller code
        can decide whether to fail-closed (default) or fall back to a
        safe default.
        """
        if not isinstance(value, str):
            raise ValueError(f"PermissionMode requires a string, got {type(value).__name__}")
        normalised = value.strip().lower().replace("_", "").replace("-", "")
        for member in cls:
            if member.name.lower() == normalised:
                return member
        raise ValueError(
            f"unknown PermissionMode {value!r}; valid: "
            f"{[m.name for m in cls]}"
        )


@dataclass(frozen=True)
class EnforcementResult:
    """Structured outcome of :meth:`PermissionEnforcer.check`.

    HITL UIs render the fields directly — no string parsing required to
    surface "needs WorkspaceWrite permission" to the user.
    """

    outcome: Literal["allowed", "denied"]
    tool: str
    active_mode: PermissionMode
    required_mode: PermissionMode
    reason: str = ""

    # ── Constructors ───────────────────────────────────────────────────

    @classmethod
    def allow(
        cls,
        *,
        tool: str,
        active_mode: PermissionMode,
        required_mode: PermissionMode,
    ) -> "EnforcementResult":
        return cls(
            outcome="allowed",
            tool=tool,
            active_mode=active_mode,
            required_mode=required_mode,
            reason="",
        )

    @classmethod
    def deny(
        cls,
        *,
        tool: str,
        active_mode: PermissionMode,
        required_mode: PermissionMode,
        reason: str,
    ) -> "EnforcementResult":
        return cls(
            outcome="denied",
            tool=tool,
            active_mode=active_mode,
            required_mode=required_mode,
            reason=reason,
        )

    # ── Serialisation ──────────────────────────────────────────────────

    def to_metadata(self) -> Dict[str, Any]:
        """Flat dict suitable for ``ToolResult.metadata`` and HITL UIs."""
        return {
            "outcome": self.outcome,
            "tool": self.tool,
            "active_mode": self.active_mode.name,
            "required_mode": self.required_mode.name,
            "reason": self.reason,
        }


# ── Active mode ContextVar (F7 / F8 plumbing) ──────────────────────────────


_ACTIVE_PERMISSION_MODE: ContextVar[PermissionMode] = ContextVar(
    "runtime.policy.active_permission_mode",
    default=PermissionMode.WorkspaceWrite,
)


def get_active_permission_mode() -> PermissionMode:
    """Return the currently bound active mode for this context.

    Defaults to :attr:`PermissionMode.WorkspaceWrite` because that is
    the production expectation for most milestones. Plan-mode contexts
    should clamp to :attr:`PermissionMode.ReadOnly` via
    :func:`resolve_active_for_milestone`.
    """
    return _ACTIVE_PERMISSION_MODE.get()


def set_active_permission_mode(mode: PermissionMode) -> Token:
    """Bind *mode* in the current context. Returns a token for
    :func:`reset_active_permission_mode`."""
    if not isinstance(mode, PermissionMode):
        raise TypeError(
            f"set_active_permission_mode requires a PermissionMode, "
            f"got {type(mode).__name__}"
        )
    return _ACTIVE_PERMISSION_MODE.set(mode)


def reset_active_permission_mode(token: Token) -> None:
    """Restore the binding captured by :func:`set_active_permission_mode`."""
    _ACTIVE_PERMISSION_MODE.reset(token)


@contextmanager
def scoped_active_permission_mode(mode: PermissionMode):
    """Context manager that binds *mode* for the duration of the
    ``with`` block.

    Designed for the agent driver's plan-mode entry/exit: wrap
    ``loop.run()`` with this helper so tools that don't carry a
    ``milestone_id`` (write_file / edit_file / patch_apply) still see
    the clamped active mode through the ContextVar.

    Restores the prior binding on normal exit AND on exception, so a
    plan-mode loop that raises mid-run can't leak the clamp into
    subsequent runs.
    """
    token = set_active_permission_mode(mode)
    try:
        yield
    finally:
        reset_active_permission_mode(token)


def resolve_active_for_milestone(
    milestone_id: Optional[str],
) -> PermissionMode:
    """Resolve the effective active mode for *milestone_id*.

    Plan-mode milestones (per :class:`runtime.plan_mode.registry.PlanModeState`)
    clamp to :attr:`PermissionMode.ReadOnly` regardless of the
    ContextVar value — plan mode is read-only by contract.

    All other contexts return the ContextVar value (default
    :attr:`PermissionMode.WorkspaceWrite`).

    The resolver is the single source of truth for "what permission
    mode applies right now"; F7 / F8 callers should consult it rather
    than building their own clamp logic.
    """
    if milestone_id:
        try:
            from vendor_runtime_sdk.runtime.plan_mode.registry import get_plan_mode

            if get_plan_mode(milestone_id).active:
                return PermissionMode.ReadOnly
        except Exception:  # pragma: no cover — plan_mode registry should never fail
            pass
    return get_active_permission_mode()


def is_plan_mode_active_for_milestone(
    milestone_id: Optional[str],
) -> bool:
    """Return True when *milestone_id* is currently in plan-mode.

    Sprint 10 PR-6 helper — used by the F7 enforcer to inject the
    ``plan_mode_blocked`` reason into denial outcomes so the LLM can
    distinguish "you can't do that yet, you're in plan mode" from
    "your session lacks WorkspaceWrite privilege".
    """
    if not milestone_id:
        return False
    try:
        from vendor_runtime_sdk.runtime.plan_mode.registry import get_plan_mode

        return bool(get_plan_mode(milestone_id).active)
    except Exception:  # pragma: no cover — defensive
        return False


__all__ = [
    "EnforcementResult",
    "PermissionMode",
    "RiskLevel",
    "get_active_permission_mode",
    "is_plan_mode_active_for_milestone",
    "reset_active_permission_mode",
    "resolve_active_for_milestone",
    "scoped_active_permission_mode",
    "set_active_permission_mode",
]
