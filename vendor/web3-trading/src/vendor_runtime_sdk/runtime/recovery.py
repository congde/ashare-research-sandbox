# -*- coding: utf-8 -*-
"""
RecoveryEngine — One-shot automatic recovery for tool execution failures.

Core principle (from claw-code V2):
  - Each RecoveryRecipe tries exactly ONE automatic recovery attempt
  - If recovery fails, immediately escalate to human
  - No infinite retries — prevents token waste and LLM rate-limit cascading

Recovery flow:
  Tool execution fails
      ↓
  RecoveryEngine.match(error) → best matching Recipe
      ↓
  Recipe.apply(context) → one attempt
      ↓
  Success → retry tool once
  Failure → escalate (alert + stop)

Built-in recipes:
  - NetworkTransientRecipe: Retry once on network timeout / connection error
  - StaleSessionRecipe: Re-init session on stale/rotated session errors
  - TrustPromptAutoResolveRecipe: Auto-resolve trust prompt failures
  - McpServerDownRecipe: Degrade to available tools when MCP server is down
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type

logger = logging.getLogger(__name__)


# ──────────────── Data Classes ────────────────


@dataclass
class RecoveryContext:
    """Recovery context — passed to each recipe"""

    error: Exception
    tool_name: str
    tool_input: Dict[str, Any]
    session_id: str
    lane_id: Optional[str] = None
    retry_count: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RecoveryResult:
    """Recovery attempt result"""

    success: bool
    action: str = ""  # "retry" | "degrade" | "reinit_session" | "skip"
    message: str = ""
    degraded_tools: Optional[List[str]] = None  # Available tools after degradation
    retry_input: Optional[Dict[str, Any]] = None  # Modified input for retry


# ──────────────── Recovery Recipe ABC ────────────────


class RecoveryRecipe(ABC):
    """Abstract recovery recipe — one shot, one attempt only."""

    # Priority: higher = tried first
    priority: int = 0

    @abstractmethod
    def can_handle(self, error: Exception, context: RecoveryContext) -> bool:
        """Check if this recipe can handle the given error."""
        ...

    @abstractmethod
    async def apply(self, context: RecoveryContext) -> RecoveryResult:
        """Apply recovery — exactly one attempt. Must not retry internally."""
        ...

    @property
    def name(self) -> str:
        return self.__class__.__name__


# ──────────────── Built-in Recipes ────────────────


class NetworkTransientRecipe(RecoveryRecipe):
    """Recover from transient network errors (timeout, connection reset)."""

    priority = 100

    # Known transient error markers
    _TRANSIENT_MARKERS = (
        "timeout",
        "timed out",
        "connection reset",
        "connection refused",
        "connection aborted",
        "broken pipe",
        "503",
        "502",
        "ECONNREFUSED",
        "ECONNRESET",
        "ETIMEDOUT",
    )

    def can_handle(self, error: Exception, context: RecoveryContext) -> bool:
        error_str = str(error).lower()
        error_type = type(error).__name__.lower()
        return any(
            m in error_str or m in error_type
            for m in self._TRANSIENT_MARKERS
        )

    async def apply(self, context: RecoveryContext) -> RecoveryResult:
        logger.info(
            "NetworkTransientRecipe: retrying %s after transient error: %s",
            context.tool_name, context.error,
        )
        return RecoveryResult(
            success=True,
            action="retry",
            message=f"Transient network error, retrying {context.tool_name} once",
            retry_input=context.tool_input,
        )


class StaleSessionRecipe(RecoveryRecipe):
    """Recover from stale/rotated session errors by re-initializing session."""

    priority = 80

    _STALE_MARKERS = (
        "session expired",
        "session not found",
        "session rotated",
        "stale session",
        "invalid session",
        "context_length_exceeded",
    )

    def can_handle(self, error: Exception, context: RecoveryContext) -> bool:
        error_str = str(error).lower()
        return any(m in error_str for m in self._STALE_MARKERS)

    async def apply(self, context: RecoveryContext) -> RecoveryResult:
        logger.info(
            "StaleSessionRecipe: reinitializing session %s after stale error",
            context.session_id,
        )
        return RecoveryResult(
            success=True,
            action="reinit_session",
            message="Session stale, triggering reinitialization",
        )


class TrustPromptAutoResolveRecipe(RecoveryRecipe):
    """Auto-resolve trust prompt failures by escalating to user."""

    priority = 50

    _TRUST_MARKERS = (
        "trust_prompt",
        "trust prompt",
        "permission denied",
        "unauthorized",
        "forbidden",
    )

    def can_handle(self, error: Exception, context: RecoveryContext) -> bool:
        error_str = str(error).lower()
        return any(m in error_str for m in self._TRUST_MARKERS)

    async def apply(self, context: RecoveryContext) -> RecoveryResult:
        logger.info(
            "TrustPromptAutoResolveRecipe: escalating trust issue for %s",
            context.tool_name,
        )
        return RecoveryResult(
            success=False,
            action="escalate",
            message="Trust/permission issue requires human intervention",
        )


class McpServerDownRecipe(RecoveryRecipe):
    """Degrade gracefully when MCP server is down — continue with available tools."""

    priority = 60

    _MCP_DOWN_MARKERS = (
        "mcp server",
        "tool not found",
        "server unavailable",
        "mcp connection",
        "mcp handshake",
    )

    def can_handle(self, error: Exception, context: RecoveryContext) -> bool:
        error_str = str(error).lower()
        return any(m in error_str for m in self._MCP_DOWN_MARKERS)

    async def apply(self, context: RecoveryContext) -> RecoveryResult:
        logger.info(
            "McpServerDownRecipe: degrading after MCP server error for %s",
            context.tool_name,
        )
        return RecoveryResult(
            success=True,
            action="degrade",
            message=f"MCP server down, skipping {context.tool_name}",
        )


class RateLimitRecipe(RecoveryRecipe):
    """Handle rate-limit errors by suggesting backoff or model degradation."""

    priority = 90

    _RATE_LIMIT_MARKERS = (
        "rate limit",
        "rate_limit",
        "too many requests",
        "429",
        "quota exceeded",
        "capacity",
    )

    def can_handle(self, error: Exception, context: RecoveryContext) -> bool:
        error_str = str(error).lower()
        return any(m in error_str for m in self._RATE_LIMIT_MARKERS)

    async def apply(self, context: RecoveryContext) -> RecoveryResult:
        logger.info(
            "RateLimitRecipe: rate limit hit for %s", context.tool_name,
        )
        return RecoveryResult(
            success=True,
            action="degrade",
            message="Rate limit detected, suggesting degradation to backup model",
        )


# ──────────────── Recovery Engine ────────────────


class RecoveryEngine:
    """
    Recovery engine — tries matching recipes in priority order.

    Guarantees:
    - Only ONE automatic recovery attempt per error
    - No infinite retry loops
    - Failed recovery immediately escalates

    Usage:
        engine = RecoveryEngine()
        engine.register(NetworkTransientRecipe())

        result = await engine.try_recover(
            error=some_exception,
            context=RecoveryContext(...)
        )
        if result.success:
            # Retry once
            ...
        else:
            # Escalate to human
            ...
    """

    def __init__(self, recipes: Optional[List[RecoveryRecipe]] = None):
        self._recipes: List[RecoveryRecipe] = sorted(
            recipes or self._default_recipes(),
            key=lambda r: -r.priority,
        )

    @staticmethod
    def _default_recipes() -> List[RecoveryRecipe]:
        """Built-in default recipes"""
        return [
            NetworkTransientRecipe(),
            StaleSessionRecipe(),
            RateLimitRecipe(),
            McpServerDownRecipe(),
            TrustPromptAutoResolveRecipe(),
        ]

    def register(self, recipe: RecoveryRecipe) -> None:
        """Register a new recipe (inserted by priority)"""
        self._recipes.append(recipe)
        self._recipes.sort(key=lambda r: -r.priority)

    def remove(self, recipe_class: Type[RecoveryRecipe]) -> None:
        """Remove all recipes of a given class"""
        self._recipes = [r for r in self._recipes if not isinstance(r, recipe_class)]

    async def try_recover(
        self,
        error: Exception,
        context: Optional[RecoveryContext] = None,
    ) -> Optional[RecoveryResult]:
        """
        Try to recover from an error.

        Returns:
            RecoveryResult if a matching recipe was found, None otherwise.
            result.success=True → retry once
            result.success=False → escalate to human
        """
        if context is None:
            context = RecoveryContext(
                error=error,
                tool_name="unknown",
                tool_input={},
                session_id="unknown",
            )

        for recipe in self._recipes:
            try:
                if recipe.can_handle(error, context):
                    logger.info(
                        "RecoveryEngine: matching recipe %s for error: %s",
                        recipe.name, error,
                    )
                    result = await recipe.apply(context)
                    result.message = f"[{recipe.name}] {result.message}"
                    return result
            except Exception as recipe_error:
                logger.warning(
                    "RecoveryEngine: recipe %s raised error: %s",
                    recipe.name, recipe_error,
                )
                continue

        # No matching recipe
        logger.info("RecoveryEngine: no matching recipe for error: %s", error)
        return None

    def get_all_recipes(self) -> List[RecoveryRecipe]:
        """Return all registered recipes"""
        return list(self._recipes)
