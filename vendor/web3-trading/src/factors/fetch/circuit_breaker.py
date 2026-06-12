"""熔断器 — 按数据源独立熔断，避免级联故障。"""

from __future__ import annotations

import logging
import time
from enum import StrEnum
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


class CircuitState(StrEnum):
    CLOSED = "closed"          # 正常调用
    OPEN = "open"              # 熔断中，直接拒绝
    HALF_OPEN = "half_open"    # 允许一次探测调用


class CircuitBreaker:
    """按数据源 key 独立熔断。

    状态转移::

        CLOSED ──连续失败 N 次──▶ OPEN
        OPEN   ──超时后─────────▶ HALF_OPEN
        HALF_OPEN ──成功────────▶ CLOSED
        HALF_OPEN ──失败────────▶ OPEN

    Usage::

        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=300)
        result = await cb.call(lambda: api.fetch(), key="whale_cost")
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 300.0,
    ) -> None:
        self._threshold = failure_threshold
        self._recovery = recovery_timeout
        self._states: dict[str, CircuitState] = {}
        self._failures: dict[str, int] = {}
        self._opened_at: dict[str, float] = {}

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    async def call(
        self,
        coro_factory: Callable[[], Coroutine[Any, Any, Any]],
        *,
        key: str,
    ) -> Any:
        """在熔断器保护下执行调用。"""
        state = self._current_state(key)
        if state == CircuitState.OPEN:
            logger.warning("Circuit OPEN for %s — rejecting call.", key)
            raise CircuitOpenError(key)
        try:
            result = await coro_factory()
        except Exception:
            self._on_failure(key)
            raise
        self._on_success(key)
        return result

    @property
    def states(self) -> dict[str, CircuitState]:
        """返回所有数据源的当前状态快照。"""
        return {k: self._current_state(k) for k in self._states}

    def reset(self, key: str) -> None:
        """手动重置指定数据源的熔断器。"""
        self._states.pop(key, None)
        self._failures.pop(key, None)
        self._opened_at.pop(key, None)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _current_state(self, key: str) -> CircuitState:
        state = self._states.get(key, CircuitState.CLOSED)
        if state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._opened_at.get(key, 0.0)
            if elapsed >= self._recovery:
                self._states[key] = CircuitState.HALF_OPEN
                logger.info("Circuit HALF_OPEN for %s — allowing probe.", key)
                return CircuitState.HALF_OPEN
        return self._states.get(key, CircuitState.CLOSED)

    def _on_failure(self, key: str) -> None:
        current = self._current_state(key)
        if current == CircuitState.HALF_OPEN:
            self._states[key] = CircuitState.OPEN
            self._opened_at[key] = time.monotonic()
            self._failures[key] = self._threshold
            logger.warning("Circuit OPEN for %s — probe failed.", key)
            return
        count = self._failures.get(key, 0) + 1
        self._failures[key] = count
        if count >= self._threshold:
            self._states[key] = CircuitState.OPEN
            self._opened_at[key] = time.monotonic()
            logger.warning("Circuit OPEN for %s after %d failures.", key, count)

    def _on_success(self, key: str) -> None:
        self._states[key] = CircuitState.CLOSED
        self._failures[key] = 0
        self._opened_at.pop(key, None)


class CircuitOpenError(Exception):
    """熔断器打开时抛出的异常。"""

    def __init__(self, key: str) -> None:
        super().__init__(f"Circuit breaker is OPEN for '{key}'")
        self.key = key
