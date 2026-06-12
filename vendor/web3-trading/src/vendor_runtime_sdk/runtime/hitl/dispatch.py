# -*- coding: utf-8 -*-
"""
runtime.hitl.dispatch — runtime-agnostic HITL decision dispatcher.

Sprint 2 PR-M1 (docs/TUI-Web-Runtime同构化技术方案.md §A1).

History
-------
``_resolve_hitl_decision`` was first introduced in PR-J inside
``cli/local_runtime.py``. It does not depend on ``LocalRuntime`` state
— pure dispatch logic on top of the ``PermissionPrompter`` Protocol +
the legacy ``approval_callback`` bool callback. PR-M1 lifts it into
``runtime.hitl`` so both ``LocalRuntime`` (today) and
``ConversationRuntime`` (Sprint 3 PR-M2+) can consume the same
implementation. ``cli.local_runtime`` re-exports the symbols for
back-compat — no test or caller import changes required.

Contract
--------
Two HITL inputs are supported; ``prompter`` wins when both are set:

* ``prompter`` (preferred, Sprint 2+) — converts the envelope dict to a
  ``PermissionRequest``, awaits ``prompter.prompt(req)``, then
  extracts ``decision.allowed`` (bool surface). When the prompter
  returns ``edited_args`` and the gate was approved, those edits are
  written back into the original envelope so downstream resume code
  (``_resume_after_approval``) reads the user's correction. Denied
  gates never propagate edits.

* ``callback`` (legacy, pre-Sprint-2) — calls ``callback(envelope)``
  and coerces the possibly-awaitable return to ``bool``.

Both paths are **fail-closed**: any exception → ``False`` (deny). The
runtime layer logs and updates FSM state; this helper only resolves
the bool decision.

The envelope shape is the canonical ``hitl_pending`` dict (same as
the SSE ``REQUIRES_APPROVAL`` event's ``extraInfo``). Both V1 and V2
field names are accepted on input (``tool_args`` legacy mirror +
``reason`` fallback) so callers don't have to normalise.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, Optional, Union

from vendor_runtime_sdk.runtime.protocols.permission_prompter import (
    PermissionDecision,
    PermissionPrompter,
    PermissionRequest,
)

logger = logging.getLogger(__name__)


# Type alias preserved for back-compat (cli.local_runtime re-exports it).
ApprovalCallback = Callable[
    [Dict[str, Any]],
    Union[bool, Awaitable[bool]],
]


async def resolve_hitl_decision(
    *,
    envelope: Dict[str, Any],
    prompter: Optional[PermissionPrompter] = None,
    callback: Optional[ApprovalCallback] = None,
    storage: Optional[Any] = None,
    session_id: str = "",
    workspace_id: str = "",
    decided_by: str = "",
) -> bool:
    """Unified HITL dispatch — see module docstring.

    Returns the bool ``allowed`` decision after running the appropriate
    code path (prompter / callback / fail-closed default). The runtime
    that called this helper is responsible for FSM transitions, event
    yielding, and any resume-on-approve flow.

    Sprint 2 PR-N+1 fix: when the prompter path returns
    ``decision.scope in {"session", "forever"}`` AND ``storage`` /
    ``session_id`` / ``workspace_id`` are supplied, persist the
    decision to ``storage.hitl_gates.record_session_decision(...)``
    so future identical gates can short-circuit. Without this, the
    TUI's ``s``/``f`` keyboard shortcuts would set scope on the
    decision but have no operational effect — see review M1.

    The scope-persistence write is **fail-soft**: any exception logs
    at WARN and the bool gate result still propagates. Persistence
    failure must never block the in-flight tool call.
    """
    if prompter is not None:
        # Sprint 2 PR-O0: check decision_memory BEFORE invoking the
        # prompter. When a previous turn recorded a session/forever
        # "allow" for this (session, tool, args), short-circuit and
        # don't prompt again. This closes the loop with PR-N+1 M1
        # which writes the decisions — without this check, the TUI's
        # ``s`` / ``f`` shortcuts only updated the audit trail but
        # the next identical gate still prompted.
        #
        # Fail-soft: lookup errors don't break the gate. We continue
        # to prompter on any failure.
        if await _check_short_circuit(
            envelope=envelope,
            storage=storage,
            session_id=session_id,
            workspace_id=workspace_id,
        ):
            logger.info(
                "hitl.dispatch: short-circuit hit for tool=%s session=%s "
                "(prior session/forever decision)",
                envelope.get("tool_name", "?"), session_id,
            )
            return True

        try:
            request = build_request_from_envelope(envelope)
            decision = await prompter.prompt(request)
        except Exception as exc:  # noqa: BLE001 — fail-closed
            logger.warning(
                "hitl.dispatch: prompter.prompt raised for tool=%s — %s "
                "(treating as deny)",
                envelope.get("tool_name", "?"), exc,
            )
            return False
        if not isinstance(decision, PermissionDecision):
            logger.warning(
                "hitl.dispatch: prompter returned %r (expected "
                "PermissionDecision) — treating as deny",
                type(decision).__name__,
            )
            return False
        # Sprint 2 PR-K: when the prompter returns ``edited_args``,
        # write them back into the original envelope so the runtime's
        # downstream resume path reads the user's correction. This
        # preserves the long-standing in-place-mutation contract that
        # pre-PR-K callbacks relied on (``ApprovalRow.apply_modified_input``
        # mutates ``pending_ref["arguments"]``).
        if decision.allowed and decision.edited_args is not None:
            envelope["arguments"] = dict(decision.edited_args)
            # Keep the legacy ``tool_args`` mirror in sync so any
            # consumer reading the older field name also sees the edit.
            envelope["tool_args"] = dict(decision.edited_args)
        # Sprint 2 PR-N+1 M1: persist scope=session/forever decisions
        # so future identical gates short-circuit via decision_memory.
        # Fail-soft: bool gate result propagates regardless of write
        # outcome — persistence is a courtesy, not the source of truth.
        if (
            decision.allowed
            and decision.scope in ("session", "forever")
            and storage is not None
            and session_id
        ):
            await _persist_scope_decision(
                storage=storage,
                session_id=session_id,
                workspace_id=workspace_id,
                tool_name=str(envelope.get("tool_name") or ""),
                decided_by=decided_by or decision.decided_by,
            )
        return bool(decision.allowed)

    if callback is None:
        # No HITL input supplied — caller should have routed to the
        # ``requires_approval`` yield path before reaching here.
        # Fail-closed as the safe default.
        return False

    try:
        result = callback(envelope)
        if asyncio.iscoroutine(result):
            result = await result
        return bool(result)
    except Exception as exc:  # noqa: BLE001 — fail-closed
        logger.exception("hitl.dispatch: approval_callback raised: %s", exc)
        return False


async def _check_short_circuit(
    *,
    envelope: Dict[str, Any],
    storage: Optional[Any],
    session_id: str,
    workspace_id: str,
) -> bool:
    """Sprint 2 PR-O0 — query ``storage.hitl_gates.lookup_session_decision``
    to decide whether the gate can short-circuit.

    Returns ``True`` only when there's a recorded ``"allow"`` for this
    ``(session_id, tool_name)`` in the storage backend. Every other
    code path (missing storage / missing method / lookup raises /
    no match / missing identifiers) returns ``False`` so the runtime
    falls through to the normal prompter path.

    Fail-soft: lookup is operational sugar, not the source of truth.
    The runtime layer still drives the actual decision — short-circuit
    is just "we already asked, don't ask again".
    """
    tool_name = str(envelope.get("tool_name") or "")
    if not tool_name or not session_id:
        return False
    if storage is None:
        return False
    hitl_gates = getattr(storage, "hitl_gates", None)
    if hitl_gates is None:
        return False
    lookup = getattr(hitl_gates, "lookup_session_decision", None)
    if lookup is None:
        return False
    try:
        verdict = await lookup(
            session_id=session_id,
            workspace_id=workspace_id,
            tool_name=tool_name,
            arguments=envelope.get("arguments") or envelope.get("tool_args"),
        )
    except Exception as exc:  # noqa: BLE001 — never break the gate
        logger.debug(
            "hitl.dispatch: lookup_session_decision raised (%s) — "
            "falling through to prompter",
            exc,
        )
        return False
    return verdict == "allow"


async def _persist_scope_decision(
    *,
    storage: Any,
    session_id: str,
    workspace_id: str,
    tool_name: str,
    decided_by: str = "",
) -> None:
    """Sprint 2 PR-N+1 M1 — write a session/forever decision to
    ``storage.hitl_gates.record_session_decision`` so future identical
    gates short-circuit.

    Defensive at every step:
    * Empty ``tool_name`` → skip (without a tool_name we can't match
      future gates anyway).
    * ``storage`` lacking ``hitl_gates`` attribute → skip.
    * ``hitl_gates`` lacking ``record_session_decision`` method →
      skip (covers partial mocks / older backends).
    * Any exception during the write → WARN log + swallow.

    This helper is callable from any runtime (LocalRuntime via the
    dispatch helper, ConversationRuntime once it migrates in Sprint 3+).
    """
    if not tool_name:
        return
    hitl_gates = getattr(storage, "hitl_gates", None)
    if hitl_gates is None:
        return
    record = getattr(hitl_gates, "record_session_decision", None)
    if record is None:
        return
    try:
        await record(
            session_id=session_id,
            workspace_id=workspace_id,
            tool_name=tool_name,
            action="allow",
            decided_by=decided_by,
        )
        logger.info(
            "hitl.dispatch: persisted session decision tool=%s "
            "session=%s workspace=%s",
            tool_name, session_id, workspace_id,
        )
    except Exception as exc:  # noqa: BLE001 — never break the gate
        logger.warning(
            "hitl.dispatch: record_session_decision raised for tool=%s "
            "session=%s — %s (gate result unaffected)",
            tool_name, session_id, exc,
        )


def build_envelope_from_hitl_exception(
    exc: Any,
    *,
    v2: bool = True,
) -> Dict[str, Any]:
    """Sprint 2 PR-M2 — convert a ``HITLRequiredError`` into the
    canonical ``hitl_pending`` envelope dict.

    This is the third entry into the envelope ↔ request namespace,
    paired with:

    * ``build_request_from_envelope(envelope) → PermissionRequest`` —
      consumed by ``LocalRuntime`` when a dict envelope is already in
      hand.
    * ``PermissionRequest.to_envelope() → dict`` — used by prompters
      that need the SSE shape to emit/persist.

    This helper closes the loop: agent-layer code raises
    ``HITLRequiredError`` carrying attributes (``tool_name`` /
    ``approval_id`` / ``rule_id`` / ``risk_level`` / ``editable_args``
    / ``tool_call_id`` / ``tool_args`` / ``reason``), and the runtime
    needs a normalised envelope dict to feed both the SSE emit and
    the persistence call. Previously inlined at
    ``runtime/conversation/_stream.py:858-890``; lifted here so
    ``ConversationRuntime`` and any future runtime (CLI/TUI when they
    converge in Sprint 3+) share one envelope-construction
    implementation.

    Parameters
    ----------
    exc : Any
        The exception object. ``HITLRequiredError`` defines the
        canonical attribute set, but the helper uses ``getattr`` for
        every field so test stubs (``SimpleNamespace`` / ``MagicMock``)
        and pre-V2 exception variants both work.
    v2 : bool, default True
        When ``True`` (the modern default, matching the
        ``hitl_v2_protocol`` toggle), the envelope carries the full
        V2 field set (``approval_id`` / ``tool_call_id`` /
        ``arguments`` / ``risk_level`` / ``editable_args`` /
        ``scope_options``). When ``False``, downgrades to the V1
        minimum (``tool_name`` / ``tool_args`` / ``policy_message`` /
        ``rule_id``) for back-compat with frontends that haven't
        migrated to the V2 envelope.

    Returns
    -------
    A dict ready to drop into ``StreamResponse.extraInfo`` and
    ``storage.hitl_gates.save_pending(envelope=...)``. Never raises —
    every attribute access falls back to a sensible default.
    """
    # ``tool_args`` is the V1 legacy field name; ``arguments`` was
    # added in V2 as the canonical name. Older agent code paths still
    # populate ``tool_args``, so read it and use as the source of
    # truth — keep the legacy field as a mirror for back-compat
    # consumers.
    _arguments = getattr(exc, "tool_args", None) or {}
    if not isinstance(_arguments, dict):
        _arguments = {}

    envelope: Dict[str, Any] = {
        "tool_name": getattr(exc, "tool_name", "") or "",
        # Legacy mirror — drop in next major release.
        "tool_args": dict(_arguments),
        "policy_message": getattr(exc, "reason", "") or "",
        "rule_id": getattr(exc, "rule_id", None),
    }
    if v2:
        envelope.update({
            "approval_id": getattr(exc, "approval_id", None) or "",
            "tool_call_id": getattr(exc, "tool_call_id", None),
            # New canonical field (HITL Redesign).
            "arguments": dict(_arguments),
            "risk_level": getattr(exc, "risk_level", "low") or "low",
            "editable_args": list(getattr(exc, "editable_args", ()) or ()),
            "scope_options": ["once", "session", "forever"],
        })
    return envelope


def build_request_from_envelope(envelope: Dict[str, Any]) -> PermissionRequest:
    """Convert the legacy ``hitl_pending`` envelope dict to a
    ``PermissionRequest``.

    Tolerates both field-name variants the codebase has carried:
    * ``arguments`` canonical + ``tool_args`` legacy mirror.
    * ``policy_message`` canonical + ``reason`` fallback.

    Coerces malformed ``arguments`` (string instead of dict — LLM
    hallucination) to ``{}`` rather than crashing.
    """
    arguments = envelope.get("arguments") or envelope.get("tool_args") or {}
    return PermissionRequest(
        tool_name=str(envelope.get("tool_name", "")),
        arguments=dict(arguments) if isinstance(arguments, dict) else {},
        risk_level=envelope.get("risk_level") or "low",
        tool_call_id=envelope.get("tool_call_id") or None,
        rule_id=envelope.get("rule_id") or None,
        policy_message=str(
            envelope.get("policy_message") or envelope.get("reason") or ""
        ),
        editable_args=list(envelope.get("editable_args") or []),
        scope_options=list(
            envelope.get("scope_options") or ("once", "session", "forever")
        ),
        approval_id=str(envelope.get("approval_id") or ""),
        qa_id=str(envelope.get("qa_id") or ""),
    )


__all__ = [
    "ApprovalCallback",
    "build_envelope_from_hitl_exception",
    "build_request_from_envelope",
    "resolve_hitl_decision",
]
