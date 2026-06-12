# -*- coding: utf-8 -*-
"""
Backtest Engine — modular strategy backtesting framework.

Architecture inspired by Claude Code's agent harness patterns:
  - Async generator driven engine (like Agent Loop's queryLoop)
  - Strategy as Tool pattern (pluggable with schema validation)
  - Registry pattern for strategy discovery and assembly
  - Hook lifecycle for extensibility (pre/post trade, compact, etc.)
  - Streaming execution with progress events

Public API:
  from backtest import execute_backtest, BacktestResult, list_strategies, get_strategy
"""

from backtest.models import (
    Signal,
    Trade,
    BacktestResult,
    BacktestConfig,
    EngineEvent,
)
from backtest.registry import (
    get_strategy,
    list_strategies,
    STRATEGY_REGISTRY,
)
from backtest.engine import run_backtest, execute_backtest

__all__ = [
    "Signal",
    "Trade",
    "BacktestResult",
    "BacktestConfig",
    "EngineEvent",
    "get_strategy",
    "list_strategies",
    "STRATEGY_REGISTRY",
    "run_backtest",
    "execute_backtest",
]
