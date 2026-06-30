"""Sandbox ``ai_trading.api`` surface for compiled strategy DSL code."""

from __future__ import annotations

from decimal import Decimal

from strategy_engine.backtest.candles import Candle
from strategy_engine.backtest.engine import StrategyContext
from strategy_engine.backtest.protocol import OrderIntent, OrderSide, OrderType, TimeInForce


def market_buy(symbol: str, qty: Decimal | float | int) -> OrderIntent:
    return OrderIntent(
        symbol=symbol,
        side=OrderSide.BUY,
        type=OrderType.MARKET,
        qty=Decimal(str(qty)),
    )


def market_sell(symbol: str, qty: Decimal | float | int) -> OrderIntent:
    return OrderIntent(
        symbol=symbol,
        side=OrderSide.SELL,
        type=OrderType.MARKET,
        qty=Decimal(str(qty)),
    )


def limit_buy(
    symbol: str,
    qty: Decimal | float | int,
    price: Decimal | float | int,
    *,
    time_in_force: TimeInForce = TimeInForce.GTC,
) -> OrderIntent:
    return OrderIntent(
        symbol=symbol,
        side=OrderSide.BUY,
        type=OrderType.LIMIT,
        qty=Decimal(str(qty)),
        price=Decimal(str(price)),
        time_in_force=time_in_force,
    )


def limit_sell(
    symbol: str,
    qty: Decimal | float | int,
    price: Decimal | float | int,
    *,
    time_in_force: TimeInForce = TimeInForce.GTC,
) -> OrderIntent:
    return OrderIntent(
        symbol=symbol,
        side=OrderSide.SELL,
        type=OrderType.LIMIT,
        qty=Decimal(str(qty)),
        price=Decimal(str(price)),
        time_in_force=time_in_force,
    )


__all__ = [
    "Candle",
    "Decimal",
    "OrderIntent",
    "OrderSide",
    "OrderType",
    "StrategyContext",
    "TimeInForce",
    "limit_buy",
    "limit_sell",
    "market_buy",
    "market_sell",
]
