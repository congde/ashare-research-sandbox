"""降级策略 — 主数据源不可用时切换到备用数据源。"""

from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

# 降级策略类型：接收数据源 key，返回备用 coro 工厂或 None
FallbackFn = Callable[[str], Coroutine[Any, Any, Any] | None]


class FallbackRegistry:
    """按数据源 key 注册降级策略。

    Usage::

        registry = FallbackRegistry()
        registry.register("kline", kline_fallback)
        result = await registry.try_with_fallback("kline", primary_coro_factory)
    """

    def __init__(self) -> None:
        self._fallbacks: dict[str, FallbackFn] = {}

    def register(self, key: str, fn: FallbackFn) -> None:
        self._fallbacks[key] = fn

    async def try_with_fallback(
        self,
        key: str,
        primary: Callable[[], Coroutine[Any, Any, Any]],
    ) -> Any:
        """先尝试主数据源，失败后尝试降级。"""
        try:
            return await primary()
        except Exception:
            fallback_fn = self._fallbacks.get(key)
            if fallback_fn is None:
                raise
            logger.info("Primary %s failed, attempting fallback.", key)
            fallback_coro = await fallback_fn(key)
            if fallback_coro is None:
                raise
            return await fallback_coro


async def kline_fallback(_key: str) -> None:
    """KuCoin K-line 不可用时的占位降级。

    实际降级逻辑需要在管线上下文中执行（需要访问 ValueScan price_indicators），
    因此此函数在注册表中作为标记，实际降级由 pipeline._fetch_context 处理。
    """
    return None
