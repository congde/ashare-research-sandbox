# -*- coding: utf-8 -*-
"""
TerminalPrompter — in-process HITL prompter for the CLI / TUI path.

Sprint 2 PR-I (docs/TUI-Web-Runtime同构化技术方案.md §A1, counterpart to
the deferred ``WebSseHitlPrompter``).

Wraps the existing CLI / TUI ``ApprovalCallback`` shape
(``Callable[[Dict[str, Any]], Union[bool, Awaitable[bool]]]`` — defined
at ``cli.local_runtime:122``) into the canonical
``PermissionPrompter.prompt()`` Protocol. This lets a single
``ConversationRuntime`` drive both Web (deferred, off-process via
``WebSseHitlPrompter``) and CLI / TUI (in-process, synchronous reply
via this prompter) without conditionals at call sites.

Two-prompter convergence
------------------------
Same Protocol shape, two implementations:

* ``WebSseHitlPrompter.prompt(req)`` — persists pending + emits SSE,
  raises ``HitlPendingError`` so the runtime ends the turn. The user
  decision arrives on a SEPARATE HTTP request (``POST /hitl/decide``).
* ``TerminalPrompter.prompt(req)`` — calls the in-process callback
  (Typer prompt / TUI ``ApprovalBroker`` future / scripted yes-no),
  returns ``PermissionDecision`` synchronously. The runtime continues
  the turn without termination.

Callback contract
-----------------
The wrapped callback receives a dict matching the SSE / Mongo
``hitl_pending`` envelope (via ``PermissionRequest.to_envelope()``):
``tool_name`` / ``arguments`` / ``tool_args`` legacy mirror /
``rule_id`` / ``policy_message`` / ``risk_level`` / ``editable_args``
/ ``scope_options`` / ``approval_id`` / ``tool_call_id``.

The callback may be:
* Sync: ``def cb(envelope) -> bool``.
* Async: ``async def cb(envelope) -> bool`` (the wrapper awaits the
  returned coroutine).

Return shapes
-------------
* ``True`` → ``PermissionDecision(allowed=True, scope="once",
  decided_by=...)``. The scope default is ``"once"`` because the
  existing CLI / TUI callbacks return a bare bool — they don't yet
  expose scope selection. Scope-aware callbacks should call this
  prompter via the ``rich_callback`` form (see below).
* ``False`` → ``PermissionDecision(allowed=False, reason="denied by
  user")``.
* Exception → ``PermissionDecision(allowed=False, reason=...)`` —
  fail-closed; matches existing ``LocalRuntime`` behaviour at line 2154.

The ``decided_by`` field is sourced from the constructor; CLI passes
``user_id`` from ``CliConfig`` / TUI passes the JWT-resolved user id.

Rich-decision callback (optional)
---------------------------------
If the caller has a richer prompter (e.g. a TUI modal that returns
scope + edited args), they can pass ``rich_callback`` instead of
``callback``. Signature:
``Callable[[Dict], Union[PermissionDecision, Awaitable[PermissionDecision]]]``.
The two callback fields are mutually exclusive at construction.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Awaitable, Callable, Dict, Optional, Union

from vendor_runtime_sdk.runtime.protocols.permission_prompter import (
    PermissionDecision,
    PermissionRequest,
)

logger = logging.getLogger(__name__)


# ``ApprovalCallback`` is the canonical bool-returning CLI / TUI shape.
# Lives in ``runtime.hitl.dispatch`` (Sprint 2 PR-M1) so both
# ``TerminalPrompter`` and ``resolve_hitl_decision`` reference a single
# definition. Re-exported here to keep this module's import surface
# intact for callers that read ``terminal_prompter.ApprovalCallback``.
from vendor_runtime_sdk.runtime.hitl.dispatch import ApprovalCallback  # noqa: E402

# Rich callback returns the structured ``PermissionDecision`` directly —
# specific to ``TerminalPrompter``; not duplicated elsewhere.
RichApprovalCallback = Callable[
    [Dict[str, Any]],
    Union[PermissionDecision, Awaitable[PermissionDecision]],
]


class TerminalPrompter:
    """In-process prompter — wraps a yes / no callback into the Protocol.

    Construction
    ------------
    Exactly one of ``callback`` / ``rich_callback`` must be supplied.

    * ``callback`` — legacy CLI / TUI shape (returns ``bool``). The
      wrapper synthesises a ``PermissionDecision`` with ``scope="once"``
      and ``decided_by`` from the constructor.
    * ``rich_callback`` — full ``PermissionDecision`` return. Use this
      when the prompter UI lets the user pick a scope / edit args.

    * ``decided_by`` — operator identity stamped onto the decision when
      ``callback`` is used (sync, scope-less). Ignored with
      ``rich_callback`` — that path returns its own ``decided_by``.
    """

    def __init__(
        self,
        *,
        callback: Optional[ApprovalCallback] = None,
        rich_callback: Optional[RichApprovalCallback] = None,
        decided_by: str = "",
    ) -> None:
        if callback is None and rich_callback is None:
            raise ValueError(
                "TerminalPrompter requires exactly one of `callback` or "
                "`rich_callback`"
            )
        if callback is not None and rich_callback is not None:
            raise ValueError(
                "TerminalPrompter: `callback` and `rich_callback` are "
                "mutually exclusive"
            )
        self._callback = callback
        self._rich_callback = rich_callback
        self._decided_by = decided_by

    async def prompt(self, request: PermissionRequest) -> PermissionDecision:
        """Call the wrapped callback and return its decision.

        Fail-closed on callback exception: matches the long-existing
        ``LocalRuntime`` behaviour (``local_runtime.py:2153-2155`` —
        callback raised → ``decision = False``). The reason carries
        the exception's repr so audit logs can still correlate the
        denial.
        """
        envelope = request.to_envelope()

        if self._rich_callback is not None:
            return await self._invoke_rich(envelope)

        # Sync / async bool callback path.
        try:
            result = self._callback(envelope)  # type: ignore[misc]
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:  # noqa: BLE001 — fail-closed
            logger.warning(
                "TerminalPrompter: callback raised for tool=%s — %s "
                "(treating as deny)",
                request.tool_name, exc,
            )
            return PermissionDecision(
                allowed=False,
                reason=f"callback raised: {exc!r}",
                decided_by=self._decided_by,
            )

        allowed = bool(result)
        return PermissionDecision(
            allowed=allowed,
            reason="" if allowed else "denied by user",
            scope="once" if allowed else None,
            decided_by=self._decided_by,
        )

    async def _invoke_rich(
        self, envelope: Dict[str, Any],
    ) -> PermissionDecision:
        """Path for ``rich_callback`` — caller already returns
        ``PermissionDecision``. We just await + sanity-check."""
        assert self._rich_callback is not None  # narrow for mypy
        try:
            result = self._rich_callback(envelope)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:  # noqa: BLE001 — fail-closed
            logger.warning(
                "TerminalPrompter: rich_callback raised — %s "
                "(treating as deny)",
                exc,
            )
            return PermissionDecision(
                allowed=False,
                reason=f"rich_callback raised: {exc!r}",
                decided_by=self._decided_by,
            )

        if not isinstance(result, PermissionDecision):
            logger.warning(
                "TerminalPrompter: rich_callback returned %r (expected "
                "PermissionDecision) — treating as deny",
                type(result).__name__,
            )
            return PermissionDecision(
                allowed=False,
                reason=f"rich_callback returned unexpected type: {type(result).__name__}",
                decided_by=self._decided_by,
            )
        return result


__all__ = [
    "ApprovalCallback",
    "RichApprovalCallback",
    "TerminalPrompter",
]
