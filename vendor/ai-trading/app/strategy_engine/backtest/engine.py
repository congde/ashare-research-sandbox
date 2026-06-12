"""Event-driven backtest engine — core loop.

Per ADR-0009. Each candle is fed to the strategy's ``on_tick(ctx,
candle)`` (the same signature used in live runtime); resulting
``OrderIntent`` is checked, slipped, fee'd, and applied to the
``Portfolio``. Output is a ``BacktestResult`` with metrics +
trade log + equity curve.

The engine is intentionally synchronous — backtests are CPU-bound
deterministic replays. Async / parallel parameter sweeps are a
separate concern (Hyperopt, v1.5).

Fill model (S3-1):

  * ``MARKET`` orders fill on the SAME candle they were submitted on,
    at the slipped close. This matches how most simple backtest
    libraries work, and is "good enough" for end-of-bar strategies
    that don't care about intra-bar dynamics.

  * ``LIMIT`` orders go into a pending queue. On EACH subsequent
    candle, the engine checks whether the candle's [low, high] range
    crosses the limit price. If yes, fill at the LIMIT price (no
    slippage — the venue must honour the resting price). If no,
    keep the order pending. Time-in-force is honoured (``IOC`` /
    ``FOK`` cancel on the same candle).

  * ``STOP`` orders go into a pending queue. On EACH subsequent
    candle, the engine checks whether the candle's intra-bar range
    crosses the stop_price. If yes, fill at the stop price plus
    slippage (worst-case assumption — the market moved through your
    stop fast). This is conservative; some venues honour the stop at
    the trigger price.

Lookahead-bias guard:

  Strategy callable receives the current candle by value AND a
  ``ctx.history`` slice that ENDS at the current candle inclusive.
  The intent here is "you can see today's close as you decide", which
  matches the production live-runtime semantics (the runtime calls
  on_tick AT bar close). Strategies that peek beyond ``ctx.history[-1]``
  must rely on an injected future-aware data source — the engine
  doesn't supply one.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.connectors.protocol import OrderIntent, OrderSide, OrderType, TimeInForce
from app.domain.market_data import Candle
from app.strategy_engine.backtest.models import (
    BacktestResult,
    BacktestTrade,
    ConstantBpsFee,
    ConstantBpsSlippage,
    FeeModel,
    SlippageModel,
    compute_metrics,
)
from app.strategy_engine.backtest.portfolio import Portfolio
from app.strategy_engine.backtest.portfolio import Position as PortfolioPosition


@dataclass(slots=True)
class StrategyContext:
    """Subset of `ai_trading.api` exposed to user strategies during backtest."""

    symbol: str
    timeframe: str
    portfolio: Portfolio
    history: list[Candle] = field(default_factory=list)
    # `research` is the strategy-facing ResearchSurface (see
    # `app.ai_trading_api.research`). Backtest defaults to NoOpResearch
    # which raises on any tool call — strategies that need research
    # data must use the live runtime (where the runtime wires a real
    # ResearchAgentService) or pre-compute data into a constant.
    research: Any = None

    def __post_init__(self) -> None:
        # Default-resolve `research` lazily to NoOpResearch so the
        # backtest engine doesn't need to import the research module
        # to construct a context. Tests can override by passing an
        # explicit stub.
        if self.research is None:
            from app.ai_trading_api.research import NoOpResearch
            self.research = NoOpResearch()

    def position(self, symbol: str | None = None) -> PortfolioPosition:
        return self.portfolio.position(symbol or self.symbol)

    def order_intent(
        self,
        side: str,
        qty: Decimal | float | int,
        type: str = "market",
        price: Decimal | float | int | None = None,
        stop_price: Decimal | float | int | None = None,
        time_in_force: str = "GTC",
    ) -> OrderIntent:
        return OrderIntent(
            symbol=self.symbol,
            side=OrderSide(side),
            type=OrderType(type),
            qty=Decimal(str(qty)),
            price=Decimal(str(price)) if price is not None else None,
            stop_price=Decimal(str(stop_price)) if stop_price is not None else None,
            time_in_force=TimeInForce(time_in_force),
        )


# A user strategy is just a callable: (ctx, candle) -> OrderIntent | None
StrategyFn = Callable[[StrategyContext, Candle], OrderIntent | None]


# ── Pending order book ────────────────────────────────────────────


@dataclass(slots=True)
class _PendingOrder:
    """One unfilled LIMIT / STOP order waiting on a price trigger.

    Internal — exposed via ``BacktestEngine.pending_orders`` snapshot
    for inspection but never directly mutated by callers.
    """

    intent: OrderIntent
    submitted_ts: datetime


@dataclass
class BacktestEngine:
    strategy_fn: StrategyFn
    initial_capital: Decimal = Decimal("1000")
    fee_model: FeeModel = field(default_factory=ConstantBpsFee)
    slippage_model: SlippageModel = field(default_factory=ConstantBpsSlippage)
    # Sliding window of pending orders. NEVER mutated externally;
    # ``pending_orders_snapshot()`` returns a copy for inspection.
    _pending: list[_PendingOrder] = field(default_factory=list, init=False)

    def pending_orders_snapshot(self) -> list[OrderIntent]:
        """Returns a copy of the currently-pending orders' intents.

        Useful for tests / dashboards that want to inspect the
        unfilled-orders queue mid-run. The engine's internal list is
        intentionally private — callers should never mutate it.
        """
        return [p.intent for p in self._pending]

    def run(self, candles: list[Candle], symbol: str, timeframe: str) -> BacktestResult:
        if not candles:
            raise ValueError("candles must not be empty")

        portfolio = Portfolio(initial_cash=self.initial_capital)
        ctx = StrategyContext(symbol=symbol, timeframe=timeframe, portfolio=portfolio)
        trades: list[BacktestTrade] = []
        equity_curve: list[tuple[datetime, Decimal]] = []
        self._pending = []

        for candle in candles:
            # 1. Settle pending LIMIT / STOP orders against this candle
            #    BEFORE the strategy sees it. Mirrors live runtime:
            #    resting orders are at the venue and can fill at any
            #    time independent of the strategy's tick.
            self._settle_pending(candle, portfolio, trades)

            # 2. Strategy decides based on (history + current bar).
            ctx.history.append(candle)
            intent: OrderIntent | None = self.strategy_fn(ctx, candle)

            # 3. Submit the intent.
            if intent is not None:
                self._submit(intent, candle, portfolio, trades)

            # 4. Mark-to-market: record equity at the current close.
            portfolio.record_equity(candle.ts, {symbol: candle.close})
            equity_curve.append((candle.ts, portfolio.equity({symbol: candle.close})))

        metrics = compute_metrics(self.initial_capital, trades, equity_curve)
        return BacktestResult(metrics=metrics, trades=trades, equity_curve=equity_curve)

    # ── Submission ────────────────────────────────────────────────

    def _submit(
        self,
        intent: OrderIntent,
        candle: Candle,
        portfolio: Portfolio,
        trades: list[BacktestTrade],
    ) -> None:
        """Route a fresh OrderIntent to the appropriate fill path.

        * MARKET → fill now at slipped close.
        * LIMIT → queue pending. IOC / FOK try-once on the SAME candle
          before being cancelled — they don't survive to the next bar.
        * STOP / STOP_LIMIT → queue pending. The engine respects the
          ``stop_price`` trigger only on subsequent candles; same-bar
          fills would imply intra-bar tick-level data we don't have.
        """
        if intent.type == OrderType.MARKET:
            self._fill_at_price(
                intent,
                candle,
                self.slippage_model.fill_price(intent, candle),
                portfolio,
                trades,
            )
            return

        if intent.type == OrderType.LIMIT and intent.time_in_force in {
            TimeInForce.IOC,
            TimeInForce.FOK,
        }:
            # IOC / FOK: try to fill against THIS candle's range; if
            # not crossable, cancel (never queue).
            if intent.price is not None and self._limit_crossable(intent, candle):
                self._fill_at_price(intent, candle, intent.price, portfolio, trades)
            return

        # GTC LIMIT / STOP / STOP_LIMIT — queue and wait.
        self._pending.append(_PendingOrder(intent=intent, submitted_ts=candle.ts))

    # ── Settlement of pending orders ──────────────────────────────

    def _settle_pending(
        self,
        candle: Candle,
        portfolio: Portfolio,
        trades: list[BacktestTrade],
    ) -> None:
        """Walk the pending book and fill anything this candle crosses.

        Order is preserved — pending orders fire in FIFO submission
        order. A single candle can fill multiple pending orders.
        """
        if not self._pending:
            return

        still_pending: list[_PendingOrder] = []
        for entry in self._pending:
            filled = self._try_fill_pending(entry, candle, portfolio, trades)
            if not filled:
                still_pending.append(entry)
        self._pending = still_pending

    def _try_fill_pending(
        self,
        entry: _PendingOrder,
        candle: Candle,
        portfolio: Portfolio,
        trades: list[BacktestTrade],
    ) -> bool:
        """Attempt to fill ONE pending order against this candle.
        Returns True if filled (caller drops it), False to keep pending.
        """
        intent = entry.intent

        if intent.type == OrderType.LIMIT:
            if intent.price is None:
                # Defensive: a LIMIT without price shouldn't have been
                # queued. Drop silently — same outcome as a malformed
                # order at the live runtime's risk gate.
                return True
            if not self._limit_crossable(intent, candle):
                return False
            # Filled at the limit price (venue honoured resting price).
            self._fill_at_price(intent, candle, intent.price, portfolio, trades)
            return True

        if intent.type in {OrderType.STOP, OrderType.STOP_LIMIT}:
            if intent.stop_price is None:
                return True
            if not self._stop_triggered(intent, candle):
                return False
            # Conservative: stop fills at stop_price with slippage —
            # markets move fast through stops.
            fill_price = self.slippage_model.fill_price(intent, candle)
            self._fill_at_price(intent, candle, fill_price, portfolio, trades)
            return True

        # Defensive: unknown type fell through; treat as cancelled.
        return True

    # ── Crossable / triggered checks ──────────────────────────────

    @staticmethod
    def _limit_crossable(intent: OrderIntent, candle: Candle) -> bool:
        """A LIMIT BUY fills if the candle's low <= limit price.
        A LIMIT SELL fills if the candle's high >= limit price."""
        if intent.price is None:
            return False
        if intent.side == OrderSide.BUY:
            return bool(candle.low <= intent.price)
        return bool(candle.high >= intent.price)

    @staticmethod
    def _stop_triggered(intent: OrderIntent, candle: Candle) -> bool:
        """A STOP BUY (a buy-stop / break-out long) triggers when the
        high reaches stop_price. A STOP SELL (a stop-loss on a long)
        triggers when the low reaches stop_price."""
        if intent.stop_price is None:
            return False
        if intent.side == OrderSide.BUY:
            return bool(candle.high >= intent.stop_price)
        return bool(candle.low <= intent.stop_price)

    # ── Single-trade fill ────────────────────────────────────────

    def _fill_at_price(
        self,
        intent: OrderIntent,
        candle: Candle,
        fill_price: Decimal,
        portfolio: Portfolio,
        trades: list[BacktestTrade],
    ) -> None:
        """Apply a fill: take fee, update portfolio, record the trade.

        Insufficient cash / position → silent skip. The live runtime's
        :class:`RiskManager` catches these earlier; mirroring that
        behaviour here keeps backtests honest about what RISK will
        actually allow on prod.
        """
        fee = self.fee_model.calc(intent, fill_price)
        try:
            if intent.side == OrderSide.BUY:
                portfolio.apply_buy(intent.symbol, intent.qty, fill_price, fee)
                realized = Decimal("0")
            else:
                realized = portfolio.apply_sell(intent.symbol, intent.qty, fill_price, fee)
        except ValueError:
            return

        trades.append(
            BacktestTrade(
                ts=candle.ts,
                symbol=intent.symbol,
                side=intent.side.value,
                qty=intent.qty,
                price=fill_price,
                fee=fee,
                realized_pnl=realized,
            )
        )
