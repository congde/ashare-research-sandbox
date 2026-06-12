"""Strategy runtime — async event loop driving the same on_tick
contract as the backtest engine.

What this does:

  1. Subscribes to a :class:`CandleSource` for (symbol, timeframe).
  2. On each candle:
       a. Appends to ``ctx.history``
       b. Calls ``strategy_fn(ctx, candle) -> OrderIntent | None``
       c. If non-None, routes through :class:`OrderRouter`
       d. Updates the Portfolio + equity curve from the FillReport
       e. Emits a :class:`RuntimeEvent` to ``events`` (if hooked)
  3. Returns a :class:`StrategyRuntimeResult` when the candle source
     is exhausted (or on ``run_until_complete`` cancellation).

The runtime is **deterministic for a given candle stream** — same
input → same fills → same equity. This is the property dry-run
replay relies on for "same as backtest" claims.

What this DOES NOT do (yet — S7-2 / S8):

  * **No daemon mode.** ``run_until_complete`` consumes a finite
    stream then returns. Long-running daemons with start/stop/health
    endpoints come with the ACP checkpoint integration.
  * **No multi-symbol.** One runtime instance = one (symbol, timeframe).
    Multi-symbol multiplexing happens at the manager layer above.
  * **No pending-order book.** Strategies that emit GTC LIMIT / STOP
    receive a ``rejected`` FillReport from the simulated router; the
    runtime preserves that in the result but doesn't hold orders open.
  * **No risk gate.** Risk rules (position limit, max DD, kill-switch)
    are S8.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from app.connectors.protocol import OrderIntent, OrderSide
from app.domain.market_data import Candle
from app.strategy_engine.backtest.engine import StrategyContext, StrategyFn
from app.strategy_engine.backtest.models import BacktestTrade
from app.strategy_engine.backtest.portfolio import Portfolio
from app.strategy_engine.runtime.protocol import (
    CandleSource,
    FillReport,
    OrderRouter,
)

if TYPE_CHECKING:
    # Forward refs for runtime hook callable shape. Defining them
    # outside TYPE_CHECKING would require an import that isn't used
    # at runtime.
    pass


logger = logging.getLogger("strategy_runtime")


# ── Event types ──────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    """One observable thing the runtime did this tick.

    ``kind`` is a stable string so consumers (UI websocket, audit
    log) can filter without depending on dataclass identity.

    kinds:
      * ``"candle"``       — new bar arrived; payload = ts of bar
      * ``"intent"``       — strategy returned an OrderIntent
      * ``"fill"``         — order router returned ``state=filled``
      * ``"reject"``       — order router returned non-filled state
      * ``"equity"``       — mark-to-market equity at bar close
    """

    kind: str
    ts: datetime
    payload: dict[str, object] = field(default_factory=dict)


# Async event callback shape. Caller passes one or zero — the runtime
# is silent if none provided. Synchronous callbacks are NOT supported
# (the runtime is async-only).
EventHook = Callable[[RuntimeEvent], Awaitable[None]]


# ── Result ───────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class StrategyRuntimeResult:
    """Snapshot taken when the runtime stops.

    Same shape as ``BacktestResult.trades`` + ``equity_curve`` so a
    dry-run-vs-backtest delta is a one-line diff at the metric layer.
    """

    symbol: str
    timeframe: str
    candles_processed: int
    intents_emitted: int
    fills: list[FillReport]
    rejected: list[FillReport]
    trades: list[BacktestTrade]
    equity_curve: list[tuple[datetime, Decimal]]
    final_equity: Decimal


# ── Runtime ──────────────────────────────────────────────────────


class StrategyRuntime:
    """Drive one strategy callable against one (symbol, timeframe)
    feed.

    The runtime is **single-shot** in v1: construct, ``run_until_complete``,
    inspect the result. Re-running on a fresh stream requires a fresh
    instance — portfolio + equity state intentionally isn't reset.

    Injection points (constructor):
      * ``strategy_fn`` — same shape as ``BacktestEngine.strategy_fn``
      * ``candle_source`` — async stream provider
      * ``order_router`` — submission target
      * ``initial_capital`` — starting cash on the Portfolio
      * ``event_hook`` — optional async callback for observability
      * ``risk_manager`` — optional pre-route safety net (S8)

    All five are dependencies — testing is straight DI without monkey-
    patching.
    """

    def __init__(
        self,
        *,
        strategy_fn: StrategyFn,
        candle_source: CandleSource,
        order_router: OrderRouter,
        symbol: str,
        timeframe: str,
        initial_capital: Decimal = Decimal("1000"),
        event_hook: EventHook | None = None,
        risk_manager: object | None = None,
        research: object | None = None,
    ) -> None:
        self._strategy_fn = strategy_fn
        self._candle_source = candle_source
        self._order_router = order_router
        self._symbol = symbol
        self._timeframe = timeframe
        self._initial_capital = initial_capital
        self._event_hook = event_hook
        # Optional. None ⇒ no risk gate (matches v1 backward compat).
        # Typed as ``object`` to avoid a circular import — the
        # risk_manager module imports from this one (StrategyContext).
        # Duck-typed: the runtime calls .check(intent, ctx=, portfolio=,
        # candle=) regardless of the concrete type.
        self._risk_manager = risk_manager

        # Per-run state. Reset implicitly by constructing a new
        # runtime; we deliberately don't expose a `reset()` method
        # — re-using a runtime for multiple sessions invites
        # silently-leaked state bugs.
        self._portfolio = Portfolio(initial_cash=initial_capital)
        # ``research`` is the strategy-facing ResearchSurface exposed as
        # ctx.research (ADR-0020). ``None`` ⇒ StrategyContext lazy-defaults to
        # NoOpResearch, which raises on any tool call — that's the contract for
        # the backtest engine (deterministic) and any live runner started with
        # the feature flag off. The live ``/start`` path injects a real
        # StrategyResearchAdapter only when DE_LIVE_RESEARCH_ENABLED is set.
        self._ctx = StrategyContext(
            symbol=symbol,
            timeframe=timeframe,
            portfolio=self._portfolio,
            research=research,
        )
        self._trades: list[BacktestTrade] = []
        self._equity_curve: list[tuple[datetime, Decimal]] = []
        self._fills: list[FillReport] = []
        self._rejected: list[FillReport] = []
        self._candles_processed = 0
        self._intents_emitted = 0

    # ── Live mutation (S8-7): paper → live router swap ──────────

    def set_order_router(self, router: OrderRouter) -> None:
        """Swap the order router mid-run.

        Intended for the **deploy_live** approval handler — when a
        paper-trading runtime is promoted to live, the approval gate
        calls this to switch SimOrderRouter → AdapterOrderRouter.

        Subsequent intents route through ``router``. In-flight intents
        (already submitted to the OLD router and awaiting completion)
        are unaffected — the OLD router still returns their FillReport
        and the runtime processes it through the new code path
        (Portfolio update, equity, trade record).

        Why expose this rather than re-construct the runtime: the
        Portfolio + history + equity curve all live inside the runtime
        instance. Re-constructing loses state; mutating the router
        preserves continuity. The fee/slippage models stay attached
        to the new router via dependency injection at router build
        time (caller decides).

        Use sparingly. Routine router changes belong in the constructor;
        this method is the **escape hatch** for the approval-gated
        promotion flow.
        """
        self._order_router = router

    @property
    def risk_manager(self) -> object | None:
        """The injected risk manager, or ``None`` if this runtime runs
        without a risk gate.

        Exposed (read-only) so the **change_threshold** approval handler can
        reach a live runner's ``RiskManager`` and patch a rule's threshold.
        Typed as ``object`` to mirror the constructor's circular-import-safe
        annotation; callers duck-type to ``RiskManager`` (``.patch_threshold``).
        """
        return self._risk_manager

    async def run_until_complete(self) -> StrategyRuntimeResult:
        """Drain the candle source. Returns when the source is
        exhausted (production WS streams aren't typically exhausted
        — for those, the caller wraps this in an asyncio.Task they
        can cancel from outside)."""
        stream = self._candle_source.stream(
            symbol=self._symbol,
            timeframe=self._timeframe,
        )
        try:
            async for candle in stream:
                await self._process_one(candle)
        finally:
            # Finalise the source generator so it releases resources
            # (WSCandleSource closes its ExchangeAdapter). Runs on normal
            # exhaustion AND when the runner cancels this task on stop —
            # aclose() triggers the source's own ``finally``. Best-effort
            # under asyncio cancellation; a non-generator source without
            # aclose is simply skipped.
            aclose = getattr(stream, "aclose", None)
            if aclose is not None:
                await aclose()

        logger.info(
            "Runtime drained: %d candles, %d intents, %d fills, %d rejects, equity=%s",
            self._candles_processed,
            self._intents_emitted,
            len(self._fills),
            len(self._rejected),
            self._portfolio.equity({self._symbol: self._last_close()}),
        )
        return self._build_result()

    async def _process_one(self, candle: Candle) -> None:
        """Single-bar tick: history append → strategy → optional fill
        → mark-to-market.

        Order matches the backtest engine for cross-mode parity. The
        only delta vs backtest is fill timing (real vs simulated) and
        candle source (WS vs canned list)."""
        self._ctx.history.append(candle)
        self._candles_processed += 1
        await self._emit(RuntimeEvent(kind="candle", ts=candle.ts))

        intent = self._strategy_fn(self._ctx, candle)
        if intent is not None:
            self._intents_emitted += 1
            await self._emit(
                RuntimeEvent(
                    kind="intent",
                    ts=candle.ts,
                    payload={
                        "symbol": intent.symbol,
                        "side": intent.side.value,
                        "type": intent.type.value,
                        "qty": str(intent.qty),
                    },
                )
            )
            await self._handle_intent(intent, candle)

        # Mark-to-market at bar close (same as backtest).
        eq = self._portfolio.equity({self._symbol: candle.close})
        self._equity_curve.append((candle.ts, eq))
        self._portfolio.record_equity(candle.ts, {self._symbol: candle.close})
        await self._emit(RuntimeEvent(kind="equity", ts=candle.ts, payload={"equity": str(eq)}))

    async def _handle_intent(self, intent: OrderIntent, candle: Candle) -> None:
        """Route through the order router, update the Portfolio
        from the FillReport, record the trade.

        Pre-route risk gate (S8): if a ``risk_manager`` was injected,
        consult it BEFORE the router. A blocked intent never touches
        the venue — it surfaces as a synthetic FillReport(state=
        "rejected", error="risk_blocked: ...") so downstream stays
        uniform.

        Insufficient-cash / insufficient-position errors from the
        Portfolio surface as ValueError; we catch and log + record a
        rejected fill so the result captures the attempted trade.
        """
        # S8 — pre-route risk check.
        if self._risk_manager is not None:
            verdict = self._risk_manager.check(  # type: ignore[attr-defined]
                intent,
                ctx=self._ctx,
                portfolio=self._portfolio,
                candle=candle,
            )
            if not verdict.allowed:
                synth = FillReport(
                    intent=intent,
                    state="rejected",
                    submitted_at=candle.ts,
                    error=f"risk_blocked[{verdict.rule_id}]: {verdict.reason}",
                )
                self._rejected.append(synth)
                await self._emit(
                    RuntimeEvent(
                        kind="reject",
                        ts=candle.ts,
                        payload={
                            "state": "rejected",
                            "error": synth.error or "",
                            "risk_rule": verdict.rule_id,
                        },
                    )
                )
                return

        report: FillReport = await self._order_router.submit(intent, candle=candle)

        if report.state != "filled":
            self._rejected.append(report)
            await self._emit(
                RuntimeEvent(
                    kind="reject",
                    ts=candle.ts,
                    payload={"state": report.state, "error": report.error or ""},
                )
            )
            return

        # state == "filled"
        if report.fill_price is None or report.fill_qty is None or report.fee is None:
            # Defensive: a "filled" report MUST carry these. If a
            # router violates the contract, treat as reject.
            self._rejected.append(report)
            logger.warning(
                "Router reported state=filled but missing fill_price/fill_qty/fee; "
                "treating as rejected"
            )
            return

        try:
            if intent.side == OrderSide.BUY:
                self._portfolio.apply_buy(
                    intent.symbol, report.fill_qty, report.fill_price, report.fee
                )
                realized = Decimal("0")
            else:
                realized = self._portfolio.apply_sell(
                    intent.symbol, report.fill_qty, report.fill_price, report.fee
                )
        except ValueError as exc:
            # Insufficient cash / position. Treat as rejected — the
            # Portfolio refused to apply the fill. The order router
            # already reported "filled"; for a real adapter that's
            # the actual venue state, so this branch is mostly a
            # safety net for simulated routers in edge-cases.
            logger.warning("Portfolio refused fill: %s", exc)
            self._rejected.append(
                FillReport(
                    intent=intent,
                    state="rejected",
                    error=f"portfolio refused: {exc}",
                    submitted_at=report.submitted_at,
                )
            )
            return

        self._fills.append(report)
        self._trades.append(
            BacktestTrade(
                ts=candle.ts,
                symbol=intent.symbol,
                side=intent.side.value,
                qty=report.fill_qty,
                price=report.fill_price,
                fee=report.fee,
                realized_pnl=realized,
            )
        )
        await self._emit(
            RuntimeEvent(
                kind="fill",
                ts=candle.ts,
                payload={
                    "side": intent.side.value,
                    "qty": str(report.fill_qty),
                    "fill_price": str(report.fill_price),
                    "fee": str(report.fee),
                    "realized_pnl": str(realized),
                },
            )
        )

    async def _emit(self, event: RuntimeEvent) -> None:
        """Fire ``event_hook`` if set. Hook exceptions are caught and
        logged — observability must NEVER break the trading loop."""
        if self._event_hook is None:
            return
        try:
            await self._event_hook(event)
        except Exception:  # noqa: BLE001 — log + continue
            logger.exception("event_hook raised; swallowing to keep loop alive")

    def _last_close(self) -> Decimal:
        """Last candle's close, for the final equity mark-to-market.
        Returns Decimal('0') as a defensive sentinel when nothing
        arrived (degenerate empty stream). The cast tells mypy the
        Decimal arithmetic is preserved across attribute access."""
        if self._ctx.history:
            close: Decimal = self._ctx.history[-1].close
            return close
        return Decimal("0")

    def _build_result(self) -> StrategyRuntimeResult:
        """Snapshot at runtime stop."""
        return StrategyRuntimeResult(
            symbol=self._symbol,
            timeframe=self._timeframe,
            candles_processed=self._candles_processed,
            intents_emitted=self._intents_emitted,
            fills=list(self._fills),
            rejected=list(self._rejected),
            trades=list(self._trades),
            equity_curve=list(self._equity_curve),
            final_equity=self._portfolio.equity({self._symbol: self._last_close()}),
        )
