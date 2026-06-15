# -*- coding: utf-8 -*-
"""Bollinger Band Squeeze Strategy — low volatility → breakout capture."""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from backtest.rolling.models import Signal
from backtest.rolling.indicators import IndicatorSeries
from backtest.rolling.strategies.base import Strategy


class BollingerSqueezeStrategy(Strategy):
    name = "bollinger_squeeze"
    display_name = "布林带收缩策略"

    def generate_signal(
        self,
        candles: List[Dict],
        idx: int,
        params: Dict[str, Any],
        indicators: Optional[IndicatorSeries] = None,
    ) -> Signal:
        if indicators is None or idx >= len(indicators.bb_width):
            return Signal(action="WAIT", score=0)

        bb_width = indicators.bb_width[idx]
        bb_pct_b = indicators.bb_pct_b[idx]
        breakout = indicators.breakout[idx]
        vol_ratio = indicators.vol_ratio[idx]
        trend = indicators.trend[idx]

        if bb_width is None or bb_pct_b is None:
            return Signal(action="WAIT", score=0)

        squeeze_threshold = params.get("squeeze_threshold", 3.0)
        expansion_threshold = params.get("expansion_threshold", 5.0)

        score = 0.0

        # Detect squeeze state (narrow bands)
        in_squeeze = bb_width < squeeze_threshold

        # Detect expansion (breakout from squeeze)
        lookback = params.get("squeeze_lookback", 5)
        was_squeezing = False
        if idx >= lookback:
            was_squeezing = any(
                indicators.bb_width[i] is not None and indicators.bb_width[i] < squeeze_threshold
                for i in range(idx - lookback, idx)
            )

        if was_squeezing and bb_width >= expansion_threshold:
            # Breakout from squeeze — strong signal
            if bb_pct_b >= 80 or breakout == "bullish":
                score += 40
            elif bb_pct_b <= 20 or breakout == "bearish":
                score -= 40
            elif "bullish" in trend:
                score += 25
            elif "bearish" in trend:
                score -= 25
        elif in_squeeze:
            # Still in squeeze — no strong signal, wait
            score = 0
        else:
            # Normal bands — use %B for mean reversion
            if bb_pct_b >= 95:
                score -= 20
            elif bb_pct_b <= 5:
                score += 20
            elif bb_pct_b >= 80:
                score -= 10
            elif bb_pct_b <= 20:
                score += 10

        # Volume confirmation
        if abs(score) > 0 and vol_ratio >= 1.5:
            score *= 1.3

        score = max(-100, min(100, score))
        threshold = params.get("entry_threshold", 25)

        if score >= threshold:
            action = "LONG"
        elif score >= 10:
            action = "WEAK_LONG"
        elif score <= -threshold:
            action = "SHORT"
        elif score <= -10:
            action = "WEAK_SHORT"
        else:
            action = "WAIT"

        return Signal(action=action, score=score)

    def default_params(self) -> Dict[str, Any]:
        return {
            "squeeze_threshold": 3.0,
            "expansion_threshold": 5.0,
            "squeeze_lookback": 5,
            "entry_threshold": 25,
        }

    def param_grid(self) -> Dict[str, List[Any]]:
        return {
            "squeeze_threshold": [2.0, 3.0, 4.0],
            "expansion_threshold": [4.0, 5.0, 6.0],
            "entry_threshold": [20, 25, 30],
        }
