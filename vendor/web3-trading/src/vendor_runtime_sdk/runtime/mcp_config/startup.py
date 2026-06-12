# -*- coding: utf-8 -*-
"""Sprint 7 PR-5 · Startup helper for daemon / web app.

Wraps the standard "load toml → construct manager → start_all" sequence
in one async function that callers can invoke from their boot path.

Usage from daemon:
    from vendor_runtime_sdk.runtime.mcp_config.startup import bootstrap_external_mcp_or_none

    manager = await bootstrap_external_mcp_or_none()
    if manager is not None:
        # stash in app context; pass to tool_registry.build_registry()
        app_state.mcp_manager = manager
        ...
    # at shutdown:
    if manager is not None:
        await manager.stop_all()

The helper is toggle-gated: returns None when
``coder_mcp_external_servers`` is OFF, so callers can stay agnostic
about the toggle state.

Per docs/Sprint7-MCP-工具扩展技术方案.md §5.6.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from vendor_runtime_sdk.runtime.mcp_config.loader import load_mcp_servers
from vendor_runtime_sdk.runtime.mcp_config.manager import McpServerManager
from vendor_runtime_sdk.runtime.mcp_config.schema import SchemaValidationError

logger = logging.getLogger(__name__)


def _toggle_enabled() -> bool:
    try:
        from vendor_runtime_sdk.runtime.config.toggles import get_toggles
        return bool(get_toggles().is_enabled("coder_mcp_external_servers"))
    except Exception:  # pragma: no cover — fail-closed
        return False


async def bootstrap_external_mcp_or_none(
    *,
    config_path: Optional[Path] = None,
    workspace_root: Optional[str] = None,
) -> Optional[McpServerManager]:
    """Construct + start an :class:`McpServerManager` from the toml.

    Returns:
      * ``None`` when the toggle is OFF (deliberate skip) OR when
        the toml is absent (default healthy state).
      * Configured + started :class:`McpServerManager` otherwise.

    On schema validation error the helper logs an error and returns
    ``None`` — daemon must continue to start even with a broken MCP
    config; the operator sees the error in the daemon log + can fix
    the toml + restart.

    Single-server start failures don't propagate (manager handles
    isolation internally — see PR-2 ``start_all`` design).
    """
    if not _toggle_enabled():
        logger.debug("coder_mcp_external_servers toggle OFF — skipping")
        return None

    try:
        specs = load_mcp_servers(config_path)
    except SchemaValidationError as exc:
        logger.error(
            "external MCP config invalid (%s) — daemon will boot without "
            "external MCP servers; fix the toml + restart to enable",
            exc,
        )
        return None

    # Sprint S-EK-V1 PR 6 fix — even with NO operator toml and NO global
    # specs, we still need a manager when ``expert_kit_auto_install`` is
    # ON because per-user expert-kit specs live in Mongo
    # (``user_mcp_servers``) and are loaded on demand via
    # ``McpServerManager.reload_for_user(workspace_id, user_id)``. Without
    # a constructed manager, ``get_external_mcp_manager()`` returns None
    # and the Gateway's per-request per-user MCP tool registration block
    # short-circuits → kit tools never reach the LLM. Construct an empty
    # manager so per-user code can populate it.
    def _expert_kit_toggle_on() -> bool:
        try:
            from vendor_runtime_sdk.runtime.config.toggles import get_toggles
            return bool(get_toggles().is_enabled("expert_kit_auto_install"))
        except Exception:  # pragma: no cover
            return False

    if not specs:
        if _expert_kit_toggle_on():
            logger.info(
                "external MCP bootstrap: no operator toml specs, but "
                "expert_kit_auto_install is ON — constructing empty manager "
                "for per-user kit loading"
            )
            return McpServerManager(specs=[], workspace_root=workspace_root)
        logger.debug("no external MCP servers configured")
        return None

    manager = McpServerManager(specs=specs, workspace_root=workspace_root)
    statuses = await manager.start_all()
    ready = sum(1 for s in statuses.values() if s.status == "ready")
    failed = sum(1 for s in statuses.values() if s.status == "failed")
    logger.info(
        "external MCP bootstrap: ready=%d failed=%d total=%d",
        ready, failed, len(statuses),
    )
    return manager


# Singleton accessor — Sprint S-EK-V1 PR 2.
#
# The daemon / web app stashes the manager on ``app.state.mcp_manager``
# after bootstrap. Modules that need to reach it from outside the
# request lifecycle (e.g. ``agent.persona.kit_installer.install_kit``
# triggering ``reload_for_user``) can't pull from ``request.app`` —
# they need a process-wide accessor.
#
# This module-level slot is set by the app on boot. Get returns None
# when (a) toggle is OFF, (b) toml is absent, or (c) app hasn't booted
# yet (e.g. unit tests). All callers MUST treat None as "feature off"
# and degrade silently — never raise.
_external_mcp_manager: Optional[McpServerManager] = None


def set_external_mcp_manager(manager: Optional[McpServerManager]) -> None:
    """Called by the app after bootstrap_external_mcp_or_none returns
    so other modules can reach the manager."""
    global _external_mcp_manager
    _external_mcp_manager = manager


def get_external_mcp_manager() -> Optional[McpServerManager]:
    """Process-wide accessor for the bootstrapped MCP manager.

    Returns None when feature is disabled / not yet booted. Callers
    must treat None as "feature off"; never raise on None.
    """
    return _external_mcp_manager


__all__ = [
    "bootstrap_external_mcp_or_none",
    "get_external_mcp_manager",
    "set_external_mcp_manager",
]
