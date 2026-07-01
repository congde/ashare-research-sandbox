"""Project-level backtest diagnostics layered on top of the upstream engine."""

from __future__ import annotations

import math
from typing import Any

from backtest.rolling.models import Trade


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return ordered[int(pos)]
    weight = pos - lo
    return ordered[lo] * (1 - weight) + ordered[hi] * weight


def _max_streak(pnls: list[float], *, winning: bool) -> int:
    best = 0
    current = 0
    for pnl in pnls:
        hit = pnl > 0 if winning else pnl <= 0
        if hit:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def _benchmark_return(candles: list[dict[str, Any]]) -> float:
    if len(candles) < 2:
        return 0.0
    start = float(candles[0].get("close") or 0)
    end = float(candles[-1].get("close") or 0)
    if start <= 0:
        return 0.0
    return (end / start - 1.0) * 100


def _omega_ratio(pnls: list[float], threshold: float = 0.0) -> float:
    gains = sum(max(0.0, pnl - threshold) for pnl in pnls)
    losses = sum(max(0.0, threshold - pnl) for pnl in pnls)
    if losses == 0:
        return 999.99 if gains > 0 else 0.0
    return gains / losses


def compute_trade_diagnostics(
    *,
    trades: list[Trade],
    candles: list[dict[str, Any]],
    total_return_pct: float,
    max_drawdown_pct: float,
) -> dict[str, Any]:
    pnls = [trade.pnl_pct for trade in trades]
    winning = [trade for trade in trades if trade.pnl_pct > 0]
    losing = [trade for trade in trades if trade.pnl_pct <= 0]
    avg_win = sum(trade.pnl_pct for trade in winning) / len(winning) if winning else 0.0
    avg_loss = sum(trade.pnl_pct for trade in losing) / len(losing) if losing else 0.0
    payoff = avg_win / abs(avg_loss) if avg_loss else (999.99 if avg_win > 0 else 0.0)
    win_prob = len(winning) / len(trades) if trades else 0.0
    expectancy = win_prob * avg_win + (1.0 - win_prob) * avg_loss if trades else 0.0
    benchmark = _benchmark_return(candles)
    held_bars = sum(max(0, trade.bars_held) for trade in trades)
    positive = [pnl for pnl in pnls if pnl > 0]
    negative = [abs(pnl) for pnl in pnls if pnl < 0]
    tail_ratio = 0.0
    if positive and negative:
        tail_ratio = _percentile(positive, 0.95) / max(1e-9, _percentile(negative, 0.95))
    recovery = total_return_pct / max_drawdown_pct if max_drawdown_pct else 0.0

    return {
        "avg_win_pct": round(avg_win, 2),
        "avg_loss_pct": round(avg_loss, 2),
        "payoff_ratio": round(min(payoff, 999.99), 2),
        "expectancy_pct": round(expectancy, 2),
        "exposure_pct": round(min(100.0, held_bars / len(candles) * 100), 1) if candles else 0.0,
        "benchmark_return_pct": round(benchmark, 2),
        "alpha_pct": round(total_return_pct - benchmark, 2),
        "recovery_factor": round(recovery, 2),
        "tail_ratio": round(tail_ratio, 2),
        "omega_ratio": round(min(_omega_ratio(pnls), 999.99), 2),
        "max_consecutive_wins": _max_streak(pnls, winning=True),
        "max_consecutive_losses": _max_streak(pnls, winning=False),
    }
