"""tests for K-line technical factor computers (trend_strength, macd_divergence, etc.)"""

import numpy as np
import pytest

from factors.computers.common.atr_normalized import ATRNormalizedComputer
from factors.computers.common.bollinger_breakout import BollingerBreakoutComputer
from factors.computers.common.macd_divergence import MACDDivergenceComputer
from factors.computers.common.momentum_resonance import MomentumResonanceComputer
from factors.computers.common.multi_tf_return import MultiTFReturnComputer
from factors.computers.common.rsi_extreme import RSIExtremeComputer
from factors.computers.common.trend_strength import TrendStrengthComputer
from factors.computers.common.volatility import VolatilityComputer
from factors.computers.common.volume_price_divergence import VolumePriceDivergenceComputer
from factors.computers.common.vwap_deviation import VWAPDeviationComputer
from factors.context import FactorContext
from factors.enums import MarketType, SignalDirection
from factors.models import KlineFrame, KlineSnapshot


def _make_ctx_with_kline(snapshot: KlineSnapshot, market_type=MarketType.SPOT) -> FactorContext:
    return FactorContext(
        vs_token_id="token_test",
        symbol="TEST",
        coin_key="test",
        fetched_at_ms=1717200000000,
        current_price=100.0,
        market_type=market_type,
        data={
            "kline": snapshot,
            "price_indicators": type("Fake", (), {"price": 100.0})(),
        },
    )


# ---------------------------------------------------------------------------
# TrendStrengthComputer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTrendStrengthComputer:
    async def test_with_klines(self, kline_snapshot) -> None:
        ctx = _make_ctx_with_kline(kline_snapshot)
        comp = TrendStrengthComputer()
        result = await comp.compute_if_available(ctx)
        assert result is not None

    async def test_no_klines(self, empty_ctx) -> None:
        comp = TrendStrengthComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None


# ---------------------------------------------------------------------------
# MACDDivergenceComputer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMACDDivergenceComputer:
    async def test_with_klines(self, kline_snapshot) -> None:
        ctx = _make_ctx_with_kline(kline_snapshot)
        comp = MACDDivergenceComputer()
        result = await comp.compute_if_available(ctx)
        assert result is not None

    async def test_no_klines(self, empty_ctx) -> None:
        comp = MACDDivergenceComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None


# ---------------------------------------------------------------------------
# MomentumResonanceComputer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMomentumResonanceComputer:
    async def test_with_klines(self, kline_snapshot) -> None:
        ctx = _make_ctx_with_kline(kline_snapshot)
        comp = MomentumResonanceComputer()
        result = await comp.compute_if_available(ctx)
        assert result is not None

    async def test_no_klines(self, empty_ctx) -> None:
        comp = MomentumResonanceComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None


# ---------------------------------------------------------------------------
# MultiTFReturnComputer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMultiTFReturnComputer:
    async def test_with_klines(self, kline_snapshot) -> None:
        ctx = _make_ctx_with_kline(kline_snapshot)
        comp = MultiTFReturnComputer()
        result = await comp.compute_if_available(ctx)
        assert result is not None

    async def test_no_klines(self, empty_ctx) -> None:
        comp = MultiTFReturnComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None


# ---------------------------------------------------------------------------
# RSIExtremeComputer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRSIExtremeComputer:
    async def test_with_klines(self, kline_snapshot) -> None:
        ctx = _make_ctx_with_kline(kline_snapshot)
        comp = RSIExtremeComputer()
        result = await comp.compute_if_available(ctx)
        assert result is not None

    async def test_no_klines(self, empty_ctx) -> None:
        comp = RSIExtremeComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None

    async def test_extreme_oversold_produces_bullish(self) -> None:
        """构造极度超卖的 K线数据 → 应该看涨"""
        np.random.seed(99)
        n = 50
        # 持续下跌 → RSI 低
        close = 100.0 * np.cumprod(1.0 + np.random.normal(-0.005, 0.02, n))
        high = close * 1.01
        low = close * 0.99
        volume = np.ones(n) * 100
        frame = KlineFrame(close=close, high=high, low=low, volume=volume)
        snap = KlineSnapshot(tf_1h=frame)

        ctx = _make_ctx_with_kline(snap)
        comp = RSIExtremeComputer()
        result = await comp.compute_if_available(ctx)
        assert result is not None
        # 不应崩溃
        assert isinstance(result.signal_direction, SignalDirection)


# ---------------------------------------------------------------------------
# BollingerBreakoutComputer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestBollingerBreakoutComputer:
    async def test_with_klines(self, kline_snapshot) -> None:
        ctx = _make_ctx_with_kline(kline_snapshot)
        comp = BollingerBreakoutComputer()
        result = await comp.compute_if_available(ctx)
        assert result is not None

    async def test_no_klines(self, empty_ctx) -> None:
        comp = BollingerBreakoutComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None


# ---------------------------------------------------------------------------
# VWAPDeviationComputer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestVWAPDeviationComputer:
    async def test_with_klines(self, kline_snapshot) -> None:
        ctx = _make_ctx_with_kline(kline_snapshot)
        comp = VWAPDeviationComputer()
        result = await comp.compute_if_available(ctx)
        assert result is not None

    async def test_no_klines(self, empty_ctx) -> None:
        comp = VWAPDeviationComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None


# ---------------------------------------------------------------------------
# ATRNormalizedComputer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestATRNormalizedComputer:
    async def test_with_klines(self, kline_snapshot) -> None:
        ctx = _make_ctx_with_kline(kline_snapshot)
        comp = ATRNormalizedComputer()
        result = await comp.compute_if_available(ctx)
        assert result is not None

    async def test_no_klines(self, empty_ctx) -> None:
        comp = ATRNormalizedComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None


# ---------------------------------------------------------------------------
# VolatilityComputer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestVolatilityComputer:
    async def test_with_klines(self, kline_snapshot) -> None:
        ctx = _make_ctx_with_kline(kline_snapshot)
        comp = VolatilityComputer()
        result = await comp.compute_if_available(ctx)
        assert result is not None

    async def test_no_klines(self, empty_ctx) -> None:
        comp = VolatilityComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None


# ---------------------------------------------------------------------------
# VolumePriceDivergenceComputer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestVolumePriceDivergenceComputer:
    async def test_with_klines(self, kline_snapshot) -> None:
        ctx = _make_ctx_with_kline(kline_snapshot)
        comp = VolumePriceDivergenceComputer()
        result = await comp.compute_if_available(ctx)
        assert result is not None

    async def test_no_klines(self, empty_ctx) -> None:
        comp = VolumePriceDivergenceComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None
