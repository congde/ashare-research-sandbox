# -*- coding: utf-8 -*-
"""专业量化绩效指标。"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass


@dataclass
class PerformanceMetrics:
    total_return: float = 0.0
    total_return_pct: str = "0.00%"
    total_pnl: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: str = "0.00%"
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    avg_trade_pnl: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    trading_days: int = 0
    annualized_return: float = 0.0

    @property
    def largest_win(self) -> float:
        return self.best_trade

    @property
    def largest_loss(self) -> float:
        return self.worst_trade


def compute_metrics(
    equity_curve: list[dict],
    trade_history: list[dict],
    initial_cash: float = 100000.0,
    periods_per_year: float = 252.0,
) -> PerformanceMetrics:
    """Compute comprehensive performance metrics."""
    m = PerformanceMetrics()
    if not equity_curve:
        return m

    equities = [float(e["equity"]) for e in equity_curve if e.get("equity") is not None]
    if not equities:
        return m

    final_equity = equities[-1]
    m.total_return = (final_equity - initial_cash) / initial_cash if initial_cash > 0 else 0
    m.total_return_pct = f"{m.total_return:.2%}"
    m.trading_days = len(equities)

    if m.trading_days > 1:
        m.annualized_return = (1 + m.total_return) ** (periods_per_year / m.trading_days) - 1

    returns = []
    for i in range(1, len(equities)):
        if equities[i - 1] > 0:
            returns.append((equities[i] - equities[i - 1]) / equities[i - 1])

    if returns:
        avg_r = sum(returns) / len(returns)
        if len(returns) > 1:
            std_r = (sum((r - avg_r) ** 2 for r in returns) / (len(returns) - 1)) ** 0.5
            m.sharpe_ratio = round((avg_r / std_r) * (periods_per_year ** 0.5), 3) if std_r > 0 else 0
        neg_returns = [r for r in returns if r < 0]
        if len(neg_returns) > 1:
            downside_dev = (sum(r ** 2 for r in neg_returns) / (len(neg_returns) - 1)) ** 0.5
            m.sortino_ratio = round((avg_r / downside_dev) * (periods_per_year ** 0.5), 3) if downside_dev > 0 else 0

    peak = equities[0]
    max_dd = 0.0
    for eq in equities:
        peak = max(peak, eq)
        dd = (peak - eq) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)
    m.max_drawdown = round(max_dd, 4)
    m.max_drawdown_pct = f"{max_dd:.2%}"

    if max_dd > 0 and m.annualized_return != 0:
        m.calmar_ratio = round(m.annualized_return / max_dd, 3)

    pnls = [float(t.get("pnl", 0)) for t in trade_history if "pnl" in t]
    m.total_trades = len(pnls)
    m.total_pnl = round(sum(pnls), 2)

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    m.winning_trades = len(wins)
    m.losing_trades = len(losses)
    m.win_rate = round(len(wins) / len(pnls), 4) if pnls else 0
    m.avg_win = round(sum(wins) / len(wins), 2) if wins else 0
    m.avg_loss = round(sum(losses) / len(losses), 2) if losses else 0
    m.avg_trade_pnl = round(sum(pnls) / len(pnls), 2) if pnls else 0

    total_wins = sum(wins) if wins else 0
    total_losses = abs(sum(losses)) if losses else 0
    m.profit_factor = round(total_wins / total_losses, 2) if total_losses > 0 else float("inf") if total_wins > 0 else 0

    m.best_trade = round(max(pnls), 2) if pnls else 0
    m.worst_trade = round(min(pnls), 2) if pnls else 0

    streak = 0
    for p in pnls:
        if p > 0:
            streak = streak + 1 if streak > 0 else 1
            m.max_consecutive_wins = max(m.max_consecutive_wins, streak)
        else:
            streak = streak - 1 if streak < 0 else -1
            m.max_consecutive_losses = max(m.max_consecutive_losses, abs(streak))

    return m


def metrics_to_dict(m: PerformanceMetrics) -> dict:
    """Serialize metrics into JSON-safe values."""
    data = asdict(m)
    for key, value in list(data.items()):
        if isinstance(value, float) and not math.isfinite(value):
            data[key] = None
    data["largest_win"] = m.largest_win
    data["largest_loss"] = m.largest_loss
    return data


def format_metrics_report(m: PerformanceMetrics) -> str:
    lines = [
        "=" * 50,
        "        Performance Report",
        "=" * 50,
        f"  Total Return:          {m.total_return_pct}",
        f"  Total PnL:             ${m.total_pnl:,.2f}",
        f"  Annualized Return:     {m.annualized_return:.2%}",
        "",
        f"  Sharpe Ratio:          {m.sharpe_ratio:.3f}",
        f"  Sortino Ratio:         {m.sortino_ratio:.3f}",
        f"  Calmar Ratio:          {m.calmar_ratio:.3f}",
        f"  Max Drawdown:          {m.max_drawdown_pct}",
        "",
        f"  Total Trades:          {m.total_trades}",
        f"  Win Rate:              {m.win_rate:.1%}",
        f"  Profit Factor:         {m.profit_factor}",
        f"  Avg Trade PnL:         ${m.avg_trade_pnl:,.2f}",
        f"  Avg Win:               ${m.avg_win:,.2f}",
        f"  Avg Loss:              ${m.avg_loss:,.2f}",
        f"  Best Trade:            ${m.best_trade:,.2f}",
        f"  Worst Trade:           ${m.worst_trade:,.2f}",
        "",
        f"  Max Consecutive Wins:  {m.max_consecutive_wins}",
        f"  Max Consecutive Losses:{m.max_consecutive_losses}",
        f"  Trading Periods:       {m.trading_days}",
        "=" * 50,
    ]
    return "\n".join(lines)
