# -*- coding: utf-8 -*-
"""MACD line/signal crossover — rules adapted from vendor/Qbot (MIT).

Reference: vendor/Qbot/qbot/engine/backtest/bitcoin_bt_example.py
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backtest.rolling.indicators import IndicatorSeries
from backtest.rolling.models import Signal
from backtest.rolling.strategies.base import Strategy
from backtest.rolling.strategies.qbot_rules import (
    clamp_score,
    long_only_cross_signal,
    macd_cross_flags,
    macd_lines_at,
)


class MACDCrossoverStrategy(Strategy):
    name = "macd_crossover"
    display_name = "MACD 金叉死叉（Qbot）"

    def generate_signal(
        self,
        candles: List[Dict],
        idx: int,
        params: Dict[str, Any],
        indicators: Optional[IndicatorSeries] = None,
    ) -> Signal:
        if indicators is None:
            return Signal(action="WAIT", score=0.0)

        lines = macd_lines_at(indicators, idx)
        if lines is None:
            return Signal(action="WAIT", score=0.0)

        macd, signal_line, prev_macd, prev_signal = lines
        crossed_up_flag, crossed_down_flag = macd_cross_flags(
            prev_macd, prev_signal, macd, signal_line
        )
        cross_signal = long_only_cross_signal(
            crossed_up_flag=crossed_up_flag,
            crossed_down_flag=crossed_down_flag,
        )
        if cross_signal is not None:
            return cross_signal

        close = candles[idx]["close"]
        spread = (macd - signal_line) / close * 10000 if close else 0.0
        return Signal(action="WAIT", score=clamp_score(spread * 5))

    def default_params(self) -> Dict[str, Any]:
        return {"entry_threshold": 25}

    def param_grid(self) -> Dict[str, List[Any]]:
        return {"entry_threshold": [20, 25, 30]}
