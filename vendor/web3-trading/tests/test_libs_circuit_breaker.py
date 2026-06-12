# -*- coding: utf-8 -*-
"""
Tests for src/libs/circuit_breaker.py
"""

import sys
import os
import asyncio
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from libs.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    CircuitOpenError,
    get_breaker,
    get_all_breaker_metrics,
    _breakers,
)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def clear_registry():
    """Clear global breaker registry between tests."""
    _breakers.clear()
    yield
    _breakers.clear()


class TestCircuitBreakerStates:
    def test_initial_state_is_closed(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        assert cb.state == CircuitState.CLOSED

    def test_stays_closed_on_success(self):
        cb = CircuitBreaker("test", failure_threshold=3)

        async def _test():
            async with cb:
                pass  # success
            assert cb.state == CircuitState.CLOSED

        run(_test())

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=60)

        async def _test():
            for _ in range(3):
                try:
                    async with cb:
                        raise ConnectionError("fail")
                except ConnectionError:
                    pass
            assert cb.state == CircuitState.OPEN

        run(_test())

    def test_rejects_when_open(self):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=60)

        async def _test():
            # Trip the breaker
            for _ in range(2):
                try:
                    async with cb:
                        raise ConnectionError("fail")
                except ConnectionError:
                    pass

            assert cb.state == CircuitState.OPEN

            # Next call should be rejected
            with pytest.raises(CircuitOpenError) as exc_info:
                async with cb:
                    pass
            assert "OPEN" in str(exc_info.value)

        run(_test())

    def test_half_open_after_recovery_timeout(self):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=0.1)

        async def _test():
            # Trip the breaker
            for _ in range(2):
                try:
                    async with cb:
                        raise ConnectionError("fail")
                except ConnectionError:
                    pass

            assert cb.state == CircuitState.OPEN

            # Wait for recovery
            await asyncio.sleep(0.15)

            # Next call should be allowed (half-open)
            async with cb:
                pass  # success

            assert cb.state in (CircuitState.HALF_OPEN, CircuitState.CLOSED)

        run(_test())

    def test_closes_after_success_threshold_in_half_open(self):
        cb = CircuitBreaker(
            "test", failure_threshold=2, recovery_timeout=0.05,
            success_threshold=2,
        )

        async def _test():
            # Trip
            for _ in range(2):
                try:
                    async with cb:
                        raise ConnectionError("fail")
                except ConnectionError:
                    pass

            await asyncio.sleep(0.1)

            # Two successes should close
            async with cb:
                pass
            async with cb:
                pass

            assert cb.state == CircuitState.CLOSED

        run(_test())

    def test_half_open_failure_reopens(self):
        cb = CircuitBreaker(
            "test", failure_threshold=2, recovery_timeout=0.05,
        )

        async def _test():
            # Trip
            for _ in range(2):
                try:
                    async with cb:
                        raise ConnectionError("fail")
                except ConnectionError:
                    pass

            await asyncio.sleep(0.1)

            # Fail in half-open → back to open
            try:
                async with cb:
                    raise ConnectionError("fail again")
            except ConnectionError:
                pass

            assert cb.state == CircuitState.OPEN

        run(_test())


class TestCircuitBreakerExclusions:
    def test_excluded_exceptions_dont_count(self):
        cb = CircuitBreaker(
            "test", failure_threshold=2,
            excluded_exceptions=(ValueError,),
        )

        async def _test():
            for _ in range(5):
                try:
                    async with cb:
                        raise ValueError("bad input")
                except ValueError:
                    pass

            # Should still be closed — ValueError is excluded
            assert cb.state == CircuitState.CLOSED

        run(_test())

    def test_non_excluded_exceptions_count(self):
        cb = CircuitBreaker(
            "test", failure_threshold=2,
            excluded_exceptions=(ValueError,),
        )

        async def _test():
            for _ in range(2):
                try:
                    async with cb:
                        raise ConnectionError("real failure")
                except ConnectionError:
                    pass

            assert cb.state == CircuitState.OPEN

        run(_test())


class TestCircuitBreakerMetrics:
    def test_metrics_tracking(self):
        cb = CircuitBreaker("metrics-test", failure_threshold=3)

        async def _test():
            # 2 successes
            for _ in range(2):
                async with cb:
                    pass

            # 1 failure
            try:
                async with cb:
                    raise ConnectionError("fail")
            except ConnectionError:
                pass

            m = cb.metrics
            assert m["total_calls"] == 3
            assert m["total_successes"] == 2
            assert m["total_failures"] == 1
            assert m["total_rejected"] == 0
            assert m["state"] == "closed"

        run(_test())

    def test_rejected_count(self):
        cb = CircuitBreaker("reject-test", failure_threshold=1, recovery_timeout=60)

        async def _test():
            try:
                async with cb:
                    raise ConnectionError("fail")
            except ConnectionError:
                pass

            # Now open, try 3 more calls
            for _ in range(3):
                try:
                    async with cb:
                        pass
                except CircuitOpenError:
                    pass

            assert cb.metrics["total_rejected"] == 3

        run(_test())


class TestCircuitBreakerDecorator:
    def test_protect_decorator(self):
        cb = CircuitBreaker("decorator-test", failure_threshold=3)

        @cb.protect
        async def my_func(x):
            return x * 2

        async def _test():
            result = await my_func(5)
            assert result == 10
            assert cb.state == CircuitState.CLOSED

        run(_test())

    def test_protect_decorator_counts_failures(self):
        cb = CircuitBreaker("decorator-fail", failure_threshold=2)

        @cb.protect
        async def failing_func():
            raise ConnectionError("boom")

        async def _test():
            for _ in range(2):
                try:
                    await failing_func()
                except ConnectionError:
                    pass
            assert cb.state == CircuitState.OPEN

        run(_test())


class TestCircuitBreakerReset:
    def test_manual_reset(self):
        cb = CircuitBreaker("reset-test", failure_threshold=1, recovery_timeout=60)

        async def _test():
            try:
                async with cb:
                    raise ConnectionError("fail")
            except ConnectionError:
                pass

            assert cb.state == CircuitState.OPEN
            cb.reset()
            assert cb.state == CircuitState.CLOSED

        run(_test())


class TestCircuitBreakerRegistry:
    def test_get_breaker_creates_new(self):
        b = get_breaker("service-a")
        assert isinstance(b, CircuitBreaker)
        assert b.name == "service-a"

    def test_get_breaker_returns_existing(self):
        b1 = get_breaker("service-b")
        b2 = get_breaker("service-b")
        assert b1 is b2

    def test_all_metrics(self):
        get_breaker("svc-1")
        get_breaker("svc-2")
        metrics = get_all_breaker_metrics()
        assert "svc-1" in metrics
        assert "svc-2" in metrics


if __name__ == "__main__":
    pytest.main([__file__, "-v"])