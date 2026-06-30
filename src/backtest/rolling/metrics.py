# -*- coding: utf-8 -*-
"""
Backtest metrics computation — Sharpe, Sortino, Calmar, Monte Carlo.

Fixes the broken Sharpe annualization from the old code and adds
Sortino (downside-only risk), Calmar (return / max-drawdown), and
Monte Carlo 95% confidence interval via trade-sequence shuffling.
"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Optional

from backtest.rolling.models import BacktestResult, Trade


# ---------------------------------------------------------------------------
# Annual factors by K-line period (sqrt of candles per year)
# ---------------------------------------------------------------------------
_ANNUAL_FACTOR = {
    "15min": math.sqrt(365 * 24 * 4),    # ~187.1
    "1hour": math.sqrt(365 * 24),         # ~93.6
    "4hour": math.sqrt(365 * 6),          # ~46.8
    "1day": math.sqrt(365),               # ~19.1
}


def _get_annual_factor(kline_type: str) -> float:
    return _ANNUAL_FACTOR.get(kline_type, math.sqrt(252))


# ---------------------------------------------------------------------------
# Core metric functions
# ---------------------------------------------------------------------------

def compute_sharpe(pnls: List[float], kline_type: str = "1hour") -> float:
    """Annualized Sharpe ratio using proper period-based annualization."""
    if len(pnls) < 2:
        return 0.0
    mean_r = sum(pnls) / len(pnls)
    var_r = sum((p - mean_r) ** 2 for p in pnls) / (len(pnls) - 1)
    std_r = math.sqrt(var_r) if var_r > 0 else 0.0
    if std_r == 0:
        return 0.0
    return (mean_r / std_r) * _get_annual_factor(kline_type)


def compute_sortino(pnls: List[float], kline_type: str = "1hour") -> float:
    """Annualized Sortino ratio — penalizes only downside deviation."""
    if len(pnls) < 2:
        return 0.0
    mean_r = sum(pnls) / len(pnls)
    downside = [min(p, 0) ** 2 for p in pnls]
    downside_dev = math.sqrt(sum(downside) / len(pnls))
    if downside_dev == 0:
        return 0.0
    return (mean_r / downside_dev) * _get_annual_factor(kline_type)


def compute_calmar(total_return_pct: float, max_drawdown_pct: float) -> float:
    """Calmar ratio = total return / max drawdown."""
    if max_drawdown_pct == 0:
        return 0.0
    return total_return_pct / max_drawdown_pct


def compute_monte_carlo_95(
    pnls: List[float],
    n_simulations: int = 1000,
    seed: int = 42,
) -> Optional[float]:
    """Monte Carlo simulation: shuffle trade sequence, return 95th percentile worst total return.

    This tests how fragile the equity curve is to trade ordering.
    """
    if len(pnls) < 5:
        return None
    rng = random.Random(seed)
    final_returns = []
    for _ in range(n_simulations):
        shuffled = pnls[:]
        rng.shuffle(shuffled)
        equity = 100.0
        for p in shuffled:
            equity *= (1 + p / 100)
        final_returns.append(equity - 100.0)
    final_returns.sort()
    idx_5pct = max(0, int(len(final_returns) * 0.05))
    return round(final_returns[idx_5pct], 2)


def compute_profit_factor(trades: List[Trade]) -> float:
    gross_profit = sum(t.pnl_pct for t in trades if t.pnl_pct > 0)
    gross_loss = abs(sum(t.pnl_pct for t in trades if t.pnl_pct <= 0))
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


# ---------------------------------------------------------------------------
# Aggregate: compute all metrics from trades + equity curve
# ---------------------------------------------------------------------------

def compute_metrics(
    trades: List[Trade],
    equity_curve: List[Dict],
    candles: List[Dict],
    symbol: str,
    kline_type: str,
    strategy_name: str = "",
) -> BacktestResult:
    """Compute all backtest metrics from trade list + equity curve.

    This replaces the old compute_metrics in backtest_service.py with:
    - Correct Sharpe annualization
    - Sortino ratio
    - Calmar ratio
    - Monte Carlo 95% CI
    - Average bars held
    """
    winning = [t for t in trades if t.pnl_pct > 0]
    losing = [t for t in trades if t.pnl_pct <= 0]
    pnls = [t.pnl_pct for t in trades]

    total_return = 0.0
    if equity_curve:
        total_return = equity_curve[-1]["equity"] - 100.0

    max_dd = max((e["drawdown"] for e in equity_curve), default=0.0)

    avg_pnl = sum(pnls) / len(pnls) if pnls else 0.0
    best = max(pnls) if pnls else 0.0
    worst = min(pnls) if pnls else 0.0

    avg_bars = 0.0
    if trades:
        avg_bars = sum(t.bars_held for t in trades) / len(trades)

    sharpe = compute_sharpe(pnls, kline_type)
    sortino = compute_sortino(pnls, kline_type)
    calmar = compute_calmar(total_return, max_dd)
    mc_95 = compute_monte_carlo_95(pnls)
    pf = compute_profit_factor(trades)

    trade_dicts = [t.to_dict() for t in trades]

    return BacktestResult(
        symbol=symbol,
        kline_type=kline_type,
        strategy=strategy_name,
        total_candles=len(candles),
        total_trades=len(trades),
        winning_trades=len(winning),
        losing_trades=len(losing),
        win_rate=round(len(winning) / len(trades) * 100, 1) if trades else 0,
        total_return_pct=round(total_return, 2),
        max_drawdown_pct=round(max_dd, 2),
        sharpe_ratio=round(sharpe, 2),
        sortino_ratio=round(sortino, 2),
        calmar_ratio=round(calmar, 2),
        avg_trade_pct=round(avg_pnl, 2),
        best_trade_pct=round(best, 2),
        worst_trade_pct=round(worst, 2),
        profit_factor=round(min(pf, 999.99), 2),
        avg_bars_held=round(avg_bars, 1),
        monte_carlo_95=mc_95,
        equity_curve=equity_curve,
        trades=trade_dicts,
    )
