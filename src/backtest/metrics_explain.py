"""Explain backtest metrics across strategies (chapter 19 teaching helper)."""

from __future__ import annotations

from typing import Any

from backtest.rolling.service import compare_strategies


def explain_metrics(
    *,
    symbol: str | None = None,
    limit: int = 120,
    stop_loss_pct: float = 3.0,
    take_profit_pct: float = 5.0,
) -> dict[str, Any]:
    """Contrast return vs drawdown profiles instead of ranking by return alone."""
    payload = compare_strategies(
        symbol=symbol,
        limit=limit,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
    )
    rows = payload["strategies"]
    by_return = sorted(rows, key=lambda item: item["total_return_pct"], reverse=True)
    by_drawdown = sorted(rows, key=lambda item: item["max_drawdown_pct"])

    highest_return = by_return[0]
    lowest_drawdown = by_drawdown[0]
    same_leader = highest_return["strategy_key"] == lowest_drawdown["strategy_key"]

    pairs: list[dict[str, Any]] = []
    for row in rows:
        pairs.append(
            {
                "strategy_key": row["strategy_key"],
                "strategy": row["strategy"],
                "total_return_pct": row["total_return_pct"],
                "max_drawdown_pct": row["max_drawdown_pct"],
                "sharpe_ratio": row["sharpe_ratio"],
                "calmar_ratio": row["calmar_ratio"],
                "win_rate": row["win_rate"],
                "total_trades": row["total_trades"],
                "return_rank": by_return.index(row) + 1,
                "drawdown_rank": by_drawdown.index(row) + 1,
            }
        )

    guidance: list[str] = [
        "不要只用 total_return_pct 选策略；必须同时看 max_drawdown_pct 与 Sharpe/Calmar。",
        "交易次数过少时，Sharpe/Calmar 可能失真，应回到 trades 明细核对。",
    ]
    if not same_leader:
        guidance.append(
            f"本样本中收益最高的是 {highest_return['strategy']}，"
            f"但回撤最低的是 {lowest_drawdown['strategy']} — 需要人工权衡。"
        )
    else:
        guidance.append(
            f"本样本中 {highest_return['strategy']} 同时领先收益与回撤，"
            "仍应做窗口稳定性检查（第 21 讲）。"
        )

    return {
        "ok": True,
        "engine": payload["engine"],
        "symbol": payload["symbol"],
        "kline_type": payload["kline_type"],
        "total_candles": payload["total_candles"],
        "strategies": pairs,
        "highest_return": highest_return["strategy_key"],
        "lowest_drawdown": lowest_drawdown["strategy_key"],
        "same_leader": same_leader,
        "guidance": guidance,
        "assumptions": payload["assumptions"],
    }
