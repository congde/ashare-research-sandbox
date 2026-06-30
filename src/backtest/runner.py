from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from backtest.metrics import sharpe_ratio
from risk.config import DEFAULT_RULE_IDS, default_risk_manager
from strategy_engine.backtest.candles import Candle
from strategy_engine.backtest.engine import BacktestEngine
from strategy_engine.strategies.ma_crossover import make_ma_crossover_strategy


SYMBOL = "WEB3-DEMO/USDT"
INITIAL_CAPITAL = Decimal("10000")


@dataclass(frozen=True)
class Price:
    date: str
    close: float


def load_prices(
    path: Path,
    *,
    delimiter: str = ",",
    encoding: str = "utf-8",
) -> list[Price]:
    with path.open(encoding=encoding, newline="") as handle:
        return [
            Price(row["date"], float(row["close"]))
            for row in csv.DictReader(handle, delimiter=delimiter)
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


def calmar_ratio(total_return_pct: float, maximum_drawdown_pct: float) -> float:
    """Adapted from web3-trading's pure Calmar metric for negative drawdown."""
    if maximum_drawdown_pct == 0:
        return 0.0
    return total_return_pct / abs(maximum_drawdown_pct)


def prices_to_candles(prices: list[Price], symbol: str = SYMBOL) -> list[Candle]:
    candles: list[Candle] = []
    for item in prices:
        close = Decimal(str(item.close))
        ts = datetime.strptime(item.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        candles.append(
            Candle(
                exchange="teaching",
                symbol=symbol,
                timeframe="1day",
                ts=ts,
                open=close,
                high=close * Decimal("1.002"),
                low=close * Decimal("0.998"),
                close=close,
                volume=Decimal("1"),
            )
        )
    return candles


def _format_engine_result(
    result,
    prices: list[Price],
    candles: list[Candle],
    *,
    short: int,
    long: int,
) -> dict:
    closes = [item.close for item in prices]
    ts_to_date = {candle.ts: price.date for candle, price in zip(candles, prices)}

    curve: list[dict] = []
    equity_values: list[float] = []
    for index, item in enumerate(prices):
        short_ma = moving_average(closes, short, index)
        long_ma = moving_average(closes, long, index)
        equity = round(float(result.equity_curve[index][1]), 2)
        equity_values.append(equity)
        curve.append(
            {
                "date": item.date,
                "close": item.close,
                "short_ma": round(short_ma, 4) if short_ma is not None else None,
                "long_ma": round(long_ma, 4) if long_ma is not None else None,
                "equity": equity,
            }
        )

    trades = [
        {
            "date": ts_to_date[trade.ts],
            "action": trade.side.upper(),
            "price": float(trade.price),
        }
        for trade in result.trades
    ]

    risk_rejections = [
        {
            "date": ts_to_date.get(rejection.ts, rejection.ts.date().isoformat()),
            "symbol": rejection.symbol,
            "side": rejection.side.upper(),
            "rule_id": rejection.rule_id,
            "reason": rejection.reason,
        }
        for rejection in result.risk_rejections
    ]

    buy_hold_return = closes[-1] / closes[0] - 1
    strategy_return_pct = round(result.metrics.pnl_pct, 2)
    maximum_drawdown_pct = round(-result.metrics.max_drawdown_pct, 2)
    final_equity = round(float(result.metrics.final_equity), 2)

    return {
        "parameters": {"short_window": short, "long_window": long},
        "metrics": {
            "strategy_return_pct": strategy_return_pct,
            "buy_hold_return_pct": round(buy_hold_return * 100, 2),
            "maximum_drawdown_pct": maximum_drawdown_pct,
            "calmar_ratio": round(
                calmar_ratio(strategy_return_pct, maximum_drawdown_pct), 2
            ),
            "sharpe_ratio": round(sharpe_ratio(equity_values), 2),
            "trade_count": len(trades),
            "final_equity": final_equity,
        },
        "trades": trades,
        "curve": curve,
        "risk_rejections": risk_rejections,
        "risk_rules": list(DEFAULT_RULE_IDS),
        "engine": "ai-trading/event-driven",
        "assumptions": [
            "Uses ai-trading event-driven BacktestEngine (ADR-0009).",
            "Pre-trade RiskManager gates every order intent (5 MVP rules).",
            "Uses fixed fictional Web3 daily close prices.",
            "Teaching run uses zero fee and zero slippage models.",
            "Historical sample performance cannot predict future returns.",
        ],
    }


def run_backtest(prices: list[Price], short: int = 3, long: int = 7) -> dict:
    if short < 2 or long <= short:
        raise ValueError("Use windows where 2 <= short < long.")
    if len(prices) <= long:
        raise ValueError("Not enough price rows for the long window.")

    candles = prices_to_candles(prices)
    engine = BacktestEngine(
        strategy_fn=make_ma_crossover_strategy(short, long),
        initial_capital=INITIAL_CAPITAL,
        risk_manager=default_risk_manager(initial_capital=INITIAL_CAPITAL),
    )
    result = engine.run(candles, symbol=SYMBOL, timeframe="1day")
    return _format_engine_result(result, prices, candles, short=short, long=long)
