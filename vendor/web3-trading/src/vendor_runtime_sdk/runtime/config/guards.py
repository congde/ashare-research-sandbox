# -*- coding: utf-8 -*-
"""
Module Guards — centralized toggle checks for Phase 2–4 modules (M4 review fix)

Provides a thin wrapper that modules can call at their entry points to
check if they are enabled.  Uses the global ModuleToggles instance.

Design: modules remain importable regardless of toggle state; the guard
only prevents *execution* when disabled.  This avoids import-time side
effects and keeps tests simple.

Usage::

    from vendor_runtime_sdk.runtime.config.guards import require_module

    async def spawn_and_wait(self, ...):
        require_module("typed_subagent")  # raises ModuleDisabledError if off
        ...

    # Or as a soft check:
    from vendor_runtime_sdk.runtime.config.guards import is_module_enabled
    if is_module_enabled("coordinator"):
        coord = CoordinatorAgent(...)
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Global toggles instance — set by application startup
_toggles: Optional[object] = None


class ModuleDisabledError(RuntimeError):
    """Raised when a disabled module is invoked."""

    def __init__(self, module: str) -> None:
        super().__init__(
            f"Module '{module}' is disabled via ModuleToggles. "
            f"Enable it with RUNTIME__MODULES__{module.upper()}__ENABLED=true"
        )
        self.module = module


def init_guards(toggles: object) -> None:
    """Initialize the global toggles reference. Called once at startup."""
    global _toggles
    _toggles = toggles
    logger.debug("Module guards initialized")


def is_module_enabled(module: str) -> bool:
    """
    Check if a module is enabled.

    Returns True if toggles are not initialized (fail-open for tests).
    """
    if _toggles is None:
        return True  # no toggles → all enabled (test / dev mode)
    return _toggles.is_enabled(module)


def require_module(module: str) -> None:
    """
    Assert that a module is enabled; raise ModuleDisabledError if not.

    No-ops if toggles are not initialized (test / dev mode).
    """
    if _toggles is not None and not _toggles.is_enabled(module):
        raise ModuleDisabledError(module)
