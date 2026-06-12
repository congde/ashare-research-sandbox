# -*- coding: utf-8 -*-
"""MACD Strategy — trend-following via MACD crossover and histogram."""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from backtest.models import Signal
from backtest.indicators import IndicatorSeries
from backtest.strategies.base import Strategy


class MACDStrategy(Strategy):
    name = "macd"
    display_name = "MACD策略"

    def generate_signal(
        self,
        candles: List[Dict],
        idx: int,
        params: Dict[str, Any],
        indicators: Optional[IndicatorSeries] = None,
    ) -> Signal:
        if indicators is None or idx >= len(indicators.macd_line):
            return Signal(action="WAIT", score=0)

        macd = indicators.macd_line[idx]
        signal_line = indicators.macd_signal[idx]
        histogram = indicators.macd_histogram[idx]

        if macd is None or signal_line is None or histogram is None:
            return Signal(action="WAIT", score=0)

        # Previous bar for crossover detection
        prev_macd = indicators.macd_line[idx - 1] if idx > 0 else None
        prev_signal = indicators.macd_signal[idx - 1] if idx > 0 else None

        score = 0.0
        hist_weight = params.get("histogram_weight", 30)
        cross_weight = params.get("crossover_weight", 25)

        # Histogram strength (normalized)
        close = candles[idx]["close"]
        if close > 0:
            norm_hist = histogram / close * 10000  # basis points
            score += max(-50, min(50, norm_hist * hist_weight / 10))

        # Crossover detection
        if prev_macd is not None and prev_signal is not None:
            crossed_up = prev_macd <= prev_signal and macd > signal_line
            crossed_down = prev_macd >= prev_signal and macd < signal_line
            if crossed_up:
                score += cross_weight
            elif crossed_down:
                score -= cross_weight

        # Zero-line cross adds conviction
        if prev_macd is not None:
            if prev_macd <= 0 and macd > 0:
                score += 10
            elif prev_macd >= 0 and macd < 0:
                score -= 10

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
            "histogram_weight": 30,
            "crossover_weight": 25,
            "entry_threshold": 25,
        }

    def param_grid(self) -> Dict[str, List[Any]]:
        return {
            "histogram_weight": [20, 30, 40],
            "crossover_weight": [15, 25, 35],
            "entry_threshold": [20, 25, 30],
        }
