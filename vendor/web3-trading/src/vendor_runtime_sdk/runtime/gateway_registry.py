# -*- coding: utf-8 -*-
"""
runtime.gateway_registry — Process-level Gateway singleton accessor
(PR-E*c of the Agent Engine SDK extraction plan).

See ``docs/Agent-Engine-SDK-剥离方案.md`` §5 PR-E*c.

Why this module
---------------
``Gateway`` is the single entry point that wires the live skill
registry, persona registry, runtime hooks, and LLM router together
before dispatching a request to an agent.  Two engine code paths
need to reach the same Gateway instance the live HTTP request uses:

* ``src/agent/schedule/agent_task_dispatcher.py`` — background
  scheduler dispatch.
* ``src/runtime/conversation/_resume.py`` — HITL auto-resume.
* ``src/agent/schedule/service.py`` — Coder-task scheduled dispatch.

Pre-PR-E*c those call sites either:

(a) imported ``_get_gateway`` from ``web.api.chat.chat`` (a
    ``web.api.*`` module — banned by the engine import boundary)
(b) read ``app.state.gateway`` via ``from web.application import app``
    (a ``web.application`` import — also banned)

Both routes drag the FastAPI/web layer onto the SDK import surface.

PR-E*c introduces a tiny process-level registry: ``set_gateway`` /
``get_gateway`` / ``reset_gateway_for_test``.  The web layer registers
the live Gateway after constructing it; engine call sites read from
the registry instead of dragging ``web.api.*`` onto their imports.

Phase 2 (post-extraction)
-------------------------
The registry stays — it's the canonical accessor for SDK consumers
that need to share a Gateway between scheduler + HTTP + CLI surfaces.
The legacy fallback for backward compat (``web.api.chat.chat._get_gateway``)
is removed at the same time the ``web/`` import surface is dropped
from the engine.

Failure semantics
-----------------
``get_gateway()`` returns ``None`` when nothing is installed — engine
callers MUST treat this as "no Gateway available" and degrade
gracefully (log + skip), matching the legacy ``_resolve_gateway`` shape
in ``agent.schedule.service``. **Never raise** — the scheduler tick
must keep looping.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


_gateway: Optional[Any] = None


def set_gateway(gateway: Any) -> None:
    """Install the process-level Gateway singleton.

    Idempotent — subsequent calls overwrite.  The web layer
    (``web.api.chat.chat._get_gateway``) calls this after building the
    lazy singleton so the engine-side accessor returns the SAME
    instance the live HTTP request uses.

    Logs at INFO so boot order is auditable.  **Never** logs the
    Gateway contents — it holds skill registry refs and may carry
    operator credentials downstream.

    Args:
        gateway: A ``Gateway`` instance.  No structural check is
            performed (Gateway has a large surface area; relying on a
            Protocol here would add churn without value — the call
            sites all use ``await gateway.dispatch(...)`` and a missing
            method would surface immediately).
    """
    global _gateway
    _gateway = gateway
    logger.info("Gateway installed: %s", type(gateway).__name__)


def get_gateway() -> Optional[Any]:
    """Return the installed Gateway, or ``None`` when nothing is set.

    Engine callers MUST treat ``None`` as a fail-soft signal
    (typical pattern: log a warning + skip the dispatch).  This
    mirrors the legacy ``app.state.gateway`` resolution shape that
    returns ``None`` when no HTTP layer is present.
    """
    return _gateway


def reset_gateway_for_test() -> None:
    """Test-only helper to clear the installed Gateway between cases.

    NOT for production use.
    """
    global _gateway
    _gateway = None


__all__ = [
    "set_gateway",
    "get_gateway",
    "reset_gateway_for_test",
]
