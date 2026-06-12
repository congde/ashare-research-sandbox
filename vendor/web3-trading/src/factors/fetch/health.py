"""数据源健康状态 — 滑动窗口成功率跟踪。"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from enum import StrEnum


class HealthStatus(StrEnum):
    HEALTHY = "healthy"        # 成功率 >= 95%
    DEGRADED = "degraded"      # 成功率 50%-95%
    UNHEALTHY = "unhealthy"    # 成功率 < 50%


@dataclass
class DataSourceHealth:
    """单个数据源的健康状态快照。"""

    key: str
    status: HealthStatus
    success_rate: float
    total_samples: int
    last_success_at: float = 0.0
    last_failure_at: float = 0.0


class HealthTracker:
    """按数据源 key 跟踪最近 N 次调用的成功率。

    Usage::

        tracker = HealthTracker(window_size=20)
        tracker.record("whale_cost", success=True)
        health = tracker.get("whale_cost")
    """

    def __init__(self, window_size: int = 20) -> None:
        self._window = window_size
        self._records: dict[str, deque[bool]] = {}
        self._last_success: dict[str, float] = {}
        self._last_failure: dict[str, float] = {}

    def record(self, key: str, success: bool) -> None:
        """记录一次调用结果。"""
        if key not in self._records:
            self._records[key] = deque(maxlen=self._window)
        self._records[key].append(success)
        now = time.monotonic()
        if success:
            self._last_success[key] = now
        else:
            self._last_failure[key] = now

    def get(self, key: str) -> DataSourceHealth:
        """获取指定数据源的健康状态。"""
        records = self._records.get(key)
        if not records:
            return DataSourceHealth(
                key=key, status=HealthStatus.HEALTHY,
                success_rate=1.0, total_samples=0,
            )
        total = len(records)
        successes = sum(1 for r in records if r)
        rate = successes / total if total > 0 else 1.0
        if rate >= 0.95:
            status = HealthStatus.HEALTHY
        elif rate >= 0.50:
            status = HealthStatus.DEGRADED
        else:
            status = HealthStatus.UNHEALTHY
        return DataSourceHealth(
            key=key,
            status=status,
            success_rate=rate,
            total_samples=total,
            last_success_at=self._last_success.get(key, 0.0),
            last_failure_at=self._last_failure.get(key, 0.0),
        )

    def snapshot(self) -> dict[str, DataSourceHealth]:
        """返回所有已跟踪数据源的健康状态。"""
        return {k: self.get(k) for k in self._records}

    def all_healthy(self) -> bool:
        """所有已跟踪数据源是否都健康。"""
        return all(h.status == HealthStatus.HEALTHY for h in self.snapshot().values())
