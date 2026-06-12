# -*- coding: utf-8 -*-
"""测试熔断器。"""

import pytest

from factors.fetch.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState


class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_normal_call(self) -> None:
        cb = CircuitBreaker(failure_threshold=2)
        result = await cb.call(lambda: _ok(), key="test")
        assert result == 42
        assert cb.states["test"] == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_opens_after_threshold(self) -> None:
        cb = CircuitBreaker(failure_threshold=2)
        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(lambda: _fail(), key="api")

        with pytest.raises(CircuitOpenError):
            await cb.call(lambda: _ok(), key="api")

        assert cb.states["api"] == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_isolated_per_key(self) -> None:
        cb = CircuitBreaker(failure_threshold=2)
        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(lambda: _fail(), key="api_a")

        result = await cb.call(lambda: _ok(), key="api_b")
        assert result == 42
        assert cb.states["api_b"] == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_reset(self) -> None:
        cb = CircuitBreaker(failure_threshold=2)
        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(lambda: _fail(), key="api")

        cb.reset("api")
        result = await cb.call(lambda: _ok(), key="api")
        assert result == 42

    @pytest.mark.asyncio
    async def test_half_open_probe_success(self) -> None:
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0)
        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(lambda: _fail(), key="api")

        result = await cb.call(lambda: _ok(), key="api")
        assert result == 42
        assert cb.states["api"] == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_half_open_probe_failure(self) -> None:
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0)
        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(lambda: _fail(), key="api")

        with pytest.raises(ValueError):
            await cb.call(lambda: _fail(), key="api")

        # recovery_timeout=0 所以 OPEN 立即转为 HALF_OPEN
        assert cb.states["api"] == CircuitState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_circuit_open_error_key(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=999)
        with pytest.raises(ValueError):
            await cb.call(lambda: _fail(), key="db")

        with pytest.raises(CircuitOpenError) as exc_info:
            await cb.call(lambda: _ok(), key="db")
        assert exc_info.value.key == "db"


async def _ok():
    return 42


async def _fail():
    raise ValueError("simulated failure")
