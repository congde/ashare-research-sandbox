from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Price:
    date: str
    close: float


def load_prices(path: Path) -> list[Price]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [
            Price(row["date"], float(row["close"]))
            for row in csv.DictReader(handle)
        ]


def moving_average(values: list[float], window: int, index: int) -> float | None:
    if index + 1 < window:
        return None
    sample = values[index + 1 - window : index + 1]
    return sum(sample) / window


def maximum_drawdown(equity: list[float]) -> float:
    peak = equity[0]
    worst = 0.0
    for value in equity:
        peak = max(peak, value)
        worst = min(worst, value / peak - 1)
    return worst


def run_backtest(prices: list[Price], short: int = 3, long: int = 7) -> dict:
    if short < 2 or long <= short:
        raise ValueError("Use windows where 2 <= short < long.")
    if len(prices) <= long:
        raise ValueError("Not enough price rows for the long window.")

    closes = [item.close for item in prices]
    cash = 10_000.0
    shares = 0.0
    position = False
    trades: list[dict] = []
    curve: list[dict] = []

    for index, item in enumerate(prices):
        short_ma = moving_average(closes, short, index)
        long_ma = moving_average(closes, long, index)
        should_hold = (
            short_ma is not None and long_ma is not None and short_ma > long_ma
        )
        if should_hold and not position:
            shares = cash / item.close
            cash = 0.0
            position = True
            trades.append({"date": item.date, "action": "BUY", "price": item.close})
        elif not should_hold and position:
            cash = shares * item.close
            shares = 0.0
            position = False
            trades.append({"date": item.date, "action": "SELL", "price": item.close})

        equity = cash + shares * item.close
        curve.append(
            {
                "date": item.date,
                "close": item.close,
                "short_ma": round(short_ma, 4) if short_ma is not None else None,
                "long_ma": round(long_ma, 4) if long_ma is not None else None,
                "equity": round(equity, 2),
            }
        )

    final_equity = curve[-1]["equity"]
    buy_hold_return = closes[-1] / closes[0] - 1
    return {
        "parameters": {"short_window": short, "long_window": long},
        "metrics": {
            "strategy_return_pct": round((final_equity / 10_000 - 1) * 100, 2),
            "buy_hold_return_pct": round(buy_hold_return * 100, 2),
            "maximum_drawdown_pct": round(
                maximum_drawdown([point["equity"] for point in curve]) * 100, 2
            ),
            "trade_count": len(trades),
            "final_equity": final_equity,
        },
        "trades": trades,
        "curve": curve,
        "assumptions": [
            "Uses fixed fictional daily close prices.",
            "Ignores fees, slippage, taxes, suspensions, and position limits.",
            "Historical sample performance cannot predict future returns.",
        ],
    }

