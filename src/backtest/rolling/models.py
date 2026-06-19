# -*- coding: utf-8 -*-
"""
Data models for the backtest engine.

Analogous to Claude Code's src/models.py — frozen dataclasses for all
domain types used throughout the backtest system.  Immutable where possible
to guarantee snapshot-safe state across engine iterations.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


# ---------------------------------------------------------------------------
# Signal — output of a Strategy.generate_signal() call
# ---------------------------------------------------------------------------
class Action(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    WEAK_LONG = "WEAK_LONG"
    WEAK_SHORT = "WEAK_SHORT"
    WAIT = "WAIT"


@dataclass(frozen=True)
class Signal:
    """Immutable trading signal produced by a strategy at a single candle."""
    action: str      # Action enum value
    score: float     # [-100, 100] signal strength


# ---------------------------------------------------------------------------
# Trade — a completed (or in-flight) position entry/exit pair
# ---------------------------------------------------------------------------
@dataclass
class Trade:
    entry_idx: int
    entry_price: float
    entry_ts: int
    direction: str               # "LONG" or "SHORT"
    exit_idx: int = 0
    exit_price: float = 0.0
    exit_ts: int = 0
    pnl_pct: float = 0.0
    exit_reason: str = ""
    peak_price: float = 0.0      # for trailing stop tracking
    bars_held: int = 0           # for time stop tracking

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entryIdx": self.entry_idx,
            "entryTs": self.entry_ts,
            "entryPrice": round(self.entry_price, 6),
            "direction": self.direction,
            "exitIdx": self.exit_idx,
            "exitTs": self.exit_ts,
            "exitPrice": round(self.exit_price, 6),
            "pnlPct": round(self.pnl_pct, 2),
            "exitReason": self.exit_reason,
            "barsHeld": self.bars_held,
        }


# ---------------------------------------------------------------------------
# BacktestConfig — engine configuration (immutable)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BacktestConfig:
    """All knobs for a single backtest run, frozen at creation time."""
    min_context: int = 60
    stop_loss_pct: float = 3.0
    take_profit_pct: float = 5.0
    trailing_stop_pct: float = 0.0       # 0 = disabled
    max_hold_bars: int = 0               # 0 = disabled (time stop)
    commission_pct: float = 0.1
    slippage_pct: float = 0.0            # simulated slippage (fixed %)
    dynamic_slippage: bool = False        # Phase 2.4: volume-based slippage
    dynamic_slippage_factor: float = 0.5  # multiplier for volume-impact model
    funding_rate_pct: float = 0.0         # 8h funding rate for perps
    start_from: int = 0                  # OOS start for walk-forward
    kline_type: str = "1hour"            # for Sharpe annualization


# ---------------------------------------------------------------------------
# BacktestResult — final output from the engine
# ---------------------------------------------------------------------------
@dataclass
class BacktestResult:
    symbol: str
    kline_type: str
    strategy: str
    total_candles: int
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    avg_trade_pct: float = 0.0
    best_trade_pct: float = 0.0
    worst_trade_pct: float = 0.0
    profit_factor: float = 0.0
    avg_bars_held: float = 0.0
    monte_carlo_95: Optional[float] = None   # 95th percentile worst return
    equity_curve: List[Dict[str, Any]] = field(default_factory=list)
    trades: List[Dict[str, Any]] = field(default_factory=list)
    candle_signals: List[Dict[str, Any]] = field(default_factory=list)
    walk_forward: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Engine events — yielded by the async generator engine (like Claude Code's
# StreamEvent from query.ts)
# ---------------------------------------------------------------------------
class EventType(str, Enum):
    ENGINE_START = "engine_start"
    CANDLE_PROCESSED = "candle_processed"
    TRADE_OPENED = "trade_opened"
    TRADE_CLOSED = "trade_closed"
    HOOK_FIRED = "hook_fired"
    COMPACT = "compact"            # skipped candle for OOS boundary
    ENGINE_DONE = "engine_done"


@dataclass(frozen=True)
class EngineEvent:
    """Immutable progress event yielded by the backtest engine generator."""
    type: EventType
    idx: int = 0
    data: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# WalkForwardResult — output from optimization
# ---------------------------------------------------------------------------
@dataclass
class WalkForwardResult:
    best_params: Dict[str, Any]
    in_sample_sharpe: float
    out_of_sample_sharpe: float
    out_of_sample_return: float
    num_windows: int
    window_results: List[Dict[str, Any]]
    num_trials: int = 0
