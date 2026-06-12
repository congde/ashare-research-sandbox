"""Tests for the real-exchange OrderRouter (AdapterOrderRouter).

The router translates OrderIntent → adapter.create_order → FillReport.
We test the translation layer + the error-normalisation behaviour
WITHOUT hitting a real exchange (no testnet calls in the unit suite).

What we use:

  * ``_FakeAdapter`` — minimal stand-in that satisfies the
    ``ExchangeAdapter`` Protocol for our purposes (only ``create_order``
    is exercised by this router). Configurable to return a specific
    ``Order`` or raise a specific ``AdapterError`` subclass per call.

Why a fake instead of FakeBinanceClient (used elsewhere): the unit
suite tests THIS router's translation logic, not adapter behaviour.
A leaner fake keeps the test surface focused.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.connectors.protocol import (
    AdapterError,
    ExchangeRejectError,
    ExchangeUnavailableError,
    Order,
    OrderIntent,
    OrderSide,
    OrderType,
    RateLimitError,
    TimeInForce,
)
from app.domain.market_data import Candle
from app.strategy_engine.runtime import AdapterOrderRouter

# ── Fake adapter ────────────────────────────────────────────────


class _FakeAdapter:
    """Minimal stand-in for the OrderRouter's adapter dependency.

    Two modes per construction:
      * ``return_order=Order(...)`` — create_order returns it
      * ``raise_exc=Exception(...)`` — create_order raises it

    Records every create_order call so tests can assert exactly which
    intents were forwarded.
    """

    name = "fake"
    supports = {"spot": True, "futures": False, "margin": False}

    def __init__(
        self,
        *,
        return_order: Order | None = None,
        raise_exc: Exception | None = None,
    ) -> None:
        self._return_order = return_order
        self._raise_exc = raise_exc
        self.calls: list[OrderIntent] = []

    async def create_order(self, intent: OrderIntent) -> Order:
        self.calls.append(intent)
        if self._raise_exc is not None:
            raise self._raise_exc
        if self._return_order is not None:
            return self._return_order
        raise AssertionError("FakeAdapter mis-configured: no order, no exception")


# ── Fixtures ────────────────────────────────────────────────────


def _intent(
    *,
    type_: OrderType = OrderType.MARKET,
    side: OrderSide = OrderSide.BUY,
    qty: str = "0.001",
    price: str | None = None,
    tif: TimeInForce = TimeInForce.GTC,
) -> OrderIntent:
    return OrderIntent(
        symbol="BTC/USDT",
        side=side,
        type=type_,
        qty=Decimal(qty),
        price=Decimal(price) if price else None,
        time_in_force=tif,
    )


def _candle() -> Candle:
    """The router ignores the candle param, but the OrderRouter
    Protocol requires we pass one. Build a sane default."""
    p = Decimal("60000.0")
    return Candle(
        exchange="binance",
        symbol="BTC/USDT",
        timeframe="1m",
        ts=datetime(2026, 5, 16, tzinfo=UTC),
        open=p, high=p, low=p, close=p,
        volume=Decimal("1.0"),
    )


def _filled_order(
    intent: OrderIntent,
    *,
    state: str = "filled",
    fill_price: Decimal | None = Decimal("60000.0"),
    fill_qty: Decimal | None = None,
    fee: Decimal = Decimal("0.06"),
) -> Order:
    """Build an adapter-shaped Order suitable for happy-path returns."""
    return Order(
        exchange="binance",
        exchange_order_id="ord-1",
        client_order_id="cli-1",
        intent=intent,
        state=state,
        fill_qty=fill_qty if fill_qty is not None else intent.qty,
        fill_price=fill_price,
        fee=fee,
        fee_currency="USDT",
        submitted_at=datetime(2026, 5, 16, tzinfo=UTC),
        filled_at=datetime(2026, 5, 16, tzinfo=UTC),
    )


# ── Happy path: MARKET fills cleanly ─────────────────────────────


@pytest.mark.asyncio
async def test_market_buy_filled_propagates_fill_metadata() -> None:
    """Adapter returns state=filled + fill_price + fill_qty + fee →
    FillReport carries all of those values unchanged."""
    intent = _intent()
    adapter = _FakeAdapter(return_order=_filled_order(intent))
    router = AdapterOrderRouter(adapter)

    report = await router.submit(intent, candle=_candle())

    assert report.state == "filled"
    assert report.fill_price == Decimal("60000.0")
    assert report.fill_qty == Decimal("0.001")
    assert report.fee == Decimal("0.06")
    assert report.fee_currency == "USDT"
    assert report.error is None
    # Adapter saw exactly the intent the strategy emitted.
    assert adapter.calls == [intent]


@pytest.mark.asyncio
async def test_market_sell_filled_propagates() -> None:
    """SELL side mirrors BUY — symmetric flow."""
    intent = _intent(side=OrderSide.SELL)
    adapter = _FakeAdapter(return_order=_filled_order(intent))
    router = AdapterOrderRouter(adapter)

    report = await router.submit(intent, candle=_candle())
    assert report.state == "filled"
    assert report.intent.side == OrderSide.SELL


@pytest.mark.asyncio
async def test_partial_state_counts_as_filled() -> None:
    """The adapter's ``partial`` state means "some quantity filled" —
    runtime treats it as a fill with the reported fill_qty. The
    strategy's risk gate decides whether to retry the rest."""
    intent = _intent()
    adapter = _FakeAdapter(
        return_order=_filled_order(
            intent, state="partial", fill_qty=Decimal("0.0005")
        ),
    )
    router = AdapterOrderRouter(adapter)
    report = await router.submit(intent, candle=_candle())
    assert report.state == "filled"
    assert report.fill_qty == Decimal("0.0005")


# ── LIMIT / STOP unsupported in v1 ──────────────────────────────


@pytest.mark.asyncio
async def test_limit_order_rejected_in_v1() -> None:
    """LIMIT (any TIF) → router rejects WITHOUT calling the adapter.
    Strategy author gets a clear "use SimOrderRouter for dry-run"
    hint. Adapter.create_order never invoked."""
    intent = _intent(type_=OrderType.LIMIT, price="60000.0")
    adapter = _FakeAdapter(return_order=_filled_order(intent))
    router = AdapterOrderRouter(adapter)

    report = await router.submit(intent, candle=_candle())

    assert report.state == "rejected"
    assert "MARKET" in (report.error or "")
    assert "SimOrderRouter" in (report.error or "")
    # Critical: adapter NEVER touched. Strategy author shouldn't burn
    # rate-limit budget on rejections this layer can catch.
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_stop_order_rejected_in_v1() -> None:
    """STOP — same gate as LIMIT."""
    intent = _intent(type_=OrderType.STOP)
    adapter = _FakeAdapter(return_order=_filled_order(intent))
    router = AdapterOrderRouter(adapter)
    report = await router.submit(intent, candle=_candle())
    assert report.state == "rejected"
    assert adapter.calls == []


# ── Error taxonomy → FillReport mapping ─────────────────────────


@pytest.mark.asyncio
async def test_rate_limit_error_surfaces_as_reject() -> None:
    """KeyPool / RateLimiter rejection → rejected fill with reason."""
    intent = _intent()
    adapter = _FakeAdapter(raise_exc=RateLimitError("hit local 1s window"))
    router = AdapterOrderRouter(adapter)
    report = await router.submit(intent, candle=_candle())
    assert report.state == "rejected"
    assert "rate_limit" in (report.error or "")


@pytest.mark.asyncio
async def test_exchange_reject_error_surfaces_with_reason() -> None:
    """Venue 400 (insufficient balance, bad symbol, halted market)
    bubbles up as rejected with the exchange's reason intact."""
    intent = _intent()
    adapter = _FakeAdapter(
        raise_exc=ExchangeRejectError("balance insufficient"),
    )
    router = AdapterOrderRouter(adapter)
    report = await router.submit(intent, candle=_candle())
    assert report.state == "rejected"
    assert "exchange_reject" in (report.error or "")
    assert "balance insufficient" in (report.error or "")


@pytest.mark.asyncio
async def test_exchange_unavailable_surfaces_as_reject() -> None:
    """5xx / circuit-breaker open → rejected. Strategy can decide to
    retry next bar."""
    intent = _intent()
    adapter = _FakeAdapter(
        raise_exc=ExchangeUnavailableError("circuit open"),
    )
    router = AdapterOrderRouter(adapter)
    report = await router.submit(intent, candle=_candle())
    assert report.state == "rejected"
    assert "exchange_unavailable" in (report.error or "")


@pytest.mark.asyncio
async def test_generic_adapter_error_surfaces_as_reject() -> None:
    """Adapter base-class error (not one of the narrow subclasses) is
    still caught — never lets an exception escape the router."""

    class _CustomAdapterError(AdapterError):
        pass

    intent = _intent()
    adapter = _FakeAdapter(raise_exc=_CustomAdapterError("misc adapter bug"))
    router = AdapterOrderRouter(adapter)
    report = await router.submit(intent, candle=_candle())
    assert report.state == "rejected"
    assert "adapter_error" in (report.error or "")
    assert "_CustomAdapterError" in (report.error or "")


@pytest.mark.asyncio
async def test_non_adapter_exception_propagates() -> None:
    """A bare ``RuntimeError`` (i.e. NOT in the AdapterError
    taxonomy) is NOT silently swallowed — it propagates so the
    runtime / observability layer learns about it.

    Rationale: the AdapterError hierarchy is the contract for
    "expected" failures the router can normalise. Anything outside
    that hierarchy indicates a bug we WANT to see loudly.
    """
    intent = _intent()
    adapter = _FakeAdapter(raise_exc=RuntimeError("unhandled bug"))
    router = AdapterOrderRouter(adapter)
    with pytest.raises(RuntimeError, match="unhandled bug"):
        await router.submit(intent, candle=_candle())


# ── Edge cases in Order → FillReport mapping ────────────────────


@pytest.mark.asyncio
async def test_filled_state_without_fill_price_is_rejected() -> None:
    """Adapter reports state=filled but no fill_price → testnet
    weirdness. Router treats as rejected with explanation so the
    runtime doesn't carry a phantom fill into the Portfolio.
    """
    intent = _intent()
    bad_order = _filled_order(intent, state="filled", fill_price=None)
    adapter = _FakeAdapter(return_order=bad_order)
    router = AdapterOrderRouter(adapter)
    report = await router.submit(intent, candle=_candle())
    assert report.state == "rejected"
    assert "fill_price=None" in (report.error or "")


@pytest.mark.asyncio
async def test_submitted_state_with_zero_fill_qty_is_rejected() -> None:
    """A MARKET order that returns state=submitted but reports 0
    filled is the testnet 'queued, will fill eventually' case. v1
    treats it as rejected because we don't poll for completion."""
    intent = _intent()
    bad = _filled_order(
        intent, state="submitted", fill_qty=Decimal("0"),
    )
    adapter = _FakeAdapter(return_order=bad)
    router = AdapterOrderRouter(adapter)
    report = await router.submit(intent, candle=_candle())
    assert report.state == "rejected"
    assert "submitted" in (report.error or "")


@pytest.mark.asyncio
async def test_cancelled_state_passes_through() -> None:
    """When the adapter itself reports state=cancelled (rare for a
    MARKET request, but possible if the venue rejects on the way to
    the matching engine), the router emits state=cancelled instead
    of rejected — keeps the distinction the FillReport schema makes.
    """
    intent = _intent()
    cancelled = _filled_order(
        intent, state="cancelled", fill_price=None, fill_qty=Decimal("0"),
    )
    adapter = _FakeAdapter(return_order=cancelled)
    router = AdapterOrderRouter(adapter)
    report = await router.submit(intent, candle=_candle())
    assert report.state == "cancelled"
    assert "cancelled" in (report.error or "")


# ── Integration with the runtime ────────────────────────────────


@pytest.mark.asyncio
async def test_router_integrates_into_strategy_runtime() -> None:
    """Sanity check that the router plugs into ``StrategyRuntime`` —
    not just a router-level test. We use a fake candle source + the
    real AdapterOrderRouter wrapping our FakeAdapter, and run a
    simple "MARKET BUY once" strategy.

    The Portfolio should reflect the filled order; the trade should
    appear in result.trades.
    """
    from collections.abc import AsyncIterator

    from app.strategy_engine.runtime import StrategyRuntime
    from app.strategy_engine.runtime.protocol import CandleSource

    class _FakeSource(CandleSource):
        def __init__(self, n: int) -> None:
            self._n = n

        async def stream(self, *, symbol: str, timeframe: str) -> AsyncIterator[Candle]:
            for _ in range(self._n):
                yield _candle()

    state = {"fired": False}

    def on_tick(ctx, candle):
        if state["fired"]:
            return None
        state["fired"] = True
        return ctx.order_intent(side="buy", qty=Decimal("0.001"), type="market")

    intent_match = OrderIntent(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        type=OrderType.MARKET,
        qty=Decimal("0.001"),
    )
    adapter = _FakeAdapter(return_order=_filled_order(intent_match))
    router = AdapterOrderRouter(adapter)

    runtime = StrategyRuntime(
        strategy_fn=on_tick,
        candle_source=_FakeSource(2),
        order_router=router,
        symbol="BTC/USDT",
        timeframe="1m",
        initial_capital=Decimal("1000"),
    )
    result = await runtime.run_until_complete()

    assert len(result.fills) == 1
    assert result.fills[0].state == "filled"
    assert len(result.trades) == 1
    # Adapter was called exactly once (one BUY intent emitted).
    assert len(adapter.calls) == 1
