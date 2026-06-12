# -*- coding: utf-8 -*-
"""
ContextVar bridge from ConversationRuntime → llm.stream_llm.

Why this exists
---------------
Before this module, an LLM call that hit an availability error
(429 token-cap, provider 5xx, network flap) bubbled up to
``agent.run()``'s except block, which yielded a FAILED StreamResponse;
``ConversationRuntime.wrap_agent_stream`` then sniffed the FAILED
event, swapped the LLM client, and **restarted the entire
agent.run() generator**. For coordinator-style turns this caused the
whole specialist dispatch (3 threads × 60s + duplicate cost +
duplicate "Layer 1" envelope) to rerun from scratch — even though
only the final-response LLM call needed retrying.

This module exposes the live ``FallbackManager`` to ``stream_llm`` via
a ``ContextVar`` so the failing LLM call can swap to the next model
in the fallback chain *in place* and resume on the new client. The
agent code stays intact; the agent.run() generator is never restarted;
work done before the failure (planning, threads, tool results) is
preserved.

Contract
--------
- ``ConversationRuntime.wrap_agent_stream`` ``set_active_runtime`` on
  entry and resets the token in its ``finally`` so cross-turn / cross-
  session bleed is impossible. The ContextVar is async-task-local
  (``contextvars.copy_context`` semantics in asyncio) — concurrent
  turns get isolated views.
- ``stream_llm`` calls ``get_active_fallback_manager`` to ask for the
  current chain. ``None`` means "no fallback bridged" — old behaviour
  preserved (raise on non-retryable errors).
"""
from __future__ import annotations

import contextvars
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # avoid runtime cycle: runtime.fallback → runtime.* etc.
    from vendor_runtime_sdk.runtime.fallback.manager import FallbackManager


# Async-task-local pointer to the FallbackManager owned by the
# in-flight ConversationRuntime. None = no live runtime context (e.g.
# direct llm.stream_llm calls from tests / scripts).
_ACTIVE_FALLBACK_MGR: contextvars.ContextVar[Optional["FallbackManager"]] = (
    contextvars.ContextVar("ai_buddy_active_fallback_mgr", default=None)
)


def set_active_fallback_manager(
    mgr: Optional["FallbackManager"],
) -> contextvars.Token:
    """Set the current turn's FallbackManager.

    Returns a token the caller MUST pass to ``reset_active_fallback_manager``
    in its ``finally`` block. Mirrors ``ContextVar.set`` semantics.
    """
    return _ACTIVE_FALLBACK_MGR.set(mgr)


def reset_active_fallback_manager(token: contextvars.Token) -> None:
    """Restore the previous FallbackManager value (LIFO)."""
    try:
        _ACTIVE_FALLBACK_MGR.reset(token)
    except (LookupError, ValueError):
        # Token mismatch (typically because the token was created in a
        # different Context — happens when ConversationRuntime is reused
        # across loops in tests). Fall back to clearing.
        _ACTIVE_FALLBACK_MGR.set(None)


def get_active_fallback_manager() -> Optional["FallbackManager"]:
    """Read the current turn's FallbackManager. ``None`` = no live bridge."""
    return _ACTIVE_FALLBACK_MGR.get()
