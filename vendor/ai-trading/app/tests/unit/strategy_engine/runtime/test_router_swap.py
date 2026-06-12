"""Tests for the live-runtime router-swap path (S8-7).

Two surfaces under test:

  1. ``StrategyRuntime.set_order_router(router)`` — pure mutation,
     no IO. Pin: subsequent intents route through the NEW router
     while preserving Portfolio + history.

  2. ``StrategyRunner.current_runtime`` — exposed for the deploy_live
     approval handler. Pin: None pre-start; set during run; cleared
     conceptually post-stop.

We do NOT test the full deploy_live handler here — that's an
integration test against the runtime-registry + env credentials and
belongs in the handler test file. This module tests the **mechanism**
the handler depends on.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.connectors.protocol import OrderIntent
from app.domain.market_data import Candle
from app.strategy_engine.runtime import (
    SimOrderRouter,
    StrategyRunner,
    StrategyRuntime,
)
from app.strategy_engine.runtime.protocol import (
    CandleSource,
    FillReport,
    OrderRouter,
)

# ── Fixtures ────────────────────────────────────────────────────


def _candle(ts: datetime, *, price: float = 100.0) -> Candle:
    p = Decimal(f"{price:.4f}")
    return Candle(
        exchange="test", symbol="BTC/USDT", timeframe="1m",
        ts=ts,
        open=p, high=p, low=p, close=p,
        volume=Decimal("1.0"),
    )


class _ListSource(CandleSource):
    """Yields a pre-built list. Used by tests to drive a finite,
    deterministic candle stream."""

    def __init__(self, candles: list[Candle]) -> None:
        self._candles = candles

    async def stream(self, *, symbol: str, timeframe: str) -> AsyncIterator[Candle]:
        for c in self._candles:
            yield c


class _GatedSource(CandleSource):
    """Yields candles only when an asyncio.Event is set. Lets tests
    pause the runtime between candles so the router can be swapped
    mid-run."""

    def __init__(self, candles: list[Candle], gate: asyncio.Event) -> None:
        self._candles = candles
        self._gate = gate

    async def stream(self, *, symbol: str, timeframe: str) -> AsyncIterator[Candle]:
        for c in self._candles:
            await self._gate.wait()
            yield c


class _TaggingRouter(OrderRouter):
    """Records which router instance handled which intent. Each
    tagged report carries a sentinel so tests can assert which
    router answered."""

    def __init__(self, tag: str) -> None:
        self.tag = tag
        self.intents: list[OrderIntent] = []

    async def submit(
        self, intent: OrderIntent, *, candle: Candle
    ) -> FillReport:
        self.intents.append(intent)
        return FillReport(
            intent=intent,
            state="filled",
            fill_price=candle.close,
            fill_qty=intent.qty,
            fee=Decimal("0"),
            fee_currency="USDT",
            submitted_at=candle.ts,
            filled_at=candle.ts,
            error=f"tag={self.tag}",  # sentinel for assertions
        )


# ── set_order_router: direct mutation ───────────────────────────


def test_set_order_router_replaces_attribute() -> None:
    """The simplest pin — calling set_order_router updates the
    runtime's slot."""
    paper = SimOrderRouter()
    live = _TaggingRouter("live")
    runtime = StrategyRuntime(
        strategy_fn=lambda ctx, c: None,
        candle_source=_ListSource([]),
        order_router=paper,
        symbol="BTC/USDT",
        timeframe="1m",
    )
    assert runtime._order_router is paper  # noqa: SLF001 — direct probe
    runtime.set_order_router(live)
    assert runtime._order_router is live  # noqa: SLF001


# ── End-to-end: pre-swap intents route to OLD; post-swap to NEW ─


@pytest.mark.asyncio
async def test_swap_routes_subsequent_intents_to_new_router() -> None:
    """Drive the runtime to candle 1 with router A, swap to router B,
    drive to candle 2. Assertion: A saw the first intent, B saw the
    second. Portfolio + history unaffected by the swap."""

    # Strategy: BUY 0.001 on EVERY tick (so each candle produces one
    # intent — easy to trace which router got which).
    def always_buy(ctx, candle):
        return ctx.order_intent(side="buy", qty=Decimal("0.001"), type="market")

    router_a = _TaggingRouter("A")
    router_b = _TaggingRouter("B")

    base = datetime(2026, 5, 16, tzinfo=UTC)
    candles = [
        _candle(base, price=100.0),
        _candle(base + timedelta(minutes=1), price=101.0),
    ]

    runtime = StrategyRuntime(
        strategy_fn=always_buy,
        candle_source=_ListSource(candles),
        order_router=router_a,
        symbol="BTC/USDT",
        timeframe="1m",
        initial_capital=Decimal("10000"),  # plenty of cash for both fills
    )

    # Drive candle 0 manually (don't use run_until_complete because
    # we want to swap mid-stream).
    await runtime._process_one(candles[0])  # noqa: SLF001 — test boundary
    assert len(router_a.intents) == 1
    assert len(router_b.intents) == 0

    # Swap. The runtime keeps running; the new router fields next intent.
    runtime.set_order_router(router_b)

    await runtime._process_one(candles[1])  # noqa: SLF001
    assert len(router_a.intents) == 1  # unchanged
    assert len(router_b.intents) == 1


# ── Runner.current_runtime ──────────────────────────────────────


@pytest.mark.asyncio
async def test_current_runtime_is_none_before_start() -> None:
    """Pre-start, the runner has no runtime instance."""

    def factory() -> StrategyRuntime:
        return StrategyRuntime(
            strategy_fn=lambda ctx, c: None,
            candle_source=_ListSource([]),
            order_router=SimOrderRouter(),
            symbol="BTC/USDT",
            timeframe="1m",
        )

    runner = StrategyRunner(runtime_factory=factory)
    assert runner.current_runtime is None


@pytest.mark.asyncio
async def test_current_runtime_set_during_run() -> None:
    """During run, current_runtime is the instance the supervisor
    just constructed. Pin: it's the SAME instance the factory
    returned (no wrapping)."""
    captured: list[StrategyRuntime] = []

    def factory() -> StrategyRuntime:
        rt = StrategyRuntime(
            strategy_fn=lambda ctx, c: None,
            candle_source=_ListSource([_candle(datetime(2026, 5, 16, tzinfo=UTC))]),
            order_router=SimOrderRouter(),
            symbol="BTC/USDT",
            timeframe="1m",
        )
        captured.append(rt)
        return rt

    runner = StrategyRunner(runtime_factory=factory)
    await runner.start()
    # Yield repeatedly so the supervisor task runs through the
    # `_current_runtime = runtime` assignment AND drains the
    # 1-candle source.
    for _ in range(5):
        await asyncio.sleep(0)
        if runner.current_runtime is not None:
            break

    # The runtime the runner's pointing at IS the one factory built.
    assert runner.current_runtime is captured[0]


@pytest.mark.asyncio
async def test_swap_via_runner_current_runtime_works_end_to_end() -> None:
    """Simulates the deploy_live handler flow:
        1. Look up the runner via registry (skipped — direct ref here)
        2. Grab runner.current_runtime
        3. Call current_runtime.set_order_router(new_router)
        4. Verify the next intent routes through the new router

    Pin the END-TO-END handler-relevant path.
    """

    def always_buy(ctx, candle):
        return ctx.order_intent(side="buy", qty=Decimal("0.001"), type="market")

    paper = _TaggingRouter("paper")
    live = _TaggingRouter("live")

    # Gate the candle source so we can swap mid-run.
    gate = asyncio.Event()
    base = datetime(2026, 5, 16, tzinfo=UTC)
    candles = [_candle(base), _candle(base + timedelta(minutes=1))]

    def factory() -> StrategyRuntime:
        return StrategyRuntime(
            strategy_fn=always_buy,
            candle_source=_GatedSource(candles, gate),
            order_router=paper,
            symbol="BTC/USDT",
            timeframe="1m",
            initial_capital=Decimal("10000"),
        )

    runner = StrategyRunner(runtime_factory=factory)
    await runner.start()

    # Let the supervisor reach the source's first await.
    for _ in range(5):
        await asyncio.sleep(0)
        if runner.current_runtime is not None:
            break

    # Release candle 0 → paper router fields the intent.
    gate.set()
    gate.clear()
    for _ in range(5):
        await asyncio.sleep(0)
        if paper.intents:
            break
    assert len(paper.intents) == 1
    assert len(live.intents) == 0

    # Now the operator (in real life: deploy_live handler) swaps.
    runtime = runner.current_runtime
    assert runtime is not None
    runtime.set_order_router(live)

    # Release candle 1 → live router fields the intent.
    gate.set()
    for _ in range(20):
        await asyncio.sleep(0)
        if live.intents:
            break

    assert len(paper.intents) == 1  # unchanged
    assert len(live.intents) == 1   # the swap worked

    await runner.stop()
