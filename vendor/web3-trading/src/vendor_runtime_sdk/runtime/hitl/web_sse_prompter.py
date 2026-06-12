# -*- coding: utf-8 -*-
"""
WebSseHitlPrompter — deferred HITL prompter for the Web/HTTP request path.

Sprint 0 PR-D delivery (docs/TUI-Web-Runtime同构化技术方案.md §A1).

Wire shape (mirror of the inline behaviour in
``runtime/conversation/_stream.py:830-920`` today):

1. Agent's tool execution path raises ``HITLRequiredError`` (or upstream
   policy resolver returns ``ask``).
2. ``ConversationRuntime`` constructs a ``PermissionRequest`` from the
   exception's fields and calls ``await prompter.prompt(request)``.
3. ``WebSseHitlPrompter.prompt(request)`` does THREE things atomically:
   a. Persists the pending gate via
      ``storage.hitl_gates.save_pending(...)`` (so ``POST /hitl/decide``
      can later read what was pending).
   b. Calls ``sse_emit(envelope)`` which yields the
      REQUIRES_APPROVAL frame onto the active SSE stream.
   c. Raises ``HitlPendingError`` — the caller (runtime) catches this
      to terminate the turn cleanly and let the SSE consumer pause.

The user's eventual decision arrives on a SEPARATE HTTP request
(``POST /hitl/decide``) which calls ``continue_after_hitl_approval``;
that spawns a NEW agent run with the decision baked into the prompt
— this prompter is NOT involved in the decision-delivery half of the
cycle. Sprint 1 PR-E wires the runtime to actually call this
prompter instead of inlining the same logic.

What this prompter does NOT do
------------------------------
* Wait for a decision (the Web path is asynchronous off-process).
* Validate decisions (the ``/hitl/decide`` endpoint does that).
* Mutate FSM (the runtime owns FSM transitions; we just emit the
  signal).

Failure modes
-------------
* ``storage.hitl_gates.save_pending`` raise → log + emit SSE anyway +
  raise ``HitlPendingError`` (frontend gate still works visually; the
  resume path may 404 if it can't find the persisted envelope — the
  frontend already handles this by re-fetching ``session_meta``).
* ``sse_emit`` raise → log + raise ``HitlPendingError`` (decision arm
  is independent; the user can still click approve and the resumed
  agent re-emits its terminal status).
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from vendor_runtime_sdk.runtime.protocols.permission_prompter import (
    HitlPendingError,
    PermissionDecision,
    PermissionRequest,
)

logger = logging.getLogger(__name__)


# Type alias for the SSE emit callback. The runtime wires this to a
# closure that ``yield``s on the active SSE generator. Return value is
# ignored; the callback may be sync or async.
SseEmitCallback = Callable[[Dict[str, Any]], Optional[Awaitable[None]]]


class WebSseHitlPrompter:
    """Deferred prompter — persists + emits + raises.

    Construction
    ------------
    * ``storage`` — anything carrying a ``hitl_gates: HitlGateRepository``
      attribute. Typically a ``MongoStorageBackend`` instance, but any
      ``StorageBackend`` Protocol implementation works (the sqlite
      backend is wired the same way for parity tests).
    * ``sse_emit`` — callable that puts the envelope on the active SSE
      stream. The runtime wires this to a closure that yields the
      ``REQUIRES_APPROVAL`` ``StreamResponse`` JSON.
    * ``session_id`` / ``workspace_id`` / ``qa_id`` — three identity
      fields the storage path needs. ``qa_id`` MAY also live on the
      ``PermissionRequest`` (the SSE consumer cares); when both are
      set, ``request.qa_id`` wins (per the chained-V2-HITL fix in
      ``_stream.py:_persist_hitl_pending``).
    """

    def __init__(
        self,
        *,
        storage: Any,
        sse_emit: SseEmitCallback,
        session_id: str,
        workspace_id: str,
        qa_id: str = "",
    ) -> None:
        self._storage = storage
        self._sse_emit = sse_emit
        self._session_id = session_id
        self._workspace_id = workspace_id
        self._qa_id = qa_id

    async def prompt(self, request: PermissionRequest) -> PermissionDecision:
        """Persist pending → emit SSE → raise ``HitlPendingError``.

        Returns
        -------
        Never returns normally. The Web/HTTP path delivers the user
        decision via a *separate* request, not via this coroutine.
        ``PermissionDecision`` is in the signature only to satisfy the
        ``PermissionPrompter`` Protocol shape — Sprint 1 PR-E's
        ``TerminalPrompter`` actually returns one.

        Raises
        ------
        HitlPendingError
            Always. ``ConversationRuntime`` catches this and treats
            this turn as ``requires_approval`` terminal.
            When BOTH ``save_pending`` AND ``sse_emit`` raised, the
            exception's ``double_failure`` attribute is ``True`` so the
            runtime can surface a fallback error envelope to the
            consumer rather than transitioning to a normal pending
            state (the chat would hang forever otherwise — neither the
            SSE event arrived nor a persisted envelope exists).
        """
        envelope = request.to_envelope()
        # The qa_id on the request wins over the constructor-time
        # qa_id when set — chained-V2-HITL pinning. The persistence
        # path needs an explicit qa_id kwarg, so resolve it here.
        qa_id = request.qa_id or self._qa_id

        # ── Persist (fail-soft, track failure) ────────────────────────
        save_failed = False
        save_exc: Optional[BaseException] = None
        try:
            await self._storage.hitl_gates.save_pending(
                session_id=self._session_id,
                workspace_id=self._workspace_id,
                qa_id=qa_id,
                envelope=envelope,
            )
        except Exception as exc:  # noqa: BLE001 — never break the gate
            save_failed = True
            save_exc = exc
            logger.warning(
                "WebSseHitlPrompter[%s]: save_pending failed — %s "
                "(SSE event will still emit; resume may 404 unless "
                "the frontend re-fetches)",
                self._session_id, exc,
            )

        # ── Emit SSE event (fail-soft, track failure) ─────────────────
        emit_failed = False
        emit_exc: Optional[BaseException] = None
        try:
            result = self._sse_emit(envelope)
            if result is not None and hasattr(result, "__await__"):
                await result
        except Exception as exc:  # noqa: BLE001 — caller handles the raise
            emit_failed = True
            emit_exc = exc
            logger.warning(
                "WebSseHitlPrompter[%s]: sse_emit failed — %s "
                "(decision arm independent; resumed agent will re-emit "
                "terminal status)",
                self._session_id, exc,
            )

        # ── Double-failure → ERROR + flag the exception ───────────────
        double_failure = save_failed and emit_failed
        if double_failure:
            logger.error(
                "WebSseHitlPrompter[%s]: DOUBLE FAILURE — save_pending(%s) "
                "AND sse_emit(%s) both raised. The consumer will neither "
                "receive a REQUIRES_APPROVAL event nor find a persisted "
                "envelope on resume. Runtime must surface a fallback "
                "error to the SSE stream.",
                self._session_id, save_exc, emit_exc,
            )

        # ── Signal "turn is done, decision off-process" ───────────────
        raise HitlPendingError(request, double_failure=double_failure)


__all__ = ["WebSseHitlPrompter", "SseEmitCallback"]
