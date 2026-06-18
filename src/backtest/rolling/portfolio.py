# -*- coding: utf-8 -*-
"""Equal-weight multi-leg portfolio backtest for teaching (chapter 22)."""

from __future__ import annotations

import math
from typing import Any

from backtest.runner import load_prices
from backtest.rolling.engine import run_backtest
from backtest.rolling.metrics import compute_metrics
from backtest.rolling.models import BacktestConfig
from backtest.rolling.registry import get_strategy
from backtest.rolling.service import MIN_CONTEXT, _prices_to_candles
from paths import DATA_DIR


def _leg_candles_from_closes(
    price_rows: list[Any],
    *,
    leg_id: str,
    lag: int = 0,
    scale_drift: float = 0.0,
) -> list[dict[str, Any]]:
    from backtest.runner import Price

    closes = [row.close for row in price_rows]
    adjusted: list[float] = []
    for idx, _close in enumerate(closes):
        base = closes[max(0, idx - lag)] if lag else closes[idx]
        adjusted.append(base * (1.0 + scale_drift * idx))
    prices = [Price(source.date, value) for source, value in zip(price_rows, adjusted)]
    candles = _prices_to_candles(prices)
    for row in candles:
        row["symbol"] = leg_id
    return candles


def _daily_returns(equity_curve: list[dict[str, Any]]) -> list[float]:
    if len(equity_curve) < 2:
        return []
    out: list[float] = []
    for prev, curr in zip(equity_curve, equity_curve[1:]):
        prev_eq = float(prev.get("equity") or 100.0)
        curr_eq = float(curr.get("equity") or prev_eq)
        if prev_eq > 0:
            out.append((curr_eq - prev_eq) / prev_eq)
    return out


def _correlation(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    if n < 3:
        return 0.0
    xs, ys = a[:n], b[:n]
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den_x = math.sqrt(sum((x - mx) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - my) ** 2 for y in ys))
    if den_x == 0 or den_y == 0:
        return 0.0
    return num / (den_x * den_y)


def compare_portfolio(
    *,
    strategy_name: str = "ma_crossover",
    limit: int = 120,
    stop_loss_pct: float = 3.0,
    take_profit_pct: float = 5.0,
) -> dict[str, Any]:
    """Run one strategy on three teaching legs and aggregate equal-weight returns."""
    prices = load_prices(DATA_DIR / "prices.csv")[: max(60, min(1500, limit))]
    legs = [
        ("WEB3-DEMO/USDT", 0, 0.0),
        ("WEB3-DEMO-LAG2/USDT", 2, 0.0),
        ("WEB3-DEMO-DRIFT/USDT", 0, 0.0003),
    ]

    strategy = get_strategy(strategy_name)
    params = dict(strategy.default_params())
    overrides = strategy.backtest_config_overrides(params)
    config = BacktestConfig(
        min_context=MIN_CONTEXT,
        stop_loss_pct=max(0.5, min(20.0, stop_loss_pct)),
        take_profit_pct=max(0.5, min(50.0, take_profit_pct)),
        max_hold_bars=int(overrides.get("max_hold_bars", 0)),
        commission_pct=0.1,
        kline_type="1day",
    )

    leg_rows: list[dict[str, Any]] = []
    return_series: list[list[float]] = []

    for leg_id, lag, drift in legs:
        candles = _leg_candles_from_closes(prices, leg_id=leg_id, lag=lag, scale_drift=drift)
        if len(candles) < MIN_CONTEXT + 5:
            continue
        trades, equity, _ = run_backtest(candles, strategy, params, config)
        metrics = compute_metrics(
            trades=trades,
            equity_curve=equity,
            candles=candles,
            symbol=leg_id,
            kline_type="1day",
            strategy_name=strategy.display_name,
        )
        rets = _daily_returns(equity)
        return_series.append(rets)
        leg_rows.append(
            {
                "symbol": leg_id,
                "weight": round(1.0 / len(legs), 4),
                "total_return_pct": metrics.total_return_pct,
                "max_drawdown_pct": metrics.max_drawdown_pct,
                "sharpe_ratio": metrics.sharpe_ratio,
                "total_trades": metrics.total_trades,
            }
        )

    pair_corr: list[dict[str, Any]] = []
    for i in range(len(leg_rows)):
        for j in range(i + 1, len(leg_rows)):
            pair_corr.append(
                {
                    "a": leg_rows[i]["symbol"],
                    "b": leg_rows[j]["symbol"],
                    "correlation": round(_correlation(return_series[i], return_series[j]), 4),
                }
            )

    min_len = min((len(series) for series in return_series), default=0)
    combined_return = 0.0
    if min_len >= 1:
        weight = 1.0 / len(return_series)
        for day in range(min_len):
            combined_return += sum(weight * series[day] for series in return_series)

    avg_leg_return = (
        sum(row["total_return_pct"] for row in leg_rows) / len(leg_rows) if leg_rows else 0.0
    )

    return {
        "ok": True,
        "strategy_key": strategy_name,
        "legs": leg_rows,
        "pair_correlations": pair_corr,
        "equal_weight_daily_return_sum_pct": round(combined_return * 100, 2),
        "equal_weight_leg_avg_return_pct": round(avg_leg_return, 2),
        "diversification_hint": (
            "pair correlation < 0.7 suggests legs are not identical; "
            "still teaching sample — not investable portfolio proof."
        ),
        "assumptions": [
            "Three legs derived from data/prices.csv (base, 2-bar lag, mild drift).",
            "Equal weight rebalance implicit in daily return average.",
            "No cross-leg margin or funding — teaching aggregation only.",
        ],
    }
