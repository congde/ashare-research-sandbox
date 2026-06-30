from __future__ import annotations

from decimal import Decimal

from strategy_engine.backtest.candles import Candle
from strategy_engine.backtest.engine import StrategyContext
from strategy_engine.backtest.protocol import OrderIntent


def _sma(closes: list[Decimal], window: int) -> Decimal | None:
    if len(closes) < window:
        return None
    sample = closes[-window:]
    return sum(sample, start=Decimal("0")) / Decimal(window)


def make_ma_crossover_strategy(short: int, long: int):
    """Long-only MA crossover using the same on_tick contract as live runtime."""

    def on_tick(ctx: StrategyContext, candle: Candle) -> OrderIntent | None:
        closes = [bar.close for bar in ctx.history]
        short_ma = _sma(closes, short)
        long_ma = _sma(closes, long)
        if short_ma is None or long_ma is None:
            return None

        position = ctx.position()
        should_hold = short_ma > long_ma

        if should_hold and position.qty == 0:
            if ctx.portfolio.cash <= 0 or candle.close <= 0:
                return None
            qty = ctx.portfolio.cash / candle.close
            return ctx.order_intent("buy", qty, type="market")

        if not should_hold and position.qty > 0:
            return ctx.order_intent("sell", position.qty, type="market")

        return None

    return on_tick
