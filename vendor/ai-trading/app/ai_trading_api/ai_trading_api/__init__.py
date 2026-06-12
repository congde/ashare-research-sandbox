"""``ai_trading.api`` — the **only** import path user / LLM strategy
code is allowed to take.

Per ADR-0007 + the DSL safelist (``app/strategy_engine/dsl/safelist.py``),
strategies are isolated from the platform's internals. They speak to
the runtime through this curated surface — never via ``app.*``,
``ccxt.*``, or raw filesystem / network primitives.

The surface is deliberately small. v1.0 covers the textbook needs
(one symbol, on_tick callback, market / limit / stop orders, position
inspection); anything richer (multi-leg, conditional, scheduled, OCO,
basket orders) is parked to v1.5+ behind separate ADRs.

Source location vs import path
------------------------------

The module lives at ``app/ai_trading_api/__init__.py`` for ergonomic
co-location with the rest of the platform code. The strategy
sandbox (``app/core/sandbox/``) aliases this to ``ai_trading.api``
at runtime — so user code's ``from ai_trading.api import OrderIntent``
resolves to the same objects defined here. The DSL safelist allows
``ai_trading.api`` and disallows ``app.ai_trading_api`` precisely to
keep the contract visible: strategies see the alias, not the source.

Importing this module is cheap (re-exports only — no heavy deps).
"""

from __future__ import annotations

from decimal import Decimal

# ── Research surface (strategies access via ctx.research.*) ──────
# Public Protocol + exception taxonomy. The concrete implementation
# (ResearchAgentService) lives in app.services and is wired into
# ctx by the runtime — strategies never construct one directly.
from app.ai_trading_api.research import (
    NoOpResearch,
    ResearchCreditExceededError,
    ResearchNotConfiguredError,
    ResearchSurface,
    ResearchToolError,
    ResearchToolNotFoundError,
    ResearchUpstreamError,
)
from app.connectors.protocol import (
    OrderIntent,
    OrderSide,
    OrderType,
    TimeInForce,
)

# ── Re-exports: market-data value objects ────────────────────────
# Strategies need to read candles + ticker + orderbook by *type*.
# We re-export the domain dataclasses verbatim — there's no value in
# wrapping them; the domain layer is the source of truth and the
# dataclass shape is intentionally stable.
from app.domain.market_data import (
    Candle,
    OrderBook,
    OrderBookLevel,
    Ticker,
    Trade,
)

# ── Strategy context surface ─────────────────────────────────────
# ``StrategyContext`` is currently defined inside the backtest engine
# (``app.strategy_engine.backtest.engine.StrategyContext``). That's
# fine for now — when the live runtime lands in S7-S8, the context
# will be the same shape, just constructed by a different orchestrator.
# Re-exporting from one place keeps the strategy-author-facing contract
# stable across backtest and live.
from app.strategy_engine.backtest.engine import StrategyContext

# ── Convenience helpers ─────────────────────────────────────────


def market_buy(symbol: str, qty: Decimal | float | int) -> OrderIntent:
    """Shorthand for the most common case: buy ``qty`` of ``symbol``
    at market.

    Strategies have access to ``ctx.order_intent(...)`` but that's
    deliberately low-level — for the 80 % case of "buy at market"
    this helper saves five named-arg keystrokes per call.
    """
    return OrderIntent(
        symbol=symbol,
        side=OrderSide.BUY,
        type=OrderType.MARKET,
        qty=Decimal(str(qty)),
    )


def market_sell(symbol: str, qty: Decimal | float | int) -> OrderIntent:
    """Sister of :func:`market_buy`. ``qty`` is positive — direction
    is encoded by the function name, not by the sign of qty."""
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
    """Resting buy order at ``price``. GTC by default; IOC / FOK
    when the strategy wants same-bar cancellation semantics."""
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
    """Sister of :func:`limit_buy`. Same TimeInForce semantics."""
    return OrderIntent(
        symbol=symbol,
        side=OrderSide.SELL,
        type=OrderType.LIMIT,
        qty=Decimal(str(qty)),
        price=Decimal(str(price)),
        time_in_force=time_in_force,
    )


def stop_loss(
    symbol: str,
    qty: Decimal | float | int,
    stop_price: Decimal | float | int,
) -> OrderIntent:
    """Sell at market when price drops through ``stop_price``.

    Common idiom: protect a long position. The "stop-loss" naming is
    the conventional quant-jargon name; under the hood it's a SELL +
    STOP type. Strategies that want a buy-stop (break-out long) use
    :func:`buy_stop`.
    """
    return OrderIntent(
        symbol=symbol,
        side=OrderSide.SELL,
        type=OrderType.STOP,
        qty=Decimal(str(qty)),
        stop_price=Decimal(str(stop_price)),
    )


def buy_stop(
    symbol: str,
    qty: Decimal | float | int,
    stop_price: Decimal | float | int,
) -> OrderIntent:
    """Buy at market when price breaks UP through ``stop_price``.
    Classic break-out entry."""
    return OrderIntent(
        symbol=symbol,
        side=OrderSide.BUY,
        type=OrderType.STOP,
        qty=Decimal(str(qty)),
        stop_price=Decimal(str(stop_price)),
    )


# ── Public surface ───────────────────────────────────────────────


__all__ = [
    # Value objects
    "Candle",
    "OrderBook",
    "OrderBookLevel",
    "Ticker",
    "Trade",
    "OrderIntent",
    "OrderSide",
    "OrderType",
    "TimeInForce",
    # Context (provided by the runtime, not constructed by strategies)
    "StrategyContext",
    # Research surface — strategies access via ctx.research.*
    "NoOpResearch",
    "ResearchSurface",
    "ResearchToolError",
    "ResearchNotConfiguredError",
    "ResearchToolNotFoundError",
    "ResearchUpstreamError",
    "ResearchCreditExceededError",
    # Convenience builders
    "market_buy",
    "market_sell",
    "limit_buy",
    "limit_sell",
    "stop_loss",
    "buy_stop",
    # Standard library re-export — saves strategies importing Decimal
    # themselves (still allowed via the safelist, but having it here
    # is one less line in the LLM prompt).
    "Decimal",
]
