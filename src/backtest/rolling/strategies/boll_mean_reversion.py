# -*- coding: utf-8 -*-
"""Bollinger mean reversion — rules adapted from vendor/Qbot (MIT).

Reference: vendor/Qbot/qbot/strategies/boll_strategy_bt.py
  - Flat + close below lower band → buy (long)
  - In position + close above upper band → sell (exit long)
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from backtest.rolling.indicators import IndicatorSeries
from backtest.rolling.models import Signal
from backtest.rolling.strategies.base import Strategy


def _bollinger_at(
    closes: list[float],
    period: int,
    num_std: float,
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    if len(closes) < period:
        return None, None, None
    window = closes[-period:]
    mid = sum(window) / period
    variance = sum((value - mid) ** 2 for value in window) / period
    std = math.sqrt(variance)
    upper = mid + num_std * std
    lower = mid - num_std * std
    return upper, mid, lower


class BollMeanReversionStrategy(Strategy):
    name = "boll_mean_reversion"
    display_name = "布林带均值回归（Qbot）"

    def generate_signal(
        self,
        candles: List[Dict],
        idx: int,
        params: Dict[str, Any],
        indicators: Optional[IndicatorSeries] = None,
    ) -> Signal:
        period = int(params.get("bb_period", 13))
        num_std = float(params.get("bb_std", 2.0))

        if idx < period - 1:
            return Signal(action="WAIT", score=0.0)

        closes = [float(candles[i]["close"]) for i in range(idx - period + 1, idx + 1)]
        close = closes[-1]
        upper, _mid, lower = _bollinger_at(closes, period, num_std)

        if upper is None or lower is None:
            return Signal(action="WAIT", score=0.0)

        if close < lower:
            depth = (lower - close) / lower * 100 if lower else 0.0
            return Signal(action="LONG", score=min(100.0, 40.0 + depth * 5))
        if close > upper:
            depth = (close - upper) / upper * 100 if upper else 0.0
            return Signal(action="WAIT", score=-min(100.0, 40.0 + depth * 5))

        pct_b = (close - lower) / (upper - lower) * 100 if upper > lower else 50.0
        score = (50.0 - pct_b) * 0.4
        return Signal(action="WAIT", score=max(-100.0, min(100.0, score)))

    def default_params(self) -> Dict[str, Any]:
        return {"bb_period": 13, "bb_std": 2.0, "entry_threshold": 25}

    def param_grid(self) -> Dict[str, List[Any]]:
        return {
            "bb_period": [10, 13, 20],
            "bb_std": [1.5, 2.0, 2.5],
            "entry_threshold": [20, 25, 30],
        }

    def is_incremental(self) -> bool:
        return False
