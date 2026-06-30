# -*- coding: utf-8 -*-
"""MACD Strategy — trend-following via MACD crossover and histogram.

Scoring variant used in multi-strategy compare; see also `macd_crossover.py`
for Qbot-style binary cross (vendor/Qbot/qbot/engine/backtest/bitcoin_bt_example.py).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backtest.rolling.indicators import IndicatorSeries
from backtest.rolling.models import Signal
from backtest.rolling.strategies.base import Strategy
from backtest.rolling.strategies.qbot_rules import (
    clamp_score,
    macd_cross_score_delta,
    score_to_directional_action,
    zero_line_cross_score_delta,
)


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

        prev_macd = indicators.macd_line[idx - 1] if idx > 0 else None
        prev_signal = indicators.macd_signal[idx - 1] if idx > 0 else None

        score = 0.0
        hist_weight = params.get("histogram_weight", 30)
        cross_weight = params.get("crossover_weight", 25)

        close = candles[idx]["close"]
        if close > 0:
            norm_hist = histogram / close * 10000
            score += clamp_score(norm_hist * hist_weight / 10, low=-50.0, high=50.0)

        if prev_macd is not None and prev_signal is not None:
            score += macd_cross_score_delta(
                float(prev_macd),
                float(prev_signal),
                float(macd),
                float(signal_line),
                cross_weight=float(cross_weight),
            )

        if prev_macd is not None:
            score += zero_line_cross_score_delta(float(prev_macd), float(macd))

        score = clamp_score(score)
        threshold = float(params.get("entry_threshold", 25))
        return Signal(action=score_to_directional_action(score, threshold=threshold), score=score)

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
