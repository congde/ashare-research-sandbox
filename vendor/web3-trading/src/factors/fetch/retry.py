"""指数退避重试 — 仅重试可恢复错误，不可恢复错误直接抛出。"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

# 默认可重试的异常类型
_RETRYABLE = (
    asyncio.TimeoutError,
    ConnectionError,
    TimeoutError,
    OSError,
)


@dataclass(frozen=True)
class RetryConfig:
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 10.0
    retryable_exceptions: tuple[type[BaseException], ...] = _RETRYABLE


async def with_retry(
    coro_factory: Callable[[], Coroutine[Any, Any, Any]],
    config: RetryConfig | None = None,
    label: str = "",
) -> Any:
    """以指数退避重试执行协程。

    Args:
        coro_factory: 每次调用返回新协程的工厂函数（协程不可重用）。
        config: 重试配置，为 None 时使用默认值。
        label: 调用方的标签，用于日志。

    Returns:
        协程的返回值。

    Raises:
        最后一次尝试的异常（重试耗尽时）。
    """
    cfg = config or RetryConfig()
    last_exc: BaseException | None = None

    for attempt in range(cfg.max_retries + 1):
        try:
            return await coro_factory()
        except cfg.retryable_exceptions as exc:
            last_exc = exc
            if attempt == cfg.max_retries:
                raise
            delay = min(cfg.base_delay * (2 ** attempt), cfg.max_delay)
            delay *= 0.5 + random.random()
            tag = f" [{label}]" if label else ""
            logger.warning(
                "Retry %d/%d%s after %.1fs: %s",
                attempt + 1, cfg.max_retries, tag, delay, exc,
            )
            await asyncio.sleep(delay)

    raise last_exc  # type: ignore[misc]
