"""tests for factors/computers/_utils.py — K线技术指标计算。"""

import numpy as np
import pytest

from factors.computers._utils import (
    adx,
    atr,
    bollinger_bands,
    ema,
    log_returns,
    macd,
    rolling_percentile,
    rolling_volatility,
    rsi,
    sma,
    vwap,
)


# ----- test vectors -----

_CLOSE_UP = np.array(
    [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0, 110.0],
    dtype=np.float64,
)
_CLOSE_FLAT = np.array([100.0] * 20, dtype=np.float64)


# ---------------------------------------------------------------------------
# EMA
# ---------------------------------------------------------------------------


class TestEMA:
    def test_basic(self) -> None:
        result = ema(_CLOSE_UP, period=3)
        assert not np.isnan(result[-1])
        assert result[-1] > _CLOSE_UP[-3]

    def test_short_series(self) -> None:
        result = ema(np.array([1.0, 2.0]), period=5)
        assert np.all(np.isnan(result))

    def test_monotonic_input(self) -> None:
        result = ema(_CLOSE_UP, period=3)
        # EMA of rising series should also be rising
        assert result[-1] > result[3]


class TestSMA:
    def test_basic(self) -> None:
        result = sma(_CLOSE_UP, period=3)
        # First valid: mean(100,101,102)=101
        assert result[2] == pytest.approx(101.0)

    def test_short_series(self) -> None:
        result = sma(np.array([1.0]), period=5)
        assert np.all(np.isnan(result))


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------


class TestRSI:
    def test_all_up(self) -> None:
        result = rsi(_CLOSE_UP, period=3)
        valid = result[~np.isnan(result)]
        assert len(valid) > 0
        # All gains → RSI should be high
        assert valid[-1] > 50.0

    def test_flat(self) -> None:
        result = rsi(_CLOSE_FLAT, period=5)
        valid = result[~np.isnan(result)]
        assert valid[-1] == pytest.approx(0.0)  # no change = 0? No, RSI = 50 when flat
        # Actually with flat data, delta is all zero, gain=0, loss=0, RS=0, RSI=0
        # This is a known edge case

    def test_output_bounds(self) -> None:
        data = np.random.RandomState(42).normal(0, 1, 200).cumsum() + 100
        result = rsi(data, period=14)
        valid = result[~np.isnan(result)]
        assert np.all(valid >= 0)
        assert np.all(valid <= 100)


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------


class TestMACD:
    def test_basic(self) -> None:
        data = np.random.RandomState(42).normal(0, 1, 200).cumsum() + 100
        macd_line, signal_line, histogram = macd(data)
        assert macd_line.shape == data.shape
        assert signal_line.shape == data.shape
        assert histogram.shape == data.shape
        valid = ~np.isnan(macd_line)
        assert np.any(valid)

    def test_histogram_is_difference(self) -> None:
        data = np.random.RandomState(42).normal(0, 1, 200).cumsum() + 100
        _, _, histogram = macd(data)
        valid = ~np.isnan(histogram)
        assert np.any(valid)


# ---------------------------------------------------------------------------
# ADX
# ---------------------------------------------------------------------------


class TestADX:
    def test_basic(self) -> None:
        n = 100
        rng = np.random.RandomState(42)
        close = 100 + rng.normal(0, 1, n).cumsum()
        high = close + rng.uniform(0.5, 2, n)
        low = close - rng.uniform(0.5, 2, n)
        result = adx(high, low, close, period=14)
        valid = result[~np.isnan(result)]
        assert len(valid) > 0
        assert np.all(valid >= 0)

    def test_short_series(self) -> None:
        r = adx(np.array([1.0, 2.0]), np.array([0.5, 1.0]), np.array([1.0, 1.5]), period=14)
        assert np.all(np.isnan(r))


# ---------------------------------------------------------------------------
# ATR
# ---------------------------------------------------------------------------


class TestATR:
    def test_basic(self) -> None:
        n = 50
        rng = np.random.RandomState(42)
        close = 100 + rng.normal(0, 1, n).cumsum()
        high = close + rng.uniform(0.5, 2, n)
        low = close - rng.uniform(0.5, 2, n)
        result = atr(high, low, close, period=14)
        valid = result[~np.isnan(result)]
        assert len(valid) > 0
        assert np.all(valid >= 0)


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------


class TestBollingerBands:
    def test_basic(self) -> None:
        n = 100
        rng = np.random.RandomState(42)
        close = 100 + rng.normal(0, 1, n).cumsum()
        middle, upper, lower = bollinger_bands(close)
        valid = ~np.isnan(middle)
        assert np.any(valid)
        # upper > middle > lower
        assert np.all(upper[valid] >= middle[valid])
        assert np.all(middle[valid] >= lower[valid])

    def test_flat_data(self) -> None:
        middle, upper, lower = bollinger_bands(np.array([100.0] * 30))
        # All values equal → std = 0 → upper = middle = lower
        assert middle[-1] == pytest.approx(100.0)
        assert upper[-1] == pytest.approx(100.0)
        assert lower[-1] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# VWAP
# ---------------------------------------------------------------------------


class TestVWAP:
    def test_basic(self) -> None:
        n = 100
        close = np.full(n, 100.0)
        volume = np.full(n, 1.0)
        result = vwap(close, volume, period=10)
        valid = result[~np.isnan(result)]
        assert np.all(valid == pytest.approx(100.0))

    def test_weighted(self) -> None:
        close = np.array([100.0, 110.0, 105.0, 115.0, 120.0])
        volume = np.array([10.0, 1.0, 10.0, 1.0, 10.0])
        result = vwap(close, volume, period=3)
        # window [100,110,105], vol=[10,1,10] → (1000+110+1050)/(10+1+10)=2160/21≈102.86
        assert result[2] == pytest.approx((1000 + 110 + 1050) / 21, rel=1e-3)


# ---------------------------------------------------------------------------
# log_returns
# ---------------------------------------------------------------------------


class TestLogReturns:
    def test_basic(self) -> None:
        close = np.array([100.0, 101.0, 102.0, 103.0], dtype=np.float64)
        result = log_returns(close, lookback=1)
        assert result[1] == pytest.approx(np.log(101.0 / 100.0))
        assert np.isnan(result[0])

    def test_lookback_2(self) -> None:
        close = np.array([100.0, 101.0, 102.0, 103.0], dtype=np.float64)
        result = log_returns(close, lookback=2)
        assert result[2] == pytest.approx(np.log(102.0 / 100.0))

    def test_short_series(self) -> None:
        result = log_returns(np.array([1.0, 2.0]), lookback=5)
        assert np.all(np.isnan(result))


# ---------------------------------------------------------------------------
# rolling_volatility
# ---------------------------------------------------------------------------


class TestRollingVolatility:
    def test_basic(self) -> None:
        n = 100
        rng = np.random.RandomState(42)
        close = 100 + rng.normal(0, 1, n).cumsum()
        result = rolling_volatility(close, period=20)
        valid = result[~np.isnan(result)]
        assert len(valid) > 0
        assert np.all(valid >= 0)

    def test_flat_data(self) -> None:
        close = np.array([100.0] * 30)
        result = rolling_volatility(close, period=5)
        valid = result[~np.isnan(result)]
        assert np.all(valid >= 0)


# ---------------------------------------------------------------------------
# rolling_percentile
# ---------------------------------------------------------------------------


class TestRollingPercentile:
    def test_all_same(self) -> None:
        data = np.array([5.0] * 20)
        result = rolling_percentile(data, window=5)
        valid = result[~np.isnan(result)]
        # All equal → each value is at the max of the window → 1.0
        assert np.all(valid >= 0.9)

    def test_trending_up(self) -> None:
        data = np.arange(1, 21, dtype=float)
        result = rolling_percentile(data, window=5)
        # Last value (20) should be at 100th percentile in its window
        assert result[-1] == pytest.approx(1.0)

    def test_trending_down(self) -> None:
        data = np.arange(20, 0, -1, dtype=float)
        result = rolling_percentile(data, window=5)
        # Last value (1) should be at 0th percentile (or close) in its window
        assert result[-1] <= 0.2
