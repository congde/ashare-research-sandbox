"""
Protocol 3: Permission Prompter — HITL 权限提示抽象 (§4.2 / §A1).

Defines the contract for HITL permission prompting and the canonical
request/decision envelopes.

Two implementations live downstream:

* ``runtime.hitl.web_sse_prompter.WebSseHitlPrompter`` (Web/HTTP path)
  — persists the pending gate via ``storage.hitl_gates.save_pending``,
  emits a REQUIRES_APPROVAL SSE event to the chat consumer, then signals
  the runtime to terminate this turn by raising ``HitlPendingError``.
  The actual user decision arrives on a SEPARATE HTTP request
  (``POST /hitl/decide``) which spawns a new agent run via
  ``continue_after_hitl_approval``.

* ``runtime.hitl.terminal_prompter.TerminalPrompter`` (CLI/TUI path,
  PR-E lands the implementation) — wraps the existing
  ``approval_callback: Callable[[dict], bool]`` shape into the Protocol
  so the same runtime can drive both contexts.

Sprint 0 PR-D extends the canonical envelope with the full set of
fields the Web SSE event already carries:
* ``tool_call_id`` — pairs the gate with the in-flight tool call so
  V2 resume can re-execute the exact same call.
* ``arguments`` (was ``args``) — canonical name; ``tool_args`` legacy
  mirror lives on the SSE envelope only.
* ``rule_id`` / ``policy_message`` — which PolicyEngine rule fired.
* ``editable_args`` — keys the user is allowed to edit in the chat UI
  before approving (e.g. ``["cmd"]`` for ``bash_exec``).
* ``scope_options`` — choices presented to the user (``["once",
  "session", "forever"]``). ``PermissionDecision.scope`` carries the
  user's selection.
* ``approval_id`` — server-side row id; used by the resume path to
  correlate decision events with the original gate.
* ``qa_id`` — the SSE channel id the consumer is listening on; pinning
  this lets ``continue_after_hitl_approval`` deliver the terminal
  status update to the correct cache key (see `[[chained-v2-hitl]]`
  fix in ``_stream.py:_persist_hitl_pending``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Protocol


_DEFAULT_SCOPE_OPTIONS: tuple = ("once", "session", "forever")


@dataclass
class PermissionRequest:
    """Canonical HITL request envelope — fields match the SSE
    REQUIRES_APPROVAL ``extraInfo`` payload exactly so the prompter +
    SSE emitter can share a single dict.

    Required fields (the gate fires with at minimum these):
    * ``tool_name`` — what tool is about to run.
    * ``arguments`` — payload the tool would receive.
    * ``risk_level`` — PolicyEngine risk tier.

    Recommended fields (carried by the V2 envelope):
    * ``tool_call_id`` — id from the LLM's tool_use event; pairs the
      gate with the in-flight call. Required for V2 resume to
      re-execute the exact same call rather than a fresh re-plan.
    * ``rule_id`` / ``policy_message`` — which rule fired and the
      human-readable reason.
    * ``editable_args`` — keys the user can edit before approving.
    * ``scope_options`` — choices presented to the user; defaults
      include all three (``once``, ``session``, ``forever``).
    * ``approval_id`` — server-side correlation id; allocated upstream
      (Gateway / agent loop), passed through unchanged.
    * ``qa_id`` — the SSE channel id; used by the resume path to
      route the terminal status update.
    """

    tool_name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    risk_level: Literal["low", "medium", "high"] = "low"
    tool_call_id: Optional[str] = None
    rule_id: Optional[str] = None
    policy_message: str = ""
    editable_args: List[str] = field(default_factory=list)
    scope_options: List[str] = field(default_factory=lambda: list(_DEFAULT_SCOPE_OPTIONS))
    approval_id: str = ""
    qa_id: str = ""

    # ── Back-compat shim ──────────────────────────────────────────────
    @property
    def args(self) -> Dict[str, Any]:
        """Pre-PR-D code path used ``request.args``; keep the alias so
        any legacy reader still works. Returns a SHALLOW COPY (Sprint 1
        PR-H review L4) so a legacy caller mutating ``args`` thinking
        it's a private view doesn't corrupt the canonical ``arguments``
        dict. Writers should use ``arguments`` directly."""
        return dict(self.arguments)

    def to_envelope(self) -> Dict[str, Any]:
        """Return the SSE ``extraInfo`` shape — single source of truth
        for both the SSE emitter and ``storage.hitl_gates.save_pending``.

        The legacy ``tool_args`` mirror is included so rolling-deploy
        Web clients without the canonical-field migration still work
        (see ``_stream.py:866``).
        """
        return {
            "tool_name": self.tool_name,
            "tool_args": dict(self.arguments),  # legacy mirror
            "arguments": dict(self.arguments),
            "policy_message": self.policy_message,
            "rule_id": self.rule_id,
            "approval_id": self.approval_id,
            "tool_call_id": self.tool_call_id,
            "risk_level": self.risk_level,
            "editable_args": list(self.editable_args),
            "scope_options": list(self.scope_options),
        }


@dataclass
class PermissionDecision:
    """User's response to a ``PermissionRequest``.

    Fields:
    * ``allowed`` — approve / deny.
    * ``reason`` — optional human text (denied + reason for audit log,
      or approved with note).
    * ``scope`` — which option from ``request.scope_options`` the user
      picked. ``None`` is treated as ``"once"`` by the runtime.
    * ``edited_args`` — when the chat UI lets the user adjust args
      (e.g. tweak the bash command before approval), the corrected
      payload lands here. ``None`` = no edit, use ``request.arguments``.
    * ``decided_by`` — user_id / employee_id who clicked the button.
      Recorded for audit trail.
    """

    allowed: bool
    reason: str = ""
    scope: Optional[Literal["once", "session", "forever"]] = None
    edited_args: Optional[Dict[str, Any]] = None
    decided_by: str = ""

    @property
    def effective_scope(self) -> str:
        """Canonical scope value — ``None`` → ``"once"``."""
        return self.scope or "once"


class HitlPendingError(Exception):
    """Sentinel raised by a deferred prompter (e.g. ``WebSseHitlPrompter``)
    when the decision will arrive on a *separate* HTTP request rather
    than in-process.

    ConversationRuntime catches this exception inside its turn loop:
    1. Emits REQUIRES_APPROVAL on the SSE stream (already done by the
       prompter before raising).
    2. Transitions FSM to REQUIRES_APPROVAL.
    3. Terminates the turn cleanly (no error surface to the LLM).

    The user's subsequent ``POST /hitl/decide`` triggers a NEW
    ``continue_after_hitl_approval`` agent run that resumes from the
    persisted ``hitl_pending`` envelope.

    Fields
    ------
    * ``request`` — the ``PermissionRequest`` that triggered the gate,
      attached so the runtime can log / correlate without re-reading
      storage.
    * ``double_failure`` — Sprint 1 PR-H review M2 fix: set to ``True``
      when BOTH the storage persistence path AND the SSE emit path
      raised. The runtime is expected to surface this state to the
      consumer (fallback error envelope, FSM → FAILED instead of
      REQUIRES_APPROVAL) rather than transitioning to a normal pending
      state — otherwise the chat bubble hangs forever waiting for an
      SSE event that never arrived AND a persisted envelope that
      doesn't exist for the resume path to find.
    """

    def __init__(
        self,
        request: PermissionRequest,
        message: str = "",
        *,
        double_failure: bool = False,
    ) -> None:
        super().__init__(message or f"HITL pending: {request.tool_name}")
        self.request = request
        self.double_failure = double_failure


class PermissionPrompter(Protocol):
    """Canonical Protocol — every prompter implementation routes user
    decisions through this single async entry point.

    Implementations:
    * In-process (CLI/TUI): ``.prompt()`` awaits an asyncio.Future on
      an external broker and returns the decision normally.
    * Deferred (Web SSE): ``.prompt()`` emits the SSE gate, persists
      pending, then raises ``HitlPendingError`` to signal "this turn
      is done; the decision will arrive separately".

    Method name is ``prompt`` (not ``decide``) — matches the Sprint 0
    pre-work convergence decision (the legacy ``decide`` definition in
    ``runtime/protocols.py`` was dead code per
    ``docs/Sprint0-Pre-work-报告.md §2``).
    """

    async def prompt(self, request: PermissionRequest) -> PermissionDecision: ...
