# -*- coding: utf-8 -*-
"""测试指数退避重试。"""

import asyncio

import pytest

from factors.fetch.retry import RetryConfig, with_retry


class TestWithRetry:
    @pytest.mark.asyncio
    async def test_success_first_attempt(self) -> None:
        call_count = 0

        async def _ok():
            nonlocal call_count
            call_count += 1
            return 42

        result = await with_retry(_ok)
        assert result == 42
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_timeout(self) -> None:
        call_count = 0

        async def _flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise asyncio.TimeoutError("timeout")
            return "ok"

        result = await with_retry(_flaky)
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_exhaust_retries(self) -> None:
        call_count = 0

        async def _always_fail():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("fail")

        with pytest.raises(ConnectionError):
            await with_retry(_always_fail, RetryConfig(max_retries=2))
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_non_retryable_exception(self) -> None:
        call_count = 0

        async def _value_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("not retryable")

        with pytest.raises(ValueError):
            await with_retry(_value_error)
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_custom_retryable(self) -> None:
        call_count = 0

        async def _custom():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("custom retryable")
            return "ok"

        cfg = RetryConfig(max_retries=2, retryable_exceptions=(ValueError,))
        result = await with_retry(_custom, cfg)
        assert result == "ok"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_label_in_logs(self) -> None:
        async def _ok():
            return 1

        result = await with_retry(_ok, label="test_source")
        assert result == 1

    @pytest.mark.asyncio
    async def test_zero_retries(self) -> None:
        call_count = 0

        async def _fail():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("fail")

        with pytest.raises(ConnectionError):
            await with_retry(_fail, RetryConfig(max_retries=0))
        assert call_count == 1
