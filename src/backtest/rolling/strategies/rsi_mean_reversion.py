# -*- coding: utf-8 -*-
"""RSI Mean Reversion Strategy — buy oversold, sell overbought."""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from backtest.rolling.models import Signal
from backtest.rolling.indicators import IndicatorSeries
from backtest.rolling.strategies.base import Strategy


class RSIMeanReversionStrategy(Strategy):
    name = "rsi_mean_reversion"
    display_name = "RSI均值回归策略"

    def generate_signal(
        self,
        candles: List[Dict],
        idx: int,
        params: Dict[str, Any],
        indicators: Optional[IndicatorSeries] = None,
    ) -> Signal:
        oversold = params.get("oversold", 30)
        overbought = params.get("overbought", 70)

        # Use pre-computed RSI from indicators
        rsi = None
        if indicators is not None and idx < len(indicators.rsi):
            rsi = indicators.rsi[idx]

        if rsi is None:
            return Signal(action="WAIT", score=0)

        # Score: linear mapping from RSI
        score = (50 - rsi) * 2
        score = max(-100, min(100, score))

        threshold = params.get("entry_threshold", 25)
        if rsi <= oversold and score >= threshold:
            action = "LONG"
        elif rsi >= overbought and score <= -threshold:
            action = "SHORT"
        elif score >= 10:
            action = "WEAK_LONG"
        elif score <= -10:
            action = "WEAK_SHORT"
        else:
            action = "WAIT"

        return Signal(action=action, score=score)

    def default_params(self) -> Dict[str, Any]:
        return {
            "rsi_period": 14,
            "oversold": 30,
            "overbought": 70,
            "entry_threshold": 25,
        }

    def param_grid(self) -> Dict[str, List[Any]]:
        return {
            "oversold": [20, 25, 30],
            "overbought": [70, 75, 80],
            "entry_threshold": [20, 25, 30],
        }
