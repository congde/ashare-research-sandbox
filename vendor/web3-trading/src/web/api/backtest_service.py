# -*- coding: utf-8 -*-
"""
Backtest service — thin backward-compatibility wrapper.

The modular implementation lives under src/backtest/.
This module preserves the old import surface used by web routes.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from backtest.engine import execute_backtest
from backtest.engine import run_backtest as _run_backtest
from backtest.metrics import compute_metrics
from backtest.models import BacktestConfig, BacktestResult, Signal, Trade, WalkForwardResult
from backtest.optimization.walk_forward import walk_forward_optimize
from backtest.registry import get_strategy, list_strategies
from backtest.strategies.base import Strategy
from web.api.dashboard_service import analyze_candles, kucoin_get, normalize_candle

logger = logging.getLogger(__name__)


def run_backtest_with_strategy(
    candles: List[Dict],
    strategy: Strategy,
    params: Dict[str, Any],
    *,
    min_context: int = 60,
    stop_loss_pct: float = 3.0,
    take_profit_pct: float = 5.0,
    commission_pct: float = 0.1,
    start_from: int = 0,
    kline_type: str = "1hour",
) -> Tuple[List[Trade], List[Dict], List[Dict]]:
    """Legacy adapter to the new engine.run_backtest API."""
    config = BacktestConfig(
        min_context=min_context,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        commission_pct=commission_pct,
        start_from=start_from,
        kline_type=kline_type,
    )
    return _run_backtest(candles, strategy, params, config)


def run_backtest(
    candles: List[Dict],
    *,
    min_context: int = 60,
    entry_threshold: float = 25.0,
    exit_threshold: float = 0.0,
    stop_loss_pct: float = 3.0,
    take_profit_pct: float = 5.0,
    commission_pct: float = 0.1,
    kline_type: str = "1hour",
) -> Tuple[List[Trade], List[Dict], List[Dict]]:
    """Legacy adapter for the original technical signal backtest."""
    strategy = get_strategy("technical_signal")
    params = dict(strategy.default_params())
    params["entry_threshold"] = entry_threshold
    params["exit_threshold"] = exit_threshold
    config = BacktestConfig(
        min_context=min_context,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        commission_pct=commission_pct,
        kline_type=kline_type,
    )
    return _run_backtest(candles, strategy, params, config)
