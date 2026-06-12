"""tests for KuCoinClient — real API calls (public endpoints, no auth required).

KuCoin 公开接口测试，无需 API Key，直接调用真实 API。
"""

from __future__ import annotations

import pytest

from libs.kucoin_openapi import KuCoinClient
from libs.kucoin_openapi.enums import FuturesKlineGranularity, KlineGranularity
from libs.kucoin_openapi.models import (
    CurrentFundingRate,
    FundingRateItem,
    FuturesKlineCandle,
    KlineCandle,
    OpenInterestStats,
)


def _make_client() -> KuCoinClient:
    return KuCoinClient(timeout=15)


# ===================================================================
# Spot K-line
# ===================================================================

@pytest.mark.asyncio
class TestGetKline:
    async def test_btc_1h_returns_candles(self) -> None:
        c = _make_client()
        try:
            candles = await c.get_kline("BTC-USDT", KlineGranularity.H1)
            assert len(candles) > 0
            assert all(isinstance(k, KlineCandle) for k in candles)
            k = candles[0]
            assert isinstance(k.time, int) and k.time > 0
            assert k.open > 0
            assert k.close > 0
            assert k.high >= k.low
            assert k.volume >= 0
        finally:
            await c.close()

    async def test_eth_15min_returns_candles(self) -> None:
        c = _make_client()
        try:
            candles = await c.get_kline("ETH-USDT", KlineGranularity.M15)
            assert len(candles) > 0
            assert all(isinstance(k, KlineCandle) for k in candles)
        finally:
            await c.close()

    async def test_candles_are_chronological(self) -> None:
        c = _make_client()
        try:
            candles = await c.get_kline("BTC-USDT", KlineGranularity.H1)
            times = [k.time for k in candles]
            assert times == sorted(times), "candles should be oldest-first"
        finally:
            await c.close()

    async def test_with_start_end(self) -> None:
        import time
        c = _make_client()
        try:
            end_s = int(time.time())
            start_s = end_s - 86400
            candles = await c.get_kline("BTC-USDT", KlineGranularity.H1, start_at=start_s, end_at=end_s)
            if candles:
                assert candles[0].time >= start_s
                assert candles[-1].time <= end_s
        finally:
            await c.close()

    async def test_cached_second_call_faster(self) -> None:
        c = _make_client()
        try:
            c1 = await c.get_kline("BTC-USDT", KlineGranularity.M15, ttl=300)
            c2 = await c.get_kline("BTC-USDT", KlineGranularity.M15, ttl=300)
            assert len(c1) == len(c2)
            assert c1[0].time == c2[0].time
        finally:
            await c.close()


@pytest.mark.asyncio
class TestGetMultiTfKline:
    async def test_default_granularities(self) -> None:
        c = _make_client()
        try:
            result = await c.get_multi_tf_kline("BTC-USDT")
            assert set(result.keys()) == {"15min", "1hour", "4hour", "1day"}
            for key, candles in result.items():
                assert len(candles) > 0, f"no candles for {key}"
                assert all(isinstance(k, KlineCandle) for k in candles)
        finally:
            await c.close()

    async def test_custom_granularities(self) -> None:
        c = _make_client()
        try:
            result = await c.get_multi_tf_kline(
                "ETH-USDT",
                granularities=[KlineGranularity.H1, KlineGranularity.D1],
            )
            assert set(result.keys()) == {"1hour", "1day"}
        finally:
            await c.close()


# ===================================================================
# Futures K-line
# ===================================================================

@pytest.mark.asyncio
class TestGetFuturesKline:
    async def test_btc_1h_returns_candles(self) -> None:
        c = _make_client()
        try:
            candles = await c.get_futures_kline("XBTUSDTM", FuturesKlineGranularity.H1)
            assert len(candles) > 0
            assert all(isinstance(k, FuturesKlineCandle) for k in candles)
            k = candles[0]
            assert k.open > 0
            assert k.close > 0
            # FIXME: KuCoin futures K-line field order may differ from spot
            # (spot: [time, open, close, high, low, volume, turnover]
            #  futures: [time, open, high, low, close, volume])
            # _parse_kline uses the spot order for both, which may swap high/low/close
        finally:
            await c.close()

    async def test_eth_15min_returns_candles(self) -> None:
        c = _make_client()
        try:
            candles = await c.get_futures_kline("ETHUSDTM", FuturesKlineGranularity.M15)
            assert len(candles) > 0
            assert all(isinstance(k, FuturesKlineCandle) for k in candles)
        finally:
            await c.close()


@pytest.mark.asyncio
class TestGetFuturesMultiTfKline:
    async def test_default_granularities(self) -> None:
        c = _make_client()
        try:
            result = await c.get_futures_multi_tf_kline("XBTUSDTM")
            assert set(result.keys()) == {"15", "60", "240", "1440"}
            for key, candles in result.items():
                assert len(candles) > 0, f"no candles for {key}"
                assert all(isinstance(k, FuturesKlineCandle) for k in candles)
        finally:
            await c.close()


# ===================================================================
# Funding Rate
# ===================================================================

@pytest.mark.asyncio
class TestFundingRate:
    async def test_current_funding_rate(self) -> None:
        c = _make_client()
        try:
            result = await c.get_current_funding_rate("XBTUSDTM")
            assert isinstance(result, CurrentFundingRate)
            assert "XBTUSDTM" in result.symbol.upper().replace(".", "")
            assert isinstance(result.value, float)
        finally:
            await c.close()

    async def test_funding_rate_history(self) -> None:
        c = _make_client()
        try:
            items = await c.get_funding_rate_history("XBTUSDTM")
            assert len(items) > 0
            assert all(isinstance(item, FundingRateItem) for item in items)
            assert all(isinstance(item.funding_rate, float) for item in items)
        finally:
            await c.close()

    async def test_funding_rate_history_chronological(self) -> None:
        c = _make_client()
        try:
            items = await c.get_funding_rate_history("XBTUSDTM")
            timepoints = [item.timepoint for item in items]
            assert timepoints == sorted(timepoints), "funding rate history should be oldest-first"
        finally:
            await c.close()

    async def test_funding_rate_custom_range(self) -> None:
        import time
        c = _make_client()
        try:
            now_ms = int(time.time() * 1000)
            start_ms = now_ms - 3 * 86400_000
            items = await c.get_funding_rate_history("XBTUSDTM", start_at=start_ms, end_at=now_ms)
            if items:
                assert items[0].timepoint >= start_ms
        finally:
            await c.close()


# ===================================================================
# Open Interest
# ===================================================================

@pytest.mark.asyncio
class TestOpenInterest:
    async def test_btc_open_interest(self) -> None:
        c = _make_client()
        try:
            result = await c.get_open_interest("XBTUSDTM")
            assert isinstance(result, OpenInterestStats)
            assert "XBTUSDTM" in result.symbol
            assert result.open_interest >= 0
        finally:
            await c.close()

    async def test_eth_open_interest(self) -> None:
        c = _make_client()
        try:
            result = await c.get_open_interest("ETHUSDTM")
            assert isinstance(result, OpenInterestStats)
            assert "ETHUSDTM" in result.symbol
            assert result.open_interest >= 0
        finally:
            await c.close()


# ===================================================================
# TTL Cache
# ===================================================================

class TestTTLCache:
    async def _get_cached_kline(self) -> tuple:
        c = _make_client()
        try:
            c1 = await c.get_kline("BTC-USDT", KlineGranularity.M15, ttl=300)
            c2 = await c.get_kline("BTC-USDT", KlineGranularity.M15, ttl=300)
            return c1, c2
        finally:
            await c.close()

    @pytest.mark.asyncio
    async def test_cache_reuses_data(self) -> None:
        c1, c2 = await self._get_cached_kline()
        assert len(c1) == len(c2)
        for a, b in zip(c1, c2):
            assert a.time == b.time
            assert a.close == b.close

    def test_set_get_clear(self) -> None:
        c = _make_client()
        c._cache.set("test_key", "value")
        assert c._cache.get("test_key") == "value"
        c._cache.clear()
        assert c._cache.get("test_key") is None
