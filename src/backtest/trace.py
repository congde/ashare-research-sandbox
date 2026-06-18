"""Teaching helpers for event-driven backtest walkthroughs (chapter 18)."""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from typing import Any

from backtest.runner import load_prices, prices_to_candles, run_backtest
from paths import DATA_DIR
from risk.config import default_risk_manager
from strategy_engine.backtest.candles import Candle
from strategy_engine.backtest.engine import BacktestEngine, StrategyContext
from strategy_engine.backtest.protocol import OrderIntent, OrderSide, OrderType
from strategy_engine.strategies.ma_crossover import make_ma_crossover_strategy


def run_ma_crossover_trace(*, short: int = 3, long: int = 7) -> dict[str, Any]:
    """Run MA crossover on the teaching sample and return an auditable event trail."""
    prices = load_prices(DATA_DIR / "prices.csv")
    report = run_backtest(prices, short=short, long=long)
    trail: list[dict[str, Any]] = []
    equity_by_date = {point["date"]: point["equity"] for point in report["curve"]}

    for index, trade in enumerate(report["trades"]):
        equity = equity_by_date.get(trade["date"])
        trail.append(
            {
                "step": index + 1,
                "date": trade["date"],
                "event": "trade_filled",
                "action": trade["action"],
                "price": trade["price"],
                "equity_after": equity,
                "note": "事件驱动引擎在对应 K 线收盘时成交",
            }
        )

    rejections = [
        {
            "date": item["date"],
            "rule_id": item["rule_id"],
            "reason": item["reason"],
            "side": item["side"],
        }
        for item in report.get("risk_rejections", [])
    ]

    return {
        "ok": True,
        "engine": report["engine"],
        "parameters": report["parameters"],
        "metrics": report["metrics"],
        "trail": trail,
        "risk_rejections": rejections,
        "assumptions": report["assumptions"],
        "what_it_proves": [
            "策略在每根 K 线只看到当时及之前的 history",
            "每笔成交可在 trades 与 equity 曲线中逐笔核对",
            "RiskManager 拒绝会写入 risk_rejections 而不是静默丢弃",
        ],
        "what_it_does_not_prove": [
            "未来收益",
            "真实交易所成交价格",
            "LLM 信号本身正确",
        ],
    }


def _scripted_teaching_strategy(ctx: StrategyContext, candle: Candle) -> OrderIntent | None:
    """Emit market buy, resting limit, then oversized market buy for teaching."""
    index = len(ctx.history) - 1
    if index == 2:
        return ctx.order_intent("buy", Decimal("1"))
    if index == 3:
        return ctx.order_intent("buy", Decimal("1"), type="limit", price=candle.close * Decimal("0.5"))
    if index == 4:
        return ctx.order_intent("buy", Decimal("2000"))
    return None


def run_teaching_scenario() -> dict[str, Any]:
    """Minimal scenario: fill, pending limit, risk rejection."""
    prices = load_prices(DATA_DIR / "prices.csv")
    candles = prices_to_candles(prices[:8])
    capital = Decimal("10000")
    engine = BacktestEngine(
        strategy_fn=_scripted_teaching_strategy,
        initial_capital=capital,
        risk_manager=default_risk_manager(initial_capital=capital),
    )
    result = engine.run(candles, symbol="WEB3-DEMO/USDT", timeframe="1day")

    rows: list[dict[str, Any]] = []
    trade_dates = {trade.ts: trade for trade in result.trades}
    rejection_dates = {item.ts: item for item in result.risk_rejections}
    pending_snapshot = engine.pending_orders_snapshot()

    for index, candle in enumerate(candles):
        row: dict[str, Any] = {
            "bar": index + 1,
            "date": candle.ts.date().isoformat(),
            "close": float(candle.close),
            "history_bars": index + 1,
            "pending_after_bar": len(pending_snapshot),
        }
        if candle.ts in trade_dates:
            trade = trade_dates[candle.ts]
            row["fill"] = {
                "side": trade.side,
                "qty": float(trade.qty),
                "price": float(trade.price),
                "fee": float(trade.fee),
            }
        if candle.ts in rejection_dates:
            rejection = rejection_dates[candle.ts]
            row["risk_block"] = {
                "rule_id": rejection.rule_id,
                "reason": rejection.reason,
            }
        rows.append(row)

    return {
        "ok": True,
        "engine": "ai-trading/event-driven",
        "scenario": "market_fill + pending_limit + risk_rejection",
        "bars": rows,
        "trades": [
            {
                "date": trade.ts.date().isoformat(),
                "side": trade.side,
                "qty": float(trade.qty),
                "price": float(trade.price),
            }
            for trade in result.trades
        ],
        "risk_rejections": [
            {
                "ts": rejection.ts.isoformat(),
                "symbol": rejection.symbol,
                "side": rejection.side,
                "rule_id": rejection.rule_id,
                "reason": rejection.reason,
            }
            for rejection in result.risk_rejections
        ],
        "pending_at_end": [
            {
                "side": intent.side.value,
                "type": intent.type.value,
                "price": float(intent.price) if intent.price is not None else None,
            }
            for intent in pending_snapshot
        ],
        "final_equity": float(result.metrics.final_equity),
        "lesson": [
            "第 3 根 K 线：市价买入立即成交",
            "第 4 根 K 线：低价限价单进入 pending，本 bar 未成交",
            "第 5 根 K 线：超大买单被 MAX_POSITION_PCT 拒绝",
        ],
    }
