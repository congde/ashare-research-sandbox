# -*- coding: utf-8 -*-
"""MA crossover — rules adapted from vendor/Qbot (MIT).

Reference: vendor/Qbot/qbot/strategies/sma_cross_strategy_bt.py
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backtest.rolling.indicators import IndicatorSeries
from backtest.rolling.models import Signal
from backtest.rolling.strategies.base import Strategy
from backtest.rolling.strategies.qbot_rules import (
    crossed_down,
    crossed_up,
    long_only_cross_signal,
    separation_score,
    sma_at,
)


class MACrossoverStrategy(Strategy):
    name = "ma_crossover"
    display_name = "均线交叉策略（Qbot 双均线）"

    def generate_signal(
        self,
        candles: List[Dict],
        idx: int,
        params: Dict[str, Any],
        indicators: Optional[IndicatorSeries] = None,
    ) -> Signal:
        fast_period = int(params.get("fast_period", 10))
        slow_period = int(params.get("slow_period", 30))

        if idx < slow_period:
            return Signal(action="WAIT", score=0.0)

        closes = [float(candles[i]["close"]) for i in range(idx - slow_period, idx + 1)]
        fast_ma = sma_at(closes, fast_period)
        slow_ma = sma_at(closes, slow_period)

        prev_closes = [float(candles[i]["close"]) for i in range(idx - slow_period, idx)]
        prev_fast = sma_at(prev_closes, fast_period)
        prev_slow = sma_at(prev_closes, slow_period)

        cross_signal = long_only_cross_signal(
            crossed_up_flag=crossed_up(prev_fast, prev_slow, fast_ma, slow_ma),
            crossed_down_flag=crossed_down(prev_fast, prev_slow, fast_ma, slow_ma),
        )
        if cross_signal is not None:
            return cross_signal

        return Signal(
            action="WAIT",
            score=separation_score(fast_ma - slow_ma, slow_ma),
        )

    def default_params(self) -> Dict[str, Any]:
        return {"fast_period": 10, "slow_period": 20, "entry_threshold": 25}

    def param_grid(self) -> Dict[str, List[Any]]:
        return {
            "fast_period": [5, 7, 10, 14],
            "slow_period": [20, 30, 50],
            "entry_threshold": [20, 25, 30],
        }

    def is_incremental(self) -> bool:
        return False
