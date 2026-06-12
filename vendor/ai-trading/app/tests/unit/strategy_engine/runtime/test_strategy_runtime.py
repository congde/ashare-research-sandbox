"""End-to-end tests for the live strategy runtime (dry-run mode).

The runtime is the orchestrator; we exercise the full loop with:

  * A ``FakeCandleSource`` yielding from a pre-built list
  * ``SimOrderRouter`` (real, since it's the v1 dry-run target)
  * A simple buy-and-hold strategy whose behaviour is predictable
    from the candle prices

What we assert:

  * Same on_tick contract works in runtime as in backtest
  * MARKET orders fill, update Portfolio, get recorded as trades
  * LIMIT IOC orders fill when crossing, cancel otherwise
  * GTC LIMIT orders get rejected (v1 limitation)
  * Insufficient-cash refusals surface as rejects, not crashes
  * Event hook fires per kind in the expected order
  * Equity curve has one row per candle
  * Result reproducibility — runtime should match backtest on the
    same candle stream / strategy / models
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain.market_data import Candle
from app.strategy_engine.backtest.engine import BacktestEngine
from app.strategy_engine.runtime import (
    RuntimeEvent,
    SimOrderRouter,
    StrategyRuntime,
)
from app.strategy_engine.runtime.protocol import CandleSource

# ── Fixtures ─────────────────────────────────────────────────────


def _candle(
    ts: datetime,
    *,
    price: float = 100.0,
    volume: float = 1.0,
) -> Candle:
    """Flat-priced candle. open=high=low=close=price (no slippage
    from the OHLC range — keeps deterministic comparisons clean)."""
    p = Decimal(f"{price:.4f}")
    return Candle(
        exchange="test",
        symbol="BTC/USDT",
        timeframe="1m",
        ts=ts,
        open=p,
        high=p,
        low=p,
        close=p,
        volume=Decimal(f"{volume:.4f}"),
    )


def _ramp(n: int, start_price: float = 100.0, step: float = 1.0) -> list[Candle]:
    """N candles, prices climbing by ``step`` per bar starting at
    ``start_price``."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    return [_candle(base + timedelta(minutes=i), price=start_price + i * step) for i in range(n)]


class _ListCandleSource(CandleSource):
    """Async-yields candles from a pre-built list. Production
    candle sources (WSAggregator, ReplayCandleSource) follow the
    same Protocol; this test fake demonstrates the contract."""

    def __init__(self, candles: list[Candle]) -> None:
        self._candles = candles

    async def stream(self, *, symbol: str, timeframe: str) -> AsyncIterator[Candle]:
        for c in self._candles:
            yield c


class _AcloseRecordingSource:
    """Non-generator CandleSource with an explicit aclose() — lets us assert
    the runtime finalises the source. (A generator runs its finally on
    natural exhaustion regardless, which would hide the runtime's aclose.)"""

    def __init__(self, candles: list[Candle]) -> None:
        self._candles = candles
        self.aclose_called = False

    def stream(self, *, symbol: str, timeframe: str) -> AsyncIterator[Candle]:
        self._it = iter(self._candles)
        return self

    def __aiter__(self) -> AsyncIterator[Candle]:
        return self

    async def __anext__(self) -> Candle:
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration from None

    async def aclose(self) -> None:
        self.aclose_called = True


# ── Strategy fixtures ───────────────────────────────────────────


def _market_buy_on_first_tick():
    """Strategy that buys 0.01 on the FIRST candle, then idles.

    Deterministic — exactly one trade per fresh closure.
    """
    state = {"fired": False}

    def on_tick(ctx, candle):
        if state["fired"]:
            return None
        state["fired"] = True
        return ctx.order_intent(side="buy", qty=Decimal("0.01"), type="market")

    return on_tick


def _gtc_limit_buy():
    """Emits a GTC LIMIT once. The SimOrderRouter v1 should REJECT."""
    state = {"fired": False}

    def on_tick(ctx, candle):
        if state["fired"]:
            return None
        state["fired"] = True
        return ctx.order_intent(
            side="buy",
            qty=Decimal("0.01"),
            type="limit",
            price=Decimal("50"),  # far below market — would be GTC pending
            time_in_force="GTC",
        )

    return on_tick


def _ioc_limit_crosses():
    """IOC LIMIT BUY at a price ABOVE the candle's low (so it crosses
    immediately) — should fill on the same bar."""
    state = {"fired": False}

    def on_tick(ctx, candle):
        if state["fired"]:
            return None
        state["fired"] = True
        # candle.low == close (flat candle); set limit = close so it
        # crosses.
        return ctx.order_intent(
            side="buy",
            qty=Decimal("0.01"),
            type="limit",
            price=candle.close,
            time_in_force="IOC",
        )

    return on_tick


def _ioc_limit_misses():
    """IOC LIMIT BUY at a price FAR BELOW current — should NOT cross,
    should be cancelled by the simulated router."""
    state = {"fired": False}

    def on_tick(ctx, candle):
        if state["fired"]:
            return None
        state["fired"] = True
        return ctx.order_intent(
            side="buy",
            qty=Decimal("0.01"),
            type="limit",
            price=candle.close / 2,  # half — won't cross
            time_in_force="IOC",
        )

    return on_tick


# ── Tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_runtime_processes_all_candles() -> None:
    """Every yielded candle gets observed; counts match."""
    candles = _ramp(10)
    runtime = StrategyRuntime(
        strategy_fn=lambda ctx, c: None,  # no-op strategy
        candle_source=_ListCandleSource(candles),
        order_router=SimOrderRouter(),
        symbol="BTC/USDT",
        timeframe="1m",
        initial_capital=Decimal("1000"),
    )
    result = await runtime.run_until_complete()
    assert result.candles_processed == 10
    assert len(result.equity_curve) == 10
    assert result.intents_emitted == 0  # no-op strategy → no intents
    assert result.fills == []
    assert result.rejected == []


@pytest.mark.asyncio
async def test_runtime_finalises_candle_source() -> None:
    """The runtime aclose()s the source so resource-owning sources
    (WSCandleSource → ExchangeAdapter) release on stop / exhaustion."""
    src = _AcloseRecordingSource(_ramp(3))
    runtime = StrategyRuntime(
        strategy_fn=lambda ctx, c: None,
        candle_source=src,
        order_router=SimOrderRouter(),
        symbol="BTC/USDT",
        timeframe="1m",
    )
    await runtime.run_until_complete()
    assert src.aclose_called


@pytest.mark.asyncio
async def test_market_order_fills_and_records_trade() -> None:
    """MARKET BUY 0.01 on first candle → 1 fill, 1 trade, Portfolio
    cash decreased."""
    candles = _ramp(5)
    runtime = StrategyRuntime(
        strategy_fn=_market_buy_on_first_tick(),
        candle_source=_ListCandleSource(candles),
        order_router=SimOrderRouter(),
        symbol="BTC/USDT",
        timeframe="1m",
        initial_capital=Decimal("1000"),
    )
    result = await runtime.run_until_complete()
    assert result.intents_emitted == 1
    assert len(result.fills) == 1
    assert len(result.trades) == 1
    fill = result.fills[0]
    assert fill.state == "filled"
    assert fill.fill_qty == Decimal("0.01")
    # Final equity ≠ initial capital because we now hold 0.01 BTC
    # whose value follows the price ramp.
    assert result.final_equity != Decimal("1000")


@pytest.mark.asyncio
async def test_gtc_limit_rejected_by_simulated_router_v1() -> None:
    """The v1 SimOrderRouter does NOT implement a pending-order book.
    GTC LIMIT is rejected with an explanatory ``error`` field."""
    candles = _ramp(3)
    runtime = StrategyRuntime(
        strategy_fn=_gtc_limit_buy(),
        candle_source=_ListCandleSource(candles),
        order_router=SimOrderRouter(),
        symbol="BTC/USDT",
        timeframe="1m",
    )
    result = await runtime.run_until_complete()
    assert len(result.fills) == 0
    assert len(result.rejected) == 1
    rej = result.rejected[0]
    assert rej.state == "rejected"
    assert rej.error is not None and "MARKET" in rej.error


@pytest.mark.asyncio
async def test_ioc_limit_fills_when_crossable() -> None:
    """IOC LIMIT at the candle close → crosses → filled at the limit
    price (no slippage on resting price)."""
    candles = _ramp(3)
    runtime = StrategyRuntime(
        strategy_fn=_ioc_limit_crosses(),
        candle_source=_ListCandleSource(candles),
        order_router=SimOrderRouter(),
        symbol="BTC/USDT",
        timeframe="1m",
    )
    result = await runtime.run_until_complete()
    assert len(result.fills) == 1
    assert result.fills[0].state == "filled"


@pytest.mark.asyncio
async def test_ioc_limit_cancelled_when_uncrossable() -> None:
    """IOC LIMIT at half the close price → uncrossable → cancelled
    (NOT pending; NOT rejected with the GTC-style error)."""
    candles = _ramp(3)
    runtime = StrategyRuntime(
        strategy_fn=_ioc_limit_misses(),
        candle_source=_ListCandleSource(candles),
        order_router=SimOrderRouter(),
        symbol="BTC/USDT",
        timeframe="1m",
    )
    result = await runtime.run_until_complete()
    assert len(result.fills) == 0
    assert len(result.rejected) == 1
    assert result.rejected[0].state == "cancelled"


# ── Event hook ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_event_hook_fires_in_expected_order() -> None:
    """For one buy-and-hold across 3 candles we expect:
       3 × candle, 1 × intent, 1 × fill, 3 × equity
    The order on bar 0 is: candle → intent → fill → equity.
    On bars 1-2: candle → equity (no intent/fill)."""
    events: list[RuntimeEvent] = []

    async def hook(ev: RuntimeEvent) -> None:
        events.append(ev)

    candles = _ramp(3)
    runtime = StrategyRuntime(
        strategy_fn=_market_buy_on_first_tick(),
        candle_source=_ListCandleSource(candles),
        order_router=SimOrderRouter(),
        symbol="BTC/USDT",
        timeframe="1m",
        event_hook=hook,
    )
    await runtime.run_until_complete()
    kinds = [e.kind for e in events]
    # Bar 0: candle, intent, fill, equity
    # Bar 1: candle, equity
    # Bar 2: candle, equity
    assert kinds == [
        "candle",
        "intent",
        "fill",
        "equity",
        "candle",
        "equity",
        "candle",
        "equity",
    ]


@pytest.mark.asyncio
async def test_event_hook_exception_does_not_break_loop() -> None:
    """A broken observability hook must NEVER break the trading
    loop. Hook exceptions are caught and logged; the runtime still
    processes every candle."""
    call_count = {"n": 0}

    async def broken_hook(ev: RuntimeEvent) -> None:
        call_count["n"] += 1
        raise RuntimeError("observability broke; ignore me")

    candles = _ramp(3)
    runtime = StrategyRuntime(
        strategy_fn=lambda ctx, c: None,
        candle_source=_ListCandleSource(candles),
        order_router=SimOrderRouter(),
        symbol="BTC/USDT",
        timeframe="1m",
        event_hook=broken_hook,
    )
    result = await runtime.run_until_complete()
    # All 3 candles processed despite hook raising every time.
    assert result.candles_processed == 3
    assert call_count["n"] > 0  # hook was actually called


# ── Cross-mode parity (runtime ≈ backtest) ───────────────────────


@pytest.mark.asyncio
async def test_runtime_matches_backtest_on_same_input() -> None:
    """Hardest invariant to hold: dry-run and backtest must produce
    the same trades + equity for the same strategy + candles +
    fee/slippage models.

    We deliberately use the DEFAULT ``ConstantBpsFee`` and
    ``ConstantBpsSlippage`` in both — the SimOrderRouter and
    BacktestEngine both default to those, so the cross-mode delta
    should be zero.
    """
    candles = _ramp(10)

    # Backtest
    bt_strat = _market_buy_on_first_tick()
    bt = BacktestEngine(strategy_fn=bt_strat, initial_capital=Decimal("1000"))
    bt_result = bt.run(candles, symbol="BTC/USDT", timeframe="1m")

    # Runtime (fresh strategy closure — state must NOT leak)
    rt_strat = _market_buy_on_first_tick()
    runtime = StrategyRuntime(
        strategy_fn=rt_strat,
        candle_source=_ListCandleSource(candles),
        order_router=SimOrderRouter(),
        symbol="BTC/USDT",
        timeframe="1m",
        initial_capital=Decimal("1000"),
    )
    rt_result = await runtime.run_until_complete()

    # Trade counts match
    assert len(rt_result.trades) == len(bt_result.trades)
    # Same prices, qtys, fees on the matching trade
    for rt_t, bt_t in zip(rt_result.trades, bt_result.trades, strict=True):
        assert rt_t.price == bt_t.price
        assert rt_t.qty == bt_t.qty
        assert rt_t.fee == bt_t.fee
        assert rt_t.realized_pnl == bt_t.realized_pnl
    # Final equity matches
    assert rt_result.final_equity == bt_result.equity_curve[-1][1]


# ── Insufficient-cash safety ─────────────────────────────────────


@pytest.mark.asyncio
async def test_insufficient_cash_buy_surfaces_as_rejected() -> None:
    """Buy 1 BTC at $100 candle close with only $50 cash → Portfolio
    raises ValueError. The runtime catches it and records a rejected
    fill instead of crashing."""

    def overbuy_strategy(ctx, candle):
        # Static qty — buys way more than $50 of cash can afford.
        return ctx.order_intent(side="buy", qty=Decimal("1.0"), type="market")

    candles = _ramp(1)
    runtime = StrategyRuntime(
        strategy_fn=overbuy_strategy,
        candle_source=_ListCandleSource(candles),
        order_router=SimOrderRouter(),
        symbol="BTC/USDT",
        timeframe="1m",
        initial_capital=Decimal("50"),
    )
    result = await runtime.run_until_complete()
    assert result.fills == []
    assert len(result.rejected) == 1
    assert "portfolio refused" in (result.rejected[0].error or "")


# ── Empty stream ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_stream_returns_zero_result() -> None:
    """A candle source that yields nothing → 0 processed, equity
    equals untouched initial cash. No exception."""
    runtime = StrategyRuntime(
        strategy_fn=lambda ctx, c: None,
        candle_source=_ListCandleSource([]),
        order_router=SimOrderRouter(),
        symbol="BTC/USDT",
        timeframe="1m",
        initial_capital=Decimal("1000"),
    )
    result = await runtime.run_until_complete()
    assert result.candles_processed == 0
    assert result.equity_curve == []
    # No trades happened — Portfolio still holds full cash, no
    # position, so equity = cash regardless of the (zero) mark price.
    assert result.final_equity == Decimal("1000")
