# -*- coding: utf-8 -*-
"""Technical Signal Strategy — multi-factor scoring using pre-computed indicators.

O(1) per candle via IndicatorSeries lookups (was O(n²) with analyze_candles).
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from backtest.rolling.models import Signal
from backtest.rolling.indicators import IndicatorSeries
from backtest.rolling.strategies.base import Strategy


class TechnicalSignalStrategy(Strategy):
    name = "technical_signal"
    display_name = "技术信号策略"

    def generate_signal(
        self,
        candles: List[Dict],
        idx: int,
        params: Dict[str, Any],
        indicators: Optional[IndicatorSeries] = None,
    ) -> Signal:
        if indicators is None or idx >= len(indicators.trend):
            return Signal(action="WAIT", score=0)

        trend = indicators.trend[idx]
        rsi = indicators.rsi[idx]
        bb_pct_b = indicators.bb_pct_b[idx]
        breakout = indicators.breakout[idx]
        vol_ratio = indicators.vol_ratio[idx]
        range_pos = indicators.range_pos[idx]
        regime = indicators.regime[idx]

        tw = params.get("trend_weight", 20)
        rw = params.get("rsi_weight", 12)

        score = 0.0

        trend_scores = {
            "bullish": tw, "weak_bullish": tw // 2,
            "bearish": -tw, "weak_bearish": -(tw // 2),
        }
        score += trend_scores.get(trend, 0)

        if rsi is not None:
            oversold = params.get("rsi_oversold", 30)
            overbought = params.get("rsi_overbought", 70)
            if rsi >= overbought + 10:
                score -= rw
            elif rsi >= overbought:
                score -= rw * 0.6
            elif rsi <= oversold - 10:
                score += rw
            elif rsi <= oversold:
                score += rw * 0.6

        if bb_pct_b is not None:
            if bb_pct_b >= 100:
                score -= 6
            elif bb_pct_b <= 0:
                score += 6

        if breakout == "bullish":
            score += 15 if vol_ratio >= 1.5 else 8
        elif breakout == "bearish":
            score -= 15 if vol_ratio >= 1.5 else 8

        if regime == "trending":
            if "bullish" in trend:
                score += 5
            elif "bearish" in trend:
                score -= 5
        elif regime == "ranging":
            if range_pos >= 80:
                score -= 4
            elif range_pos <= 20:
                score += 4

        score = max(-100, min(100, score))
        entry_threshold = params.get("entry_threshold", 25)

        if score >= entry_threshold:
            action = "LONG"
        elif score >= 10:
            action = "WEAK_LONG"
        elif score <= -entry_threshold:
            action = "SHORT"
        elif score <= -10:
            action = "WEAK_SHORT"
        else:
            action = "WAIT"

        return Signal(action=action, score=score)

    def default_params(self) -> Dict[str, Any]:
        return {
            "trend_weight": 20,
            "rsi_weight": 12,
            "rsi_oversold": 30,
            "rsi_overbought": 70,
            "entry_threshold": 25,
        }

    def param_grid(self) -> Dict[str, List[Any]]:
        return {
            "trend_weight": [15, 20, 25],
            "rsi_weight": [8, 12, 16],
            "rsi_oversold": [25, 30, 35],
            "rsi_overbought": [65, 70, 75],
            "entry_threshold": [20, 25, 30],
        }
