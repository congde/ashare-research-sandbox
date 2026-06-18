# -*- coding: utf-8 -*-
"""MA crossover — rules adapted from vendor/Qbot (MIT).

Reference: vendor/Qbot/qbot/strategies/sma_cross_strategy_bt.py
  - Golden cross (fast SMA crosses above slow SMA) → enter long
  - Death cross (fast crosses below slow) → exit long (no short entry)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backtest.rolling.indicators import IndicatorSeries
from backtest.rolling.models import Signal
from backtest.rolling.strategies.base import Strategy


def _sma(values: list[float], period: int) -> float:
    window = values[-period:]
    return sum(window) / period


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
        fast_ma = _sma(closes, fast_period)
        slow_ma = _sma(closes, slow_period)

        prev_closes = [float(candles[i]["close"]) for i in range(idx - slow_period - 1, idx)]
        prev_fast = _sma(prev_closes, fast_period)
        prev_slow = _sma(prev_closes, slow_period)

        crossed_up = prev_fast <= prev_slow and fast_ma > slow_ma
        crossed_down = prev_fast >= prev_slow and fast_ma < slow_ma

        if crossed_up:
            return Signal(action="LONG", score=50.0)
        if crossed_down:
            # Negative score closes an open long; WAIT avoids opening a short leg.
            return Signal(action="WAIT", score=-50.0)

        separation = (fast_ma - slow_ma) / slow_ma * 100 if slow_ma else 0.0
        score = max(-100.0, min(100.0, separation * 10))
        return Signal(action="WAIT", score=score)

    def default_params(self) -> Dict[str, Any]:
        return {"fast_period": 10, "slow_period": 30, "entry_threshold": 25}

    def param_grid(self) -> Dict[str, List[Any]]:
        return {
            "fast_period": [5, 7, 10, 14],
            "slow_period": [20, 30, 50],
            "entry_threshold": [20, 25, 30],
        }

    def is_incremental(self) -> bool:
        return False
