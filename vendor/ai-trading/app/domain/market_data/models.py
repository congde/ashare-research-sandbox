"""Market data domain — Pydantic value objects only.

Per ADR-0006, time-series data lives in ClickHouse, NOT in PG. PG
only carries strategy / order / position state. These dataclasses
are the in-memory contract used by the Connector layer and Backtest
engine; ClickHouse INSERT/SELECT happens through
``packages/connectors/clickhouse_adapter.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Candle:
    """OHLCV bar."""

    exchange: str
    symbol: str
    timeframe: str
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_volume: Decimal | None = None


@dataclass(frozen=True, slots=True)
class Trade:
    """Streaming trade tick."""

    exchange: str
    symbol: str
    ts: datetime
    side: str  # 'buy' | 'sell'
    price: Decimal
    qty: Decimal


@dataclass(frozen=True, slots=True)
class OrderBookLevel:
    price: Decimal
    qty: Decimal


@dataclass(frozen=True, slots=True)
class OrderBook:
    exchange: str
    symbol: str
    ts: datetime
    bids: tuple[OrderBookLevel, ...]
    asks: tuple[OrderBookLevel, ...]


@dataclass(frozen=True, slots=True)
class Ticker:
    exchange: str
    symbol: str
    ts: datetime
    last: Decimal
    bid: Decimal
    ask: Decimal
    volume_24h: Decimal
