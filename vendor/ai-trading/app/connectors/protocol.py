"""Exchange adapter Protocol + value-object envelopes.

Per ADR-0005 (ccxt unified). Concrete adapters live in this package
under ``app.connectors.<exchange>`` and implement ``ExchangeAdapter``.

The Protocol is intentionally narrow — anything beyond the methods
declared here belongs in adapter-specific extensions, NOT the
business / strategy / risk layers.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable

from app.domain.market_data import Candle, OrderBook, Ticker, Trade


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class TimeInForce(StrEnum):
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"


@dataclass(frozen=True, slots=True)
class OrderIntent:
    """Pure value object — never hits the exchange directly.

    Produced by user strategies via ``ai_trading.api.order_intent``.
    Travels through RiskManager → OrderRouter → Adapter.create_order.
    """

    symbol: str
    side: OrderSide
    type: OrderType
    qty: Decimal
    price: Decimal | None = None
    stop_price: Decimal | None = None
    time_in_force: TimeInForce = TimeInForce.GTC
    client_order_id: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Order:
    """Acknowledged order from the exchange."""

    exchange: str
    exchange_order_id: str
    client_order_id: str
    intent: OrderIntent
    state: str  # 'submitted' | 'filled' | 'partial' | 'cancelled' | 'rejected'
    fill_qty: Decimal = Decimal("0")
    fill_price: Decimal | None = None
    fee: Decimal | None = None
    fee_currency: str | None = None
    submitted_at: datetime | None = None
    filled_at: datetime | None = None
    raw: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Balance:
    """Single-asset balance entry."""

    asset: str
    free: Decimal
    locked: Decimal


@dataclass(frozen=True, slots=True)
class AccountBalance:
    """Snapshot of all balances for an exchange account."""

    exchange: str
    timestamp: datetime
    balances: tuple[Balance, ...]


@dataclass(frozen=True, slots=True)
class ExchangePosition:
    """Derivative position (futures / perpetual)."""

    exchange: str
    symbol: str
    side: str  # 'long' | 'short'
    qty: Decimal
    entry_price: Decimal
    mark_price: Decimal
    unrealized_pnl: Decimal
    leverage: int = 1


class AdapterError(Exception):
    """Base exception for adapter failures."""


class RateLimitError(AdapterError):
    """Local rate-limit window exceeded — caller should back off."""


class ExchangeRejectError(AdapterError):
    """Exchange returned non-fatal rejection (e.g. invalid order params)."""


class ExchangeUnavailableError(AdapterError):
    """Exchange transient (5xx / timeout) — retry candidate."""


@runtime_checkable
class ExchangeAdapter(Protocol):
    """The single contract every CEX adapter satisfies.

    Implementations may add extra methods, but the strategy / risk /
    backtest layers may only use what is declared here.
    """

    name: str
    supports: dict[str, bool]  # {"spot": True, "futures": ..., "margin": ...}

    # ── Public market data ─────────────────────────────────────────
    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: datetime | None = None,
        limit: int = 200,
    ) -> list[Candle]: ...

    async def fetch_orderbook(self, symbol: str, limit: int = 20) -> OrderBook: ...

    async def fetch_ticker(self, symbol: str) -> Ticker: ...

    async def watch_trades(self, symbol: str) -> AsyncIterator[Trade]: ...

    async def watch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
    ) -> AsyncIterator[Candle]: ...

    # ── Authenticated trading ──────────────────────────────────────
    async def create_order(self, intent: OrderIntent) -> Order: ...

    async def cancel_order(self, order_id: str, symbol: str) -> Order: ...

    async def fetch_order(self, order_id: str, symbol: str) -> Order: ...

    async def fetch_balance(self) -> AccountBalance: ...

    async def fetch_positions(
        self,
        symbols: tuple[str, ...] | None = None,
    ) -> tuple[ExchangePosition, ...]: ...
