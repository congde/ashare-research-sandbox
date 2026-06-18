# -*- coding: utf-8 -*-
"""MACD line/signal crossover — rules adapted from vendor/Qbot (MIT).

Reference: vendor/Qbot/qbot/engine/backtest/bitcoin_bt_example.py
  - MACD line crosses above signal → enter long
  - MACD line crosses below signal → exit long (no short entry)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backtest.rolling.indicators import IndicatorSeries
from backtest.rolling.models import Signal
from backtest.rolling.strategies.base import Strategy


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
        if indicators is None or idx >= len(indicators.macd_line):
            return Signal(action="WAIT", score=0.0)

        macd = indicators.macd_line[idx]
        signal_line = indicators.macd_signal[idx]
        prev_macd = indicators.macd_line[idx - 1] if idx > 0 else None
        prev_signal = indicators.macd_signal[idx - 1] if idx > 0 else None

        if macd is None or signal_line is None or prev_macd is None or prev_signal is None:
            return Signal(action="WAIT", score=0.0)

        crossed_up = prev_macd <= prev_signal and macd > signal_line
        crossed_down = prev_macd >= prev_signal and macd < signal_line

        if crossed_up:
            return Signal(action="LONG", score=50.0)
        if crossed_down:
            return Signal(action="WAIT", score=-50.0)

        spread = (macd - signal_line) / candles[idx]["close"] * 10000 if candles[idx]["close"] else 0.0
        score = max(-100.0, min(100.0, spread * 5))
        return Signal(action="WAIT", score=score)

    def default_params(self) -> Dict[str, Any]:
        return {"entry_threshold": 25}

    def param_grid(self) -> Dict[str, List[Any]]:
        return {"entry_threshold": [20, 25, 30]}
