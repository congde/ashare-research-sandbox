# -*- coding: utf-8 -*-
"""MA Crossover Strategy — dual moving average crossover."""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from backtest.models import Signal
from backtest.indicators import IndicatorSeries
from backtest.strategies.base import Strategy


class MACrossoverStrategy(Strategy):
    name = "ma_crossover"
    display_name = "均线交叉策略"

    def generate_signal(
        self,
        candles: List[Dict],
        idx: int,
        params: Dict[str, Any],
        indicators: Optional[IndicatorSeries] = None,
    ) -> Signal:
        fast_period = params.get("fast_period", 10)
        slow_period = params.get("slow_period", 30)

        if idx < slow_period + 1:
            return Signal(action="WAIT", score=0)

        closes = [candles[i]["close"] for i in range(idx - slow_period, idx + 1)]
        fast_ma = sum(closes[-fast_period:]) / fast_period
        slow_ma = sum(closes) / slow_period

        prev_closes = [candles[i]["close"] for i in range(idx - slow_period - 1, idx)]
        prev_fast = sum(prev_closes[-fast_period:]) / fast_period
        prev_slow = sum(prev_closes) / slow_period

        separation = (fast_ma - slow_ma) / slow_ma * 100
        score = max(-100, min(100, separation * 20))

        crossed_up = prev_fast <= prev_slow and fast_ma > slow_ma
        crossed_down = prev_fast >= prev_slow and fast_ma < slow_ma

        if crossed_up:
            score = max(score, 30)
        elif crossed_down:
            score = min(score, -30)

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
        return {"fast_period": 10, "slow_period": 30, "entry_threshold": 25}

    def param_grid(self) -> Dict[str, List[Any]]:
        return {
            "fast_period": [5, 7, 10, 14],
            "slow_period": [20, 30, 50],
            "entry_threshold": [20, 25, 30],
        }

    def is_incremental(self) -> bool:
        return False  # uses raw candle access
