# -*- coding: utf-8 -*-
"""
Circuit Breaker — Phase 2.1

Generic async-safe circuit breaker for external API calls.
Three states: CLOSED → OPEN → HALF_OPEN → CLOSED.

Usage:
    breaker = CircuitBreaker("dexscan", failure_threshold=5, recovery_timeout=60)

    async def call_api():
        async with breaker:
            return await dexscan_service.get_price(...)

    # Or use the decorator:
    @breaker.protect
    async def get_price(symbol):
        return await dexscan_service.get_price(symbol)
"""

from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, Optional, Type, Tuple

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    CLOSED = "closed"           # Normal operation
    OPEN = "open"               # Failing, reject requests
    HALF_OPEN = "half_open"     # Testing recovery


class CircuitOpenError(Exception):
    """Raised when circuit is open and call is rejected."""

    def __init__(self, name: str, retry_after: float):
        self.name = name
        self.retry_after = retry_after
        super().__init__(
            f"Circuit '{name}' is OPEN. Retry after {retry_after:.1f}s."
        )


class CircuitBreaker:
    """
    Async-safe circuit breaker.

    Args:
        name: Identifier for this breaker (e.g. "dexscan", "valuescan").
        failure_threshold: Number of consecutive failures to trip open.
        recovery_timeout: Seconds to wait before trying half-open.
        success_threshold: Consecutive successes in half-open to close.
        excluded_exceptions: Exception types that do NOT count as failures
            (e.g. ValueError for bad input).
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        success_threshold: int = 2,
        excluded_exceptions: Tuple[Type[Exception], ...] = (),
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        self.excluded_exceptions = excluded_exceptions

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0
        self._lock = asyncio.Lock()

        # Metrics
        self._total_calls = 0
        self._total_failures = 0
        self._total_rejected = 0
        self._total_successes = 0

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def metrics(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "total_calls": self._total_calls,
            "total_failures": self._total_failures,
            "total_rejected": self._total_rejected,
            "total_successes": self._total_successes,
        }

    async def _check_state(self) -> None:
        """Check if we should transition from OPEN to HALF_OPEN."""
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0
                logger.info(
                    "Circuit '%s' → HALF_OPEN after %.1fs recovery",
                    self.name, elapsed,
                )

    async def _on_success(self) -> None:
        """Handle a successful call."""
        self._total_successes += 1
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.success_threshold:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._success_count = 0
                logger.info("Circuit '%s' → CLOSED (recovered)", self.name)
        else:
            # In CLOSED state, reset failure count on success
            self._failure_count = 0

    async def _on_failure(self, exc: Exception) -> None:
        """Handle a failed call."""
        self._total_failures += 1
        self._failure_count += 1
        self._last_failure_time = time.monotonic()

        if self._state == CircuitState.HALF_OPEN:
            # Any failure in half-open → back to open
            self._state = CircuitState.OPEN
            logger.warning(
                "Circuit '%s' → OPEN (half-open test failed: %s)",
                self.name, exc,
            )
        elif self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                "Circuit '%s' → OPEN (threshold %d reached: %s)",
                self.name, self.failure_threshold, exc,
            )

    async def __aenter__(self):
        async with self._lock:
            await self._check_state()
            self._total_calls += 1

            if self._state == CircuitState.OPEN:
                self._total_rejected += 1
                retry_after = self.recovery_timeout - (
                    time.monotonic() - self._last_failure_time
                )
                raise CircuitOpenError(self.name, max(0, retry_after))

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            async with self._lock:
                await self._on_success()
        elif exc_type and not issubclass(exc_type, self.excluded_exceptions):
            async with self._lock:
                await self._on_failure(exc_val)
        # Don't suppress the exception
        return False

    def protect(self, func: Callable) -> Callable:
        """Decorator to protect an async function with this circuit breaker."""

        @wraps(func)
        async def wrapper(*args, **kwargs):
            async with self:
                return await func(*args, **kwargs)

        # Attach breaker reference for inspection
        wrapper.circuit_breaker = self  # type: ignore[attr-defined]
        return wrapper

    def reset(self) -> None:
        """Manually reset the circuit breaker to CLOSED state."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        logger.info("Circuit '%s' manually reset to CLOSED", self.name)


# ---------------------------------------------------------------------------
# Registry of circuit breakers for different services
# ---------------------------------------------------------------------------
_breakers: Dict[str, CircuitBreaker] = {}


def get_breaker(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: float = 60.0,
    **kwargs,
) -> CircuitBreaker:
    """Get or create a named circuit breaker."""
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(
            name=name,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            **kwargs,
        )
    return _breakers[name]


def get_all_breaker_metrics() -> Dict[str, Dict[str, Any]]:
    """Get metrics for all registered circuit breakers."""
    return {name: cb.metrics for name, cb in _breakers.items()}