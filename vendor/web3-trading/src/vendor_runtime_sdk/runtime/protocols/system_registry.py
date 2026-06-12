# -*- coding: utf-8 -*-
"""
runtime.protocols.system_registry — Pluggable Protocols for the
MCP lifecycle manager and namespace registry singletons
(PR-E*c of the Agent Engine SDK extraction plan).

See ``docs/Agent-Engine-SDK-剥离方案.md`` §5 PR-E*c.

Why this module
---------------
``Gateway.get_degraded_report`` (``src/agent/plan/gateway.py``) needs
to read the live MCP lifecycle + namespace state so it can return a
combined degraded-status payload to admin dashboards. Pre-PR-E*c the
code reached for them via::

    from web.api.admin import _get_lifecycle_manager, _get_namespace_registry

That import drags ``web.api.*`` onto the SDK import surface for what
is conceptually a pure runtime lookup of two engine-level managers
(``mcp.lifecycle.McpLifecycleManager`` + ``mcp.namespace.NamespaceRegistry``).

PR-E*c introduces a tiny registry abstraction:

* :class:`LifecycleManager` — Protocol matching the verb the engine
  uses (``get_degraded_report`` returning a structure with ``to_dict``).
* :class:`NamespaceRegistry` — Protocol matching the verb the engine
  uses (``get_degraded_report`` returning a dict / list of dicts).

The web/admin layer installs the live singletons via
:func:`set_lifecycle_manager` / :func:`set_namespace_registry` during
boot (or lazily on first access — the legacy admin singleton getter
already publishes via this seam). Engine call sites read via
:func:`get_lifecycle_manager` / :func:`get_namespace_registry`.

Failure semantics
-----------------
Getters return ``None`` when nothing is installed. The engine call
site (``Gateway.get_degraded_report``) MUST treat that as "no MCP
manager wired" and return ``None`` to its caller — never raise. This
mirrors the legacy behaviour where the ``web.api.admin`` lookup was
already wrapped in a try/except returning ``None`` on any failure.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class LifecycleManager(Protocol):
    """Protocol for the MCP lifecycle manager singleton.

    The only engine-side verb is ``get_degraded_report`` returning an
    object with a ``to_dict`` method (the production implementation
    is ``mcp.lifecycle.McpLifecycleManager``). Implementations MAY
    expose additional admin verbs; the engine never calls them.
    """

    def get_degraded_report(self) -> Any:
        """Return a degraded-status report object exposing ``to_dict``."""
        ...


@runtime_checkable
class NamespaceRegistry(Protocol):
    """Protocol for the MCP namespace registry singleton.

    The only engine-side verb is ``get_degraded_report`` returning a
    dict / list of dicts that summarises namespace health. The
    production implementation is ``mcp.namespace.NamespaceRegistry``.
    """

    def get_degraded_report(self) -> Any:
        """Return a degraded-status payload (JSON-serialisable)."""
        ...


# ── Module-level singletons ─────────────────────────────────────────────


_lifecycle_manager: Optional[LifecycleManager] = None
_namespace_registry: Optional[NamespaceRegistry] = None


def set_lifecycle_manager(mgr: LifecycleManager) -> None:
    """Install the LifecycleManager used by engine modules.

    Idempotent — subsequent calls overwrite. Logs at INFO so boot
    order is auditable. **Never** logs the manager contents.

    Raises:
        TypeError: when ``mgr`` does not satisfy the
            :class:`LifecycleManager` Protocol.
    """
    if not isinstance(mgr, LifecycleManager):
        raise TypeError(
            "set_lifecycle_manager: mgr must satisfy LifecycleManager "
            f"Protocol (get_degraded_report), got {type(mgr).__name__}"
        )
    global _lifecycle_manager
    _lifecycle_manager = mgr
    logger.info("LifecycleManager installed: %s", type(mgr).__name__)


def set_namespace_registry(reg: NamespaceRegistry) -> None:
    """Install the NamespaceRegistry used by engine modules.

    Idempotent — subsequent calls overwrite. Logs at INFO so boot
    order is auditable.

    Raises:
        TypeError: when ``reg`` does not satisfy the
            :class:`NamespaceRegistry` Protocol.
    """
    if not isinstance(reg, NamespaceRegistry):
        raise TypeError(
            "set_namespace_registry: reg must satisfy NamespaceRegistry "
            f"Protocol (get_degraded_report), got {type(reg).__name__}"
        )
    global _namespace_registry
    _namespace_registry = reg
    logger.info("NamespaceRegistry installed: %s", type(reg).__name__)


def get_lifecycle_manager() -> Optional[LifecycleManager]:
    """Return the installed LifecycleManager, or ``None`` when nothing
    is set.

    Engine callers MUST treat ``None`` as a fail-soft signal (e.g.
    ``Gateway.get_degraded_report`` returns ``None`` to its caller
    when the registry is empty). Never raises.
    """
    return _lifecycle_manager


def get_namespace_registry() -> Optional[NamespaceRegistry]:
    """Return the installed NamespaceRegistry, or ``None`` when
    nothing is set. Engine callers MUST fail-soft on ``None``.
    """
    return _namespace_registry


def reset_system_registry_for_test() -> None:
    """Test-only helper to clear both registries between cases.

    NOT for production use.
    """
    global _lifecycle_manager, _namespace_registry
    _lifecycle_manager = None
    _namespace_registry = None


# ── In-memory NoOp implementations for tests + SDK default ──────────────


class NoOpLifecycleManager:
    """A do-nothing :class:`LifecycleManager` for tests / SDK default.

    ``get_degraded_report`` returns an object whose ``to_dict()``
    yields an empty mapping — matches the production shape without
    requiring an actual ``mcp.lifecycle`` import.
    """

    class _EmptyReport:
        def to_dict(self) -> dict[str, Any]:
            return {}

    def get_degraded_report(self) -> "_EmptyReport":  # type: ignore[name-defined]
        return self._EmptyReport()


class NoOpNamespaceRegistry:
    """A do-nothing :class:`NamespaceRegistry` for tests / SDK default."""

    def get_degraded_report(self) -> dict[str, Any]:
        return {}


__all__ = [
    "LifecycleManager",
    "NamespaceRegistry",
    "NoOpLifecycleManager",
    "NoOpNamespaceRegistry",
    "set_lifecycle_manager",
    "set_namespace_registry",
    "get_lifecycle_manager",
    "get_namespace_registry",
    "reset_system_registry_for_test",
]
