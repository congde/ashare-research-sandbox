"""数据获取容错机制 — 重试、熔断、降级、健康状态。"""

from .circuit_breaker import CircuitBreaker, CircuitState
from .fallback import FallbackRegistry, kline_fallback
from .health import DataSourceHealth, HealthStatus
from .retry import RetryConfig, with_retry

__all__ = [
    "CircuitBreaker",
    "CircuitState",
    "DataSourceHealth",
    "FallbackRegistry",
    "HealthStatus",
    "RetryConfig",
    "kline_fallback",
    "with_retry",
]
