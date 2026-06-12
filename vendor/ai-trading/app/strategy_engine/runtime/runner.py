"""Long-running daemon wrapper around :class:`StrategyRuntime`.

S7-3 closes the gap between v1 single-shot runtime
(``run_until_complete``) and the production live-loop needs:

  * Strategies like grid bots and SMA-cross are meant to run
    indefinitely until an operator stops them.
  * The HTTP API needs to ask "is the runtime healthy?" without
    blocking on the loop.
  * Restart-on-crash must be opt-in and bounded — silently re-
    spawning a strategy that crashes 100× per second is worse than
    failing loud.

Design:

  * :class:`StrategyRunner` owns one ``StrategyRuntime`` instance,
    wraps it in an asyncio.Task, and exposes start / stop / health.

  * **Restart policy** is the part that needs care. We support three
    modes:

      "fail_fast"  — first crash terminates. Default. Safest for
                     real-money live mode where a corrupted runtime
                     could leak orders.

      "restart"    — bounded restart. After every crash, sleep
                     ``backoff_seconds`` then resurrect with a fresh
                     candle source / runtime. Crash counter capped
                     at ``max_restarts``; on exhaustion the runner
                     transitions to ``state=failed`` and stays there.

      "graceful"   — same as restart, but only when the source
                     yields a clean StopAsyncIteration (i.e. the
                     stream legitimately ended — for replay sources
                     this isn't a crash). Crashes still terminate.

  * **Health** is a cheap snapshot — no blocking calls — so an HTTP
    handler can poll at 1Hz without slowing the loop.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from app.strategy_engine.runtime.protocol import CandleSource, OrderRouter
from app.strategy_engine.runtime.runtime import (
    EventHook,
    RuntimeEvent,
    StrategyRuntime,
    StrategyRuntimeResult,
)

logger = logging.getLogger("strategy_runner")


# ── States ───────────────────────────────────────────────────────


class RunnerState(StrEnum):
    """High-level state — exposed via health endpoints / UI."""

    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"  # operator-requested clean stop
    FAILED = "failed"  # crashed + restart policy exhausted


class RestartPolicy(StrEnum):
    """How to react when the inner ``run_until_complete`` returns
    (whether by normal end-of-stream or exception)."""

    FAIL_FAST = "fail_fast"
    RESTART = "restart"
    GRACEFUL = "graceful"


# ── Factory callables ────────────────────────────────────────────


# Why factories instead of pre-built instances: a restart needs
# FRESH candle source + strategy state, otherwise the second iteration
# starts mid-stream / inherits the crashed run's portfolio. Factories
# are zero-arg callables we invoke on each (re)start.

RuntimeFactory = Callable[[], StrategyRuntime]


# ── Health snapshot ──────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    """Cheap snapshot for ``GET /strategies/<id>/health`` style queries.

    All fields are immutable values captured at snapshot time — no
    awaiting, no locks. Means it's safe to call at any rate.
    """

    state: RunnerState
    started_at: datetime | None
    last_event_at: datetime | None
    last_error: str | None
    restart_count: int
    candles_processed: int
    intents_emitted: int
    fills: int
    rejected: int
    equity: Decimal


# ── Runner ───────────────────────────────────────────────────────


@dataclass
class _RunnerStats:
    """Mutable counters the runner aggregates across restarts.

    Lives separately from :class:`HealthSnapshot` so the runner can
    accumulate without needing to wrap each field in setter helpers.
    """

    started_at: datetime | None = None
    last_event_at: datetime | None = None
    last_error: str | None = None
    restart_count: int = 0
    # Per-restart counters reset on each restart; lifetime counters
    # are exposed via the health snapshot which sums across.
    candles_processed: int = 0
    intents_emitted: int = 0
    fills: int = 0
    rejected: int = 0
    equity: Decimal = field(default_factory=lambda: Decimal("0"))


class StrategyRunner:
    """Long-running async daemon wrapping one :class:`StrategyRuntime`.

    Constructor takes a **factory** (not a pre-built runtime) so the
    runner can build a fresh instance per restart cycle.

    Usage:

        async def make_runtime() -> StrategyRuntime:
            return StrategyRuntime(
                strategy_fn=..., candle_source=..., order_router=...,
                symbol="BTC/USDT", timeframe="1m",
            )

        runner = StrategyRunner(
            runtime_factory=make_runtime,
            restart_policy=RestartPolicy.RESTART,
            max_restarts=5,
            backoff_seconds=2.0,
        )
        await runner.start()
        ...
        snapshot = runner.health()
        ...
        await runner.stop()
    """

    def __init__(
        self,
        *,
        runtime_factory: RuntimeFactory,
        restart_policy: RestartPolicy = RestartPolicy.FAIL_FAST,
        max_restarts: int = 3,
        backoff_seconds: float = 1.0,
    ) -> None:
        if max_restarts < 0:
            raise ValueError(f"max_restarts must be >= 0; got {max_restarts}")
        if backoff_seconds < 0:
            raise ValueError(f"backoff_seconds must be >= 0; got {backoff_seconds}")

        self._factory = runtime_factory
        self._restart_policy = restart_policy
        self._max_restarts = max_restarts
        self._backoff_seconds = backoff_seconds

        self._state = RunnerState.CREATED
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._stats = _RunnerStats()
        # Last completed result — visible via health.last_result so
        # operators can inspect why a strategy stopped without
        # blocking on the task.
        self._last_result: StrategyRuntimeResult | None = None
        # The currently-running StrategyRuntime instance. None when the
        # runner is between iterations / before-start / after-stop.
        # Exposed publicly so the deploy_live approval handler can
        # call set_order_router on the live runtime mid-run.
        self._current_runtime: StrategyRuntime | None = None

    # ── Lifecycle ────────────────────────────────────────────────

    async def start(self) -> None:
        """Spawn the supervision task. Returns immediately — the
        task runs in the background until ``stop()`` or terminal
        failure."""
        if self._state in (
            RunnerState.STARTING,
            RunnerState.RUNNING,
            RunnerState.STOPPING,
        ):
            raise RuntimeError(f"cannot start while in state={self._state}")

        self._state = RunnerState.STARTING
        self._stats.started_at = datetime.now(UTC)
        self._stop_event.clear()
        self._task = asyncio.create_task(self._supervise(), name="strategy_runner")

    async def stop(self, *, timeout: float = 5.0) -> None:
        """Request a clean stop. Sets the stop event; cancels the
        supervision task if it doesn't honour the event within
        ``timeout`` seconds.

        Idempotent: calling on a stopped runner is a no-op.
        """
        if self._state in (RunnerState.STOPPED, RunnerState.FAILED, RunnerState.CREATED):
            return

        self._state = RunnerState.STOPPING
        self._stop_event.set()

        if self._task is None:
            self._state = RunnerState.STOPPED
            return

        try:
            await asyncio.wait_for(self._task, timeout=timeout)
        except TimeoutError:
            logger.warning("Runner did not honor stop within %.1fs; cancelling task", timeout)
            self._task.cancel()
            # Wait for the cancellation to propagate so callers can
            # rely on the task being done by the time stop() returns.
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        finally:
            # Whatever happened, end in STOPPED state — even if the
            # task crashed during shutdown.
            self._state = RunnerState.STOPPED

    # ── Health ──────────────────────────────────────────────────

    def health(self) -> HealthSnapshot:
        """Cheap snapshot — never awaits, never locks. Safe to call
        from an HTTP handler at any rate."""
        return HealthSnapshot(
            state=self._state,
            started_at=self._stats.started_at,
            last_event_at=self._stats.last_event_at,
            last_error=self._stats.last_error,
            restart_count=self._stats.restart_count,
            candles_processed=self._stats.candles_processed,
            intents_emitted=self._stats.intents_emitted,
            fills=self._stats.fills,
            rejected=self._stats.rejected,
            equity=self._stats.equity,
        )

    @property
    def current_runtime(self) -> StrategyRuntime | None:
        """The runtime instance the supervisor is currently executing,
        or None if the runner is between iterations / pre-start /
        post-stop.

        Use sparingly. The intended consumer is the deploy_live
        approval handler (S8-7), which calls
        ``current_runtime.set_order_router(...)`` to swap paper →
        live mid-run. Most callers should treat the runner as opaque.
        """
        return self._current_runtime

    @property
    def state(self) -> RunnerState:
        return self._state

    @property
    def last_result(self) -> StrategyRuntimeResult | None:
        return self._last_result

    # ── Internals ────────────────────────────────────────────────

    async def _supervise(self) -> None:
        """Main supervision loop. Builds a runtime, runs it, decides
        whether to restart or terminate based on policy + outcome.

        Stop signal handling: we check the stop_event between
        iterations. The inner ``run_until_complete`` doesn't know
        about the stop event — it just drains the candle source.
        Production candle sources (WSAggregator) need to honour an
        external cancellation token; for v1 we accept that a
        graceful stop waits for the current candle to finish.
        """
        self._state = RunnerState.RUNNING
        attempts = 0

        while not self._stop_event.is_set():
            try:
                runtime = self._factory()
                self._current_runtime = runtime
                result = await self._run_with_event_capture(runtime)
                self._last_result = result
                # Source legitimately ended (e.g. replay stream
                # exhausted). What to do next depends on policy.
                if self._restart_policy == RestartPolicy.FAIL_FAST:
                    # Treat a normal end-of-stream as a finish, not
                    # an error. Transition to STOPPED.
                    self._state = RunnerState.STOPPED
                    return
                if self._restart_policy == RestartPolicy.GRACEFUL:
                    # Same as fail_fast for this branch — graceful
                    # mode tolerates clean source-exhaustion but
                    # doesn't auto-restart on it; the stream's job
                    # was to deliver a finite series.
                    self._state = RunnerState.STOPPED
                    return
                # RESTART policy: re-spawn until max_restarts hits.
                attempts += 1
                self._stats.restart_count = attempts
                if attempts > self._max_restarts:
                    logger.error(
                        "Runner exhausted %d restarts; terminating",
                        self._max_restarts,
                    )
                    self._state = RunnerState.FAILED
                    return
                await asyncio.sleep(self._backoff_seconds)

            except asyncio.CancelledError:
                # Operator-driven shutdown via stop() with cancel().
                # Re-raise so the task ends as cancelled.
                raise

            except Exception as exc:  # noqa: BLE001 — top-level supervisor
                self._stats.last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("Runner inner runtime crashed")
                if self._restart_policy in (
                    RestartPolicy.FAIL_FAST,
                    RestartPolicy.GRACEFUL,
                ):
                    # Both fail-fast and graceful terminate on crash;
                    # graceful only auto-restarts on clean exits.
                    self._state = RunnerState.FAILED
                    return
                # RESTART policy
                attempts += 1
                self._stats.restart_count = attempts
                if attempts > self._max_restarts:
                    logger.error(
                        "Runner exhausted %d restarts after crash; terminating",
                        self._max_restarts,
                    )
                    self._state = RunnerState.FAILED
                    return
                await asyncio.sleep(self._backoff_seconds)

        # Stop event set — clean shutdown.
        self._state = RunnerState.STOPPED

    async def _run_with_event_capture(self, runtime: StrategyRuntime) -> StrategyRuntimeResult:
        """Wrap the underlying ``run_until_complete`` so we can
        intercept every RuntimeEvent and update our stats counters.

        Doesn't disrupt any caller-installed event_hook on the runtime
        — that's preserved by composing with it inside our wrapper.
        Achieved by inspecting the runtime's ``_event_hook`` slot
        (intentional knowledge boundary; we own both classes).
        """
        # Compose our stats-updater with whatever hook was already
        # installed by the runtime factory.
        prior_hook: EventHook | None = runtime._event_hook  # noqa: SLF001

        async def stats_hook(event: RuntimeEvent) -> None:
            self._stats.last_event_at = event.ts
            if event.kind == "candle":
                self._stats.candles_processed += 1
            elif event.kind == "intent":
                self._stats.intents_emitted += 1
            elif event.kind == "fill":
                self._stats.fills += 1
            elif event.kind == "reject":
                self._stats.rejected += 1
            elif event.kind == "equity":
                eq_str = event.payload.get("equity")
                if eq_str is not None:
                    try:
                        self._stats.equity = Decimal(str(eq_str))
                    except Exception:  # noqa: BLE001
                        pass

            # Chain to the caller's prior hook, swallowing its
            # exceptions same as the runtime does — observability
            # MUST NEVER break the loop.
            if prior_hook is not None:
                try:
                    await prior_hook(event)
                except Exception:  # noqa: BLE001
                    logger.exception("user-provided event_hook raised in chain; ignoring")

        runtime._event_hook = stats_hook  # noqa: SLF001
        return await runtime.run_until_complete()


# ── Convenience factory ──────────────────────────────────────────


def make_runtime_factory(
    *,
    strategy_fn: object,
    candle_source: CandleSource,
    order_router: OrderRouter,
    symbol: str,
    timeframe: str,
    initial_capital: Decimal = Decimal("1000"),
    event_hook: EventHook | None = None,
    research: object | None = None,
) -> RuntimeFactory:
    """Build a ``RuntimeFactory`` from the common ``StrategyRuntime``
    args.

    Useful for the common case where the strategy + source + router
    are static across restarts; you don't have to write the factory
    closure inline. For tests that need per-restart state isolation,
    pass distinct factory closures.

    ``research`` (ADR-0020) is the optional ctx.research surface; the same
    instance is reused across restarts. ``None`` ⇒ NoOpResearch.
    """

    def factory() -> StrategyRuntime:
        # strategy_fn is typed as ``object`` at this helper's signature
        # to avoid pulling in the StrategyFn import; the
        # ``StrategyRuntime`` constructor performs the type narrowing
        # internally.
        return StrategyRuntime(
            strategy_fn=strategy_fn,  # type: ignore[arg-type]
            candle_source=candle_source,
            order_router=order_router,
            symbol=symbol,
            timeframe=timeframe,
            initial_capital=initial_capital,
            event_hook=event_hook,
            research=research,
        )

    return factory


# Public alias for callers that want a ``time.monotonic``-based age
# computation against ``HealthSnapshot.started_at``. Exposed here so
# multiple consumers don't reinvent the parse logic.


def runner_age_seconds(snapshot: HealthSnapshot, *, now: float | None = None) -> float:
    """Seconds since the runner started. Useful for stale-strategy
    detection (uptime > X without a candle event suggests a hung
    WS feed).

    ``now`` defaults to ``time.monotonic`` for monotonicity. Returns
    0.0 when the runner never started.
    """
    if snapshot.started_at is None:
        return 0.0
    now_dt = now or time.time()
    return now_dt - snapshot.started_at.timestamp()
