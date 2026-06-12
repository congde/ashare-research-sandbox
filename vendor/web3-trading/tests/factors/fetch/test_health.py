# -*- coding: utf-8 -*-
"""测试数据源健康追踪。"""

from factors.fetch.health import HealthStatus, HealthTracker


class TestHealthTracker:
    def test_initial_unknown_key(self) -> None:
        tracker = HealthTracker(window_size=10)
        health = tracker.get("unknown")
        assert health.status == HealthStatus.HEALTHY
        assert health.success_rate == 1.0
        assert health.total_samples == 0

    def test_all_success(self) -> None:
        tracker = HealthTracker(window_size=10)
        for _ in range(10):
            tracker.record("api", success=True)
        health = tracker.get("api")
        assert health.status == HealthStatus.HEALTHY
        assert health.success_rate == 1.0
        assert health.total_samples == 10

    def test_degraded(self) -> None:
        tracker = HealthTracker(window_size=10)
        for _ in range(7):
            tracker.record("api", success=True)
        for _ in range(3):
            tracker.record("api", success=False)
        health = tracker.get("api")
        assert health.status == HealthStatus.DEGRADED
        assert 0.69 < health.success_rate < 0.71

    def test_unhealthy(self) -> None:
        tracker = HealthTracker(window_size=10)
        for _ in range(4):
            tracker.record("api", success=True)
        for _ in range(6):
            tracker.record("api", success=False)
        health = tracker.get("api")
        assert health.status == HealthStatus.UNHEALTHY

    def test_sliding_window(self) -> None:
        tracker = HealthTracker(window_size=5)
        for _ in range(5):
            tracker.record("api", success=False)
        for _ in range(5):
            tracker.record("api", success=True)
        health = tracker.get("api")
        assert health.success_rate == 1.0
        assert health.total_samples == 5

    def test_snapshot(self) -> None:
        tracker = HealthTracker(window_size=10)
        tracker.record("a", success=True)
        tracker.record("b", success=False)
        snap = tracker.snapshot()
        assert "a" in snap
        assert "b" in snap
        assert snap["a"].status == HealthStatus.HEALTHY

    def test_all_healthy(self) -> None:
        tracker = HealthTracker(window_size=10)
        tracker.record("a", success=True)
        tracker.record("b", success=True)
        assert tracker.all_healthy()

    def test_all_healthy_false_when_degraded(self) -> None:
        tracker = HealthTracker(window_size=10)
        for _ in range(8):
            tracker.record("a", success=True)
        for _ in range(2):
            tracker.record("a", success=False)
        assert not tracker.all_healthy()

    def test_boundary_95_percent(self) -> None:
        tracker = HealthTracker(window_size=20)
        for _ in range(19):
            tracker.record("api", success=True)
        tracker.record("api", success=False)
        health = tracker.get("api")
        assert health.success_rate == 0.95
        assert health.status == HealthStatus.HEALTHY
