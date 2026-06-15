# -*- coding: utf-8 -*-
"""
Strategy base class — analogous to Claude Code's Tool interface (src/Tool.ts).

Each strategy is a self-contained unit with:
  - name / display_name metadata
  - generate_signal(candles, idx, params, indicators) → Signal
  - default_params() → Dict
  - param_grid() → Dict[str, List] for optimization
  - Optional prepare() hook for batch pre-computation

Strategies receive the pre-computed IndicatorSeries for O(1) lookups
instead of recomputing indicators per candle.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from backtest.rolling.models import Signal
from backtest.rolling.indicators import IndicatorSeries


class Strategy(ABC):
    """Abstract base class for all backtest strategies."""

    name: str = "base"
    display_name: str = "Base Strategy"

    @abstractmethod
    def generate_signal(
        self,
        candles: List[Dict],
        idx: int,
        params: Dict[str, Any],
        indicators: Optional[IndicatorSeries] = None,
    ) -> Signal:
        """Generate a trading signal for candle at `idx`.

        Args:
            candles: full candle list (only [:idx+1] should be used)
            idx: current candle index
            params: strategy-specific parameters
            indicators: pre-computed indicator series (O(1) lookup)

        Returns:
            Signal with action and score.
        """
        ...

    @abstractmethod
    def default_params(self) -> Dict[str, Any]:
        """Default parameter dict for this strategy."""
        ...

    def param_grid(self) -> Dict[str, List[Any]]:
        """Parameter search space for walk-forward optimization."""
        return {}

    def prepare(self, candles: List[Dict], params: Dict[str, Any]) -> None:
        """Optional hook called once before the backtest loop.

        Use for batch pre-computation (e.g., foundation model predictions).
        """
        pass

    def is_incremental(self) -> bool:
        """Whether this strategy uses only pre-computed indicators (O(1) per candle).

        If True, the engine passes IndicatorSeries; if False, the strategy
        may do its own computation.
        """
        return True
