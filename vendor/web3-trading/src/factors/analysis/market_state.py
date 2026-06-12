# -*- coding: utf-8 -*-
"""市场状态识别器 — 基于 K线技术指标判断当前市场状态。"""

from __future__ import annotations

import numpy as np

from factors.analysis.models import MarketState, MarketStateResult
from factors.computers._utils import adx, atr, bollinger_bands, ema, rolling_percentile
from factors.models import KlineSnapshot


class MarketStateDetector:
    """基于 K线快照判断当前市场状态。

    使用多指标组合：
    1. price vs EMA20 → 趋势方向
    2. ADX(14) → 趋势强度（ADX > 25 = trending, ADX <= 25 = ranging）
    3. ATR(14) percentile → 波动率高低
    4. Bollinger bandwidth → 波动率确认

    ADX + EMA rules:
    - ADX > 25 & close > EMA20 → TRENDING_UP
    - ADX > 25 & close < EMA20 → TRENDING_DOWN
    - ADX ≤ 25 & ATR_pct > 80% → HIGH_VOL
    - ADX ≤ 25 & ATR_pct < 20% → LOW_VOL
    - 其他条件 → RANGING
    """

    ADX_TRENDING_THRESHOLD: float = 25.0
    ATR_PERCENTILE_HIGH: float = 0.80
    ATR_PERCENTILE_LOW: float = 0.20
    BB_BANDWIDTH_PERIOD: int = 20

    @classmethod
    def detect(cls, kline: KlineSnapshot) -> MarketStateResult:
        """从 K线快照判断市场状态。优先使用 1d 周期，回退到 4h 再回退到 1h。"""
        close = cls._get_close(kline)
        high = cls._get_high(kline)
        low = cls._get_low(kline)

        if close is None or len(close) < 30:
            return MarketStateResult(
                state=MarketState.RANGING,
                confidence=0.3,
                indicators={},
            )

        # ── 计算指标 ──
        ema20 = ema(close, 20)
        adx_vals = adx(high, low, close, 14)
        atr_vals = atr(high, low, close, 14)
        _, _, bb_lower = bollinger_bands(close, 20, 2.0)

        # 取最新有效值
        latest_adx = cls._last_valid(adx_vals)
        latest_ema20 = cls._last_valid(ema20)
        latest_close = close[-1]
        atr_pct = cls._last_valid(rolling_percentile(atr_vals, 60))
        bb_width = cls._bollinger_bandwidth(close)

        indicators = {
            "adx": round(latest_adx, 2),
            "atr_pct": round(atr_pct, 2) if not np.isnan(atr_pct) else 0.5,
            "ema_ratio": round(latest_close / latest_ema20, 4) if latest_ema20 > 0 else 1.0,
            "bb_width": round(bb_width, 4),
        }

        # ── 状态判定 ──
        state, confidence, adjacent = cls._classify(
            latest_adx, latest_close, latest_ema20, atr_pct, bb_width,
        )

        return MarketStateResult(
            state=state,
            confidence=confidence,
            indicators=indicators,
            adjacent_states=[s for s, _ in adjacent],
            adjacent_weights=[w for _, w in adjacent],
        )

    @classmethod
    def _classify(
        cls,
        adx_val: float,
        close_val: float,
        ema_val: float,
        atr_pct: float,
        bb_width: float,
    ) -> tuple[MarketState, float, list[tuple[MarketState, float]]]:
        if np.isnan(adx_val):
            return MarketState.RANGING, 0.3, []

        is_trending = adx_val > cls.ADX_TRENDING_THRESHOLD
        price_above = close_val > ema_val if ema_val > 0 else False

        if is_trending:
            if price_above:
                return MarketState.TRENDING_UP, 0.85, [(MarketState.RANGING, 0.15)]
            return MarketState.TRENDING_DOWN, 0.85, [(MarketState.RANGING, 0.15)]

        # 非趋势市场 — 按波动率区分
        if not np.isnan(atr_pct) and atr_pct >= cls.ATR_PERCENTILE_HIGH:
            return MarketState.HIGH_VOL, 0.75, [(MarketState.RANGING, 0.25)]
        if not np.isnan(atr_pct) and atr_pct <= cls.ATR_PERCENTILE_LOW:
            return MarketState.LOW_VOL, 0.75, [(MarketState.RANGING, 0.25)]

        return MarketState.RANGING, 0.7, []

    # ── 数据提取辅助 ────────────────────────────────────────────────────────

    @staticmethod
    def _get_close(kline: KlineSnapshot) -> np.ndarray | None:
        for tf_name in ["1d", "4h", "1h"]:
            frame = getattr(kline, f"tf_{tf_name}", None)
            if frame is not None and frame.close is not None and len(frame.close) >= 30:
                return np.asarray(frame.close, dtype=np.float64)
        return None

    @staticmethod
    def _get_high(kline: KlineSnapshot) -> np.ndarray | None:
        for tf_name in ["1d", "4h", "1h"]:
            frame = getattr(kline, f"tf_{tf_name}", None)
            if frame is not None and frame.high is not None and len(frame.high) >= 30:
                return np.asarray(frame.high, dtype=np.float64)
        return None

    @staticmethod
    def _get_low(kline: KlineSnapshot) -> np.ndarray | None:
        for tf_name in ["1d", "4h", "1h"]:
            frame = getattr(kline, f"tf_{tf_name}", None)
            if frame is not None and frame.low is not None and len(frame.low) >= 30:
                return np.asarray(frame.low, dtype=np.float64)
        return None

    @staticmethod
    def _last_valid(arr: np.ndarray) -> float:
        valid = arr[~np.isnan(arr)]
        return float(valid[-1]) if len(valid) > 0 else float("nan")

    @staticmethod
    def _bollinger_bandwidth(close: np.ndarray) -> float:
        middle, upper, lower = bollinger_bands(close, MarketStateDetector.BB_BANDWIDTH_PERIOD, 2.0)
        last_mid = MarketStateDetector._last_valid(middle)
        last_upper = MarketStateDetector._last_valid(upper)
        last_lower = MarketStateDetector._last_valid(lower)
        if last_mid > 0:
            return float((last_upper - last_lower) / last_mid)
        return 0.0
