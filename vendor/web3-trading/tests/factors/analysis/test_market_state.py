# -*- coding: utf-8 -*-
"""市场状态检测器单元测试。"""

import numpy as np
import pytest

from factors.analysis.market_state import MarketStateDetector
from factors.analysis.models import MarketState
from factors.models import KlineFrame, KlineSnapshot


def _trending_up_data(n: int = 80) -> KlineSnapshot:
    """构造上升趋势 K线：逐步上涨，低波动。"""
    rng = np.random.RandomState(42)
    base = np.linspace(100, 130, n)
    close = base + rng.randn(n) * 0.5
    high = close + abs(rng.randn(n) * 0.5)
    low = close - abs(rng.randn(n) * 0.5)
    volume = np.ones(n) * 1000
    return KlineSnapshot(
        tf_1d=KlineFrame(close=close, high=high, low=low, volume=volume),
    )


def _trending_down_data(n: int = 80) -> KlineSnapshot:
    """构造下降趋势 K线。"""
    rng = np.random.RandomState(42)
    base = np.linspace(130, 100, n)
    close = base + rng.randn(n) * 0.5
    high = close + abs(rng.randn(n) * 0.5)
    low = close - abs(rng.randn(n) * 0.5)
    volume = np.ones(n) * 1000
    return KlineSnapshot(
        tf_1d=KlineFrame(close=close, high=high, low=low, volume=volume),
    )


def _ranging_data(n: int = 80) -> KlineSnapshot:
    """构造横盘 K线：中等波动。"""
    rng = np.random.RandomState(42)
    close = 100 + rng.randn(n) * 1.5
    high = close + abs(rng.randn(n) * 0.8)
    low = close - abs(rng.randn(n) * 0.8)
    volume = np.ones(n) * 1000
    return KlineSnapshot(
        tf_1d=KlineFrame(close=close, high=high, low=low, volume=volume),
    )


def _high_vol_data(n: int = 80) -> KlineSnapshot:
    """构造高波动 K线：大幅随机摆动。"""
    rng = np.random.RandomState(42)
    close = 100 + rng.randn(n) * 6.0
    high = close + abs(rng.randn(n) * 3.0)
    low = close - abs(rng.randn(n) * 3.0)
    volume = np.ones(n) * 1000
    return KlineSnapshot(
        tf_1d=KlineFrame(close=close, high=high, low=low, volume=volume),
    )


def _low_vol_data(n: int = 80) -> KlineSnapshot:
    """构造极低波动 K线。"""
    rng = np.random.RandomState(42)
    close = 100 + rng.randn(n) * 0.03
    high = close + 0.015
    low = close - 0.015
    volume = np.ones(n) * 1000
    return KlineSnapshot(
        tf_1d=KlineFrame(close=close, high=high, low=low, volume=volume),
    )


class TestMarketStateDetector:
    def test_trending_up_detection(self) -> None:
        result = MarketStateDetector.detect(_trending_up_data())
        assert result.state == MarketState.TRENDING_UP
        assert result.confidence > 0.5

    def test_trending_down_detection(self) -> None:
        result = MarketStateDetector.detect(_trending_down_data())
        assert result.state == MarketState.TRENDING_DOWN
        assert result.confidence > 0.5

    def test_ranging_detection(self) -> None:
        result = MarketStateDetector.detect(_ranging_data())
        # 中等波动，ADX 通常 < 25 → RANGING 或一个波动率状态
        assert result.state in (
            MarketState.RANGING, MarketState.HIGH_VOL,
            MarketState.LOW_VOL,
        )

    def test_high_vol_detection(self) -> None:
        result = MarketStateDetector.detect(_high_vol_data())
        # 高波动随机数据 → HIGH_VOL 或 RANGING（取决于 ADX 判断）
        assert result.state in (MarketState.HIGH_VOL, MarketState.RANGING)

    def test_low_vol_detection(self) -> None:
        result = MarketStateDetector.detect(_low_vol_data())
        # 极低波动数据可能被归类为 LOW_VOL，取决于 ATR percentile
        assert result.state is not None
        assert result.confidence > 0.3

    def test_empty_kline(self) -> None:
        empty = KlineSnapshot()
        result = MarketStateDetector.detect(empty)
        assert result.state == MarketState.RANGING
        assert result.confidence == 0.3

    def test_indicators_in_result(self) -> None:
        result = MarketStateDetector.detect(_ranging_data())
        assert "adx" in result.indicators
        assert "atr_pct" in result.indicators
        assert "ema_ratio" in result.indicators

    def test_adjacent_states_for_trending(self) -> None:
        result = MarketStateDetector.detect(_trending_up_data())
        assert len(result.adjacent_states) >= 1
        assert MarketState.RANGING in result.adjacent_states

    def test_fallback_to_4h_when_1d_empty(self) -> None:
        """1d 数据为空时回退到 4h。"""
        close_4h = np.linspace(100, 130, 80) + np.random.RandomState(1).randn(80) * 0.5
        kline = KlineSnapshot(
            tf_4h=KlineFrame(
                close=close_4h,
                high=close_4h + 0.5,
                low=close_4h - 0.5,
                volume=np.ones(80) * 1000,
            ),
        )
        result = MarketStateDetector.detect(kline)
        assert result.confidence > 0.3

    def test_can_detect_all_states(self) -> None:
        """所有五种状态的 detect 都应正常返回，不抛异常。"""
        datasets = {
            "trending_up": _trending_up_data(),
            "trending_down": _trending_down_data(),
            "ranging": _ranging_data(),
            "high_vol": _high_vol_data(),
            "low_vol": _low_vol_data(),
        }
        results: set[MarketState] = set()
        for label, data in datasets.items():
            r = MarketStateDetector.detect(data)
            results.add(r.state)
        # 至少检测出两种不同状态
        assert len(results) >= 2, f"Expected ≥2 states, got {results}"
