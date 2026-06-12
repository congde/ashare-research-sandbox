# -*- coding: utf-8 -*-
"""Ensemble Strategy — multi-strategy weighted voting.

Inspired by Claude Code's coordinator pattern — multiple agents (strategies)
work in parallel and their signals are aggregated by a coordinator.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from backtest.models import Signal
from backtest.indicators import IndicatorSeries
from backtest.strategies.base import Strategy


class EnsembleStrategy(Strategy):
    """Weighted ensemble of multiple strategies."""

    name = "ensemble"
    display_name = "策略组合"

    def __init__(self, strategies: Optional[List[Strategy]] = None, weights: Optional[List[float]] = None):
        self._strategies = strategies or []
        self._weights = weights or []

    def prepare(self, candles: List[Dict], params: Dict[str, Any]) -> None:
        """Prepare all sub-strategies."""
        if not self._strategies:
            self._init_default_ensemble()
        for s in self._strategies:
            s.prepare(candles, params)

    def _init_default_ensemble(self):
        """Lazily initialize default ensemble members."""
        from backtest.strategies.technical_signal import TechnicalSignalStrategy
        from backtest.strategies.rsi_mean_reversion import RSIMeanReversionStrategy
        from backtest.strategies.macd import MACDStrategy

        self._strategies = [
            TechnicalSignalStrategy(),
            RSIMeanReversionStrategy(),
            MACDStrategy(),
        ]
        self._weights = [0.4, 0.3, 0.3]

    def generate_signal(
        self,
        candles: List[Dict],
        idx: int,
        params: Dict[str, Any],
        indicators: Optional[IndicatorSeries] = None,
    ) -> Signal:
        if not self._strategies:
            self._init_default_ensemble()

        total_score = 0.0
        total_weight = 0.0

        for strategy, weight in zip(self._strategies, self._weights):
            sig = strategy.generate_signal(candles, idx, params, indicators)
            total_score += sig.score * weight
            total_weight += weight

        if total_weight > 0:
            score = total_score / total_weight
        else:
            score = 0.0

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
        return {"entry_threshold": 25}

    def param_grid(self) -> Dict[str, List[Any]]:
        return {"entry_threshold": [20, 25, 30]}
