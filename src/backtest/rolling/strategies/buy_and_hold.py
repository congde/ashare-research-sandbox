# -*- coding: utf-8 -*-
"""Buy-and-Hold baseline strategy for benchmark comparison."""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from backtest.rolling.models import Signal
from backtest.rolling.indicators import IndicatorSeries
from backtest.rolling.strategies.base import Strategy


class BuyAndHoldStrategy(Strategy):
    name = "buy_and_hold"
    display_name = "买入持有基准"

    def generate_signal(
        self,
        candles: List[Dict],
        idx: int,
        params: Dict[str, Any],
        indicators: Optional[IndicatorSeries] = None,
    ) -> Signal:
        return Signal(action="LONG", score=100)

    def default_params(self) -> Dict[str, Any]:
        return {"entry_threshold": 0}

    def param_grid(self) -> Dict[str, List[Any]]:
        return {}
