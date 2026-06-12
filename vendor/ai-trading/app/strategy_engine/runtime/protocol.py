"""Runtime protocols — the injection boundary.

The runtime depends on two Protocols, not concrete classes:

  * :class:`CandleSource` — async generator of ``Candle`` objects.
    The WS aggregator (``app.connectors.ws_aggregator``) satisfies
    this in production; tests inject a fake.

  * :class:`OrderRouter` — accepts an ``OrderIntent`` and tries to
    execute it. The simulated router (``SimOrderRouter``) satisfies
    this for dry-run; the real-adapter router will satisfy it for
    live (next PR).

Defining these as Protocols (not ABCs) means anything quack-typed
works without subclass declarations — keeps the test fakes light.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from app.connectors.protocol import OrderIntent
from app.domain.market_data import Candle

# ── Candle source ────────────────────────────────────────────────


class CandleSource(Protocol):
    """Source of real-time (or replayed) candles for ``symbol/timeframe``.

    Implementations:

      * ``WSAggregator`` in ``app.connectors.ws_aggregator`` —
        production live feed.
      * ``ReplayCandleSource`` — wraps a list and yields with
        controllable cadence; used by dry-run replay backtests.
      * Test fakes — yield from a fixture list.

    Contract: each yielded candle has ``ts`` strictly greater than the
    previous one (the source is responsible for gap filling /
    dedup). Backpressure is via the consumer's iteration pace — the
    runtime calls ``on_tick`` synchronously per yield, so a slow
    strategy throttles the source naturally.
    """

    def stream(
        self, *, symbol: str, timeframe: str
    ) -> AsyncIterator[Candle]: ...


# ── Order router ─────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class FillReport:
    """Outcome of submitting an OrderIntent.

    The runtime updates its Portfolio + ``RuntimeResult.trades`` from
    this. ``state`` follows the order state machine in
    :mod:`app.domain.order.models`; for v1 we expose only the terminal
    states the simulated router produces:

      * ``"filled"`` — fully executed at ``fill_price``
      * ``"rejected"`` — venue / risk gate / vault refused
      * ``"cancelled"`` — IOC/FOK didn't cross
    """

    intent: OrderIntent
    state: str  # filled | rejected | cancelled
    fill_price: Decimal | None = None
    fill_qty: Decimal | None = None
    fee: Decimal | None = None
    fee_currency: str | None = None
    submitted_at: datetime | None = None
    filled_at: datetime | None = None
    error: str | None = None  # populated on rejected/cancelled


class OrderRouter(Protocol):
    """Routes an ``OrderIntent`` to a fill source.

    Implementations:

      * ``SimOrderRouter`` — paper fills using the same slippage / fee
        models as the backtest engine. Same code path → backtest and
        dry-run produce comparable numbers.
      * ``BinanceOrderRouter`` (next PR) — translates to
        ``ExchangeAdapter.create_order`` + maps the returned
        ``Order`` back into a ``FillReport``.

    Synchronous async — the router is called once per OrderIntent the
    strategy emits, on the strategy's tick. Concurrent submissions to
    multiple venues are NOT a v1.0 concern; the runtime assumes one
    venue per strategy.
    """

    async def submit(
        self, intent: OrderIntent, *, candle: Candle
    ) -> FillReport:
        """Submit ``intent``. ``candle`` is the bar the strategy was
        looking at when it produced the intent — needed by simulated
        routers to compute slippage from intra-bar range, ignored by
        real-adapter routers."""
        ...
