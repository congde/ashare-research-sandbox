"""Tests for the long-running StrategyRunner daemon.

The runner adds three things on top of :class:`StrategyRuntime`:

  1. **Lifecycle**: ``start()`` / ``stop()`` semantics, idempotent
     shutdown, asyncio task management
  2. **Restart policy**: fail_fast / restart / graceful — each maps
     differently to (clean exit, crash) outcomes
  3. **Health snapshots**: non-blocking observability for HTTP

We test each concern in isolation with the smallest possible
runtime/source fakes, then a few end-to-end paths.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.domain.market_data import Candle
from app.strategy_engine.runtime import (
    HealthSnapshot,
    RestartPolicy,
    RunnerState,
    SimOrderRouter,
    StrategyRunner,
    StrategyRuntime,
    make_runtime_factory,
)
from app.strategy_engine.runtime.protocol import CandleSource

# ── Tiny fakes ───────────────────────────────────────────────────


def _candle(i: int) -> Candle:
    p = Decimal("100.0")
    return Candle(
        exchange="test",
        symbol="BTC/USDT",
        timeframe="1m",
        ts=datetime(2026, 5, 16, 0, i, tzinfo=UTC),
        open=p, high=p, low=p, close=p,
        volume=Decimal("1.0"),
    )


class _ListSource(CandleSource):
    """Yields N candles then exits cleanly. The simplest finite
    candle stream."""

    def __init__(self, n: int) -> None:
        self._n = n

    async def stream(self, *, symbol: str, timeframe: str) -> AsyncIterator[Candle]:
        for i in range(self._n):
            yield _candle(i)


class _CrashingSource(CandleSource):
    """Yields candles then raises a RuntimeError on the Nth iteration.
    Used to test the crash-handling branches of the supervisor."""

    def __init__(self, n_before_crash: int) -> None:
        self._n = n_before_crash

    async def stream(self, *, symbol: str, timeframe: str) -> AsyncIterator[Candle]:
        for i in range(self._n):
            yield _candle(i)
        raise RuntimeError("simulated WS disconnect")


# ── Constructor validation ──────────────────────────────────────


def test_negative_max_restarts_rejected() -> None:
    """Operator misconfig — fail loud."""
    with pytest.raises(ValueError, match="max_restarts"):
        StrategyRunner(
            runtime_factory=lambda: _noop_runtime(),  # never invoked
            max_restarts=-1,
        )


def test_negative_backoff_rejected() -> None:
    with pytest.raises(ValueError, match="backoff_seconds"):
        StrategyRunner(
            runtime_factory=lambda: _noop_runtime(),
            backoff_seconds=-0.1,
        )


def _noop_runtime() -> StrategyRuntime:
    """Trivial runtime — used only as a placeholder when the factory
    won't actually be invoked. Returning a real-ish instance keeps
    type checkers happy."""
    return StrategyRuntime(
        strategy_fn=lambda ctx, c: None,
        candle_source=_ListSource(0),
        order_router=SimOrderRouter(),
        symbol="BTC/USDT",
        timeframe="1m",
    )


# ── Lifecycle: start / stop / state transitions ──────────────────


@pytest.mark.asyncio
async def test_initial_state_is_created() -> None:
    runner = StrategyRunner(runtime_factory=lambda: _noop_runtime())
    assert runner.state == RunnerState.CREATED


@pytest.mark.asyncio
async def test_start_then_clean_exit_transitions_to_stopped() -> None:
    """Finite stream + fail_fast policy → CREATED → STARTING →
    RUNNING → STOPPED (after stream exhausts).

    The runner's STARTING state is brief (only inside ``start()``);
    we don't pin it directly — pinning the final state is sufficient
    for the test contract.
    """
    factory = make_runtime_factory(
        strategy_fn=lambda ctx, c: None,
        candle_source=_ListSource(3),
        order_router=SimOrderRouter(),
        symbol="BTC/USDT",
        timeframe="1m",
    )
    runner = StrategyRunner(
        runtime_factory=factory,
        restart_policy=RestartPolicy.FAIL_FAST,
    )
    await runner.start()
    assert runner._task is not None
    await runner._task  # wait for natural completion
    assert runner.state == RunnerState.STOPPED


@pytest.mark.asyncio
async def test_starting_twice_raises() -> None:
    """Idempotency: start() while already running is a programmer
    error — fail loud rather than spawn a second task."""
    factory = make_runtime_factory(
        strategy_fn=lambda ctx, c: None,
        candle_source=_ListSource(100),  # long enough to be running
        order_router=SimOrderRouter(),
        symbol="BTC/USDT",
        timeframe="1m",
    )
    runner = StrategyRunner(runtime_factory=factory)
    await runner.start()
    try:
        with pytest.raises(RuntimeError, match="cannot start"):
            await runner.start()
    finally:
        await runner.stop()


@pytest.mark.asyncio
async def test_stop_is_idempotent_on_stopped_runner() -> None:
    """stop() called twice → no exception. Same applies to stop()
    on a never-started runner."""
    runner = StrategyRunner(runtime_factory=lambda: _noop_runtime())
    await runner.stop()  # never started
    await runner.stop()  # twice
    assert runner.state == RunnerState.CREATED  # still created — never started


# ── Restart policy: FAIL_FAST ───────────────────────────────────


@pytest.mark.asyncio
async def test_fail_fast_terminates_on_clean_exit() -> None:
    """Finite stream exhausts → state=STOPPED, no restart."""
    factory = make_runtime_factory(
        strategy_fn=lambda ctx, c: None,
        candle_source=_ListSource(2),
        order_router=SimOrderRouter(),
        symbol="BTC/USDT",
        timeframe="1m",
    )
    runner = StrategyRunner(
        runtime_factory=factory,
        restart_policy=RestartPolicy.FAIL_FAST,
    )
    await runner.start()
    await runner._task
    assert runner.state == RunnerState.STOPPED
    assert runner.health().restart_count == 0


@pytest.mark.asyncio
async def test_fail_fast_terminates_on_crash_with_failed_state() -> None:
    """Crashing stream → state=FAILED, last_error set."""
    factory = make_runtime_factory(
        strategy_fn=lambda ctx, c: None,
        candle_source=_CrashingSource(2),
        order_router=SimOrderRouter(),
        symbol="BTC/USDT",
        timeframe="1m",
    )
    runner = StrategyRunner(
        runtime_factory=factory,
        restart_policy=RestartPolicy.FAIL_FAST,
    )
    await runner.start()
    await runner._task
    assert runner.state == RunnerState.FAILED
    assert "simulated WS disconnect" in (runner.health().last_error or "")
    assert runner.health().restart_count == 0


# ── Restart policy: RESTART ──────────────────────────────────────


@pytest.mark.asyncio
async def test_restart_policy_resumes_after_crash_until_max() -> None:
    """RESTART policy with max_restarts=2 + a source that crashes
    every iteration → 3 attempts (initial + 2 restarts) → FAILED.

    Each restart bumps the counter; the third crash exhausts and
    the runner gives up. We use a tiny backoff so the test is fast.
    """
    factory = make_runtime_factory(
        strategy_fn=lambda ctx, c: None,
        candle_source=_CrashingSource(1),  # crash on second iter
        order_router=SimOrderRouter(),
        symbol="BTC/USDT",
        timeframe="1m",
    )
    runner = StrategyRunner(
        runtime_factory=factory,
        restart_policy=RestartPolicy.RESTART,
        max_restarts=2,
        backoff_seconds=0.0,
    )
    await runner.start()
    await runner._task
    assert runner.state == RunnerState.FAILED
    # restart_count counts ATTEMPTS BEYOND the initial run.
    # initial crash → restart_count=1; second crash → 2;
    # third crash → 3 > max_restarts(2) → FAILED.
    assert runner.health().restart_count == 3


@pytest.mark.asyncio
async def test_restart_policy_recovers_when_runtime_eventually_stable() -> None:
    """Once a restart succeeds (stream ends cleanly), RESTART policy
    keeps re-spawning even after a clean exit (production strategies
    are forever-running).

    To bound the test we use max_restarts=1 + a non-crashing source —
    initial run ends → restart 1 → ends → restart_count exceeds → FAILED.

    NOTE: This shape may surprise — \"keeps restarting\" is the point.
    Operators who want \"run once then stop\" should use FAIL_FAST.
    """
    factory = make_runtime_factory(
        strategy_fn=lambda ctx, c: None,
        candle_source=_ListSource(1),
        order_router=SimOrderRouter(),
        symbol="BTC/USDT",
        timeframe="1m",
    )
    runner = StrategyRunner(
        runtime_factory=factory,
        restart_policy=RestartPolicy.RESTART,
        max_restarts=1,
        backoff_seconds=0.0,
    )
    await runner.start()
    await runner._task
    assert runner.state == RunnerState.FAILED  # max_restarts exhausted
    assert runner.health().restart_count == 2


# ── Restart policy: GRACEFUL ─────────────────────────────────────


@pytest.mark.asyncio
async def test_graceful_terminates_on_clean_exit_without_restarting() -> None:
    """GRACEFUL: clean source exhaustion → STOPPED (no auto-restart).
    Crashes still → FAILED. Distinguishes from RESTART (which would
    re-spawn even on clean exit).
    """
    factory = make_runtime_factory(
        strategy_fn=lambda ctx, c: None,
        candle_source=_ListSource(2),
        order_router=SimOrderRouter(),
        symbol="BTC/USDT",
        timeframe="1m",
    )
    runner = StrategyRunner(
        runtime_factory=factory,
        restart_policy=RestartPolicy.GRACEFUL,
    )
    await runner.start()
    await runner._task
    assert runner.state == RunnerState.STOPPED
    assert runner.health().restart_count == 0


@pytest.mark.asyncio
async def test_graceful_terminates_on_crash_as_failed() -> None:
    """GRACEFUL on crash → FAILED (graceful only tolerates clean
    exits, not crashes)."""
    factory = make_runtime_factory(
        strategy_fn=lambda ctx, c: None,
        candle_source=_CrashingSource(1),
        order_router=SimOrderRouter(),
        symbol="BTC/USDT",
        timeframe="1m",
    )
    runner = StrategyRunner(
        runtime_factory=factory,
        restart_policy=RestartPolicy.GRACEFUL,
    )
    await runner.start()
    await runner._task
    assert runner.state == RunnerState.FAILED


# ── Health snapshot ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_snapshot_returns_immutable_shape() -> None:
    """Frozen dataclass — must not be assignable. Pins the immutable
    contract the HTTP layer relies on."""
    runner = StrategyRunner(runtime_factory=lambda: _noop_runtime())
    snap = runner.health()
    assert isinstance(snap, HealthSnapshot)
    with pytest.raises((AttributeError, TypeError)):
        snap.state = RunnerState.RUNNING  # type: ignore[misc]


@pytest.mark.asyncio
async def test_health_accumulates_event_counts() -> None:
    """After a run with 3 candles + 1 intent + 1 fill, the snapshot
    reflects those counters."""
    # Strategy that buys once.
    state = {"fired": False}

    def on_tick(ctx, candle):
        if state["fired"]:
            return None
        state["fired"] = True
        return ctx.order_intent(side="buy", qty=Decimal("0.001"), type="market")

    factory = make_runtime_factory(
        strategy_fn=on_tick,
        candle_source=_ListSource(3),
        order_router=SimOrderRouter(),
        symbol="BTC/USDT",
        timeframe="1m",
        initial_capital=Decimal("1000"),
    )
    runner = StrategyRunner(
        runtime_factory=factory, restart_policy=RestartPolicy.FAIL_FAST,
    )
    await runner.start()
    await runner._task

    snap = runner.health()
    assert snap.candles_processed == 3
    assert snap.intents_emitted == 1
    assert snap.fills == 1
    assert snap.rejected == 0
    # equity tracked from the equity events
    assert snap.equity > 0


@pytest.mark.asyncio
async def test_user_event_hook_chained_with_stats_hook() -> None:
    """Caller's event_hook (installed at runtime construction time)
    must still fire on every event — the runner composes a stats
    updater BEFORE the user hook, not in place of it."""
    user_events: list[str] = []

    async def user_hook(event):
        user_events.append(event.kind)

    factory = make_runtime_factory(
        strategy_fn=lambda ctx, c: None,
        candle_source=_ListSource(2),
        order_router=SimOrderRouter(),
        symbol="BTC/USDT",
        timeframe="1m",
        event_hook=user_hook,
    )
    runner = StrategyRunner(
        runtime_factory=factory, restart_policy=RestartPolicy.FAIL_FAST,
    )
    await runner.start()
    await runner._task

    # 2 candles → 2 candle + 2 equity events (no intents/fills with
    # the no-op strategy).
    assert user_events.count("candle") == 2
    assert user_events.count("equity") == 2


# ── Stop semantics ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stop_during_run_transitions_to_stopped() -> None:
    """A long-running stream + stop() → state=STOPPED.

    The current ``run_until_complete`` doesn't observe the stop event
    mid-stream (it drains the source). So with an INFINITE source,
    stop() would have to cancel the task. We use a slow finite
    source to keep the test deterministic.
    """

    class _SlowSource(CandleSource):
        async def stream(self, *, symbol: str, timeframe: str) -> AsyncIterator[Candle]:
            for i in range(50):
                await asyncio.sleep(0.001)
                yield _candle(i)

    factory = make_runtime_factory(
        strategy_fn=lambda ctx, c: None,
        candle_source=_SlowSource(),
        order_router=SimOrderRouter(),
        symbol="BTC/USDT",
        timeframe="1m",
    )
    runner = StrategyRunner(
        runtime_factory=factory, restart_policy=RestartPolicy.FAIL_FAST,
    )
    await runner.start()
    # Let a few candles flow.
    await asyncio.sleep(0.01)
    # Now stop — should transition cleanly.
    await runner.stop(timeout=2.0)
    assert runner.state == RunnerState.STOPPED


@pytest.mark.asyncio
async def test_stop_cancels_unresponsive_task() -> None:
    """A task that won't honor the stop event within timeout is
    cancelled. State ends as STOPPED regardless."""

    class _BlockingSource(CandleSource):
        async def stream(self, *, symbol: str, timeframe: str) -> AsyncIterator[Candle]:
            # Sleep for a long time (longer than the test timeout)
            # — stop() must cancel us.
            await asyncio.sleep(60.0)
            yield _candle(0)  # never reached

    factory = make_runtime_factory(
        strategy_fn=lambda ctx, c: None,
        candle_source=_BlockingSource(),
        order_router=SimOrderRouter(),
        symbol="BTC/USDT",
        timeframe="1m",
    )
    runner = StrategyRunner(
        runtime_factory=factory, restart_policy=RestartPolicy.FAIL_FAST,
    )
    await runner.start()
    await asyncio.sleep(0.01)
    await runner.stop(timeout=0.2)
    assert runner.state == RunnerState.STOPPED


# ── Convenience factory ─────────────────────────────────────────


def test_make_runtime_factory_returns_distinct_instances() -> None:
    """``make_runtime_factory`` must produce a callable that yields a
    FRESH runtime each call — restarts depend on this for isolation."""
    factory = make_runtime_factory(
        strategy_fn=lambda ctx, c: None,
        candle_source=_ListSource(1),
        order_router=SimOrderRouter(),
        symbol="BTC/USDT",
        timeframe="1m",
    )
    a = factory()
    b = factory()
    assert a is not b
    assert isinstance(a, StrategyRuntime)
    assert isinstance(b, StrategyRuntime)


def test_runner_age_zero_when_never_started() -> None:
    """Helper: age = 0 when started_at is None. Avoids spurious
    'strategy is X seconds old' on the dashboard before first
    start."""
    from app.strategy_engine.runtime import runner_age_seconds

    snap = HealthSnapshot(
        state=RunnerState.CREATED,
        started_at=None,
        last_event_at=None,
        last_error=None,
        restart_count=0,
        candles_processed=0,
        intents_emitted=0,
        fills=0,
        rejected=0,
        equity=Decimal("0"),
    )
    assert runner_age_seconds(snap) == 0.0
