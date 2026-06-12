"""Event-driven backtest engine adapted from ai-trading (ADR-0009)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from strategy_engine.backtest.candles import Candle
from strategy_engine.backtest.models import (
    BacktestResult,
    BacktestTrade,
    FeeModel,
    SlippageModel,
    ZeroFee,
    ZeroSlippage,
    compute_metrics,
)
from strategy_engine.backtest.portfolio import Portfolio
from strategy_engine.backtest.portfolio import Position as PortfolioPosition
from strategy_engine.backtest.protocol import OrderIntent, OrderSide, OrderType, TimeInForce


@dataclass(slots=True)
class StrategyContext:
    symbol: str
    timeframe: str
    portfolio: Portfolio
    history: list[Candle] = field(default_factory=list)

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


StrategyFn = Callable[[StrategyContext, Candle], OrderIntent | None]


@dataclass(slots=True)
class _PendingOrder:
    intent: OrderIntent
    submitted_ts: datetime


@dataclass
class BacktestEngine:
    strategy_fn: StrategyFn
    initial_capital: Decimal = Decimal("10000")
    fee_model: FeeModel = field(default_factory=ZeroFee)
    slippage_model: SlippageModel = field(default_factory=ZeroSlippage)
    _pending: list[_PendingOrder] = field(default_factory=list, init=False)

    def pending_orders_snapshot(self) -> list[OrderIntent]:
        return [entry.intent for entry in self._pending]

    def run(self, candles: list[Candle], symbol: str, timeframe: str) -> BacktestResult:
        if not candles:
            raise ValueError("candles must not be empty")

        portfolio = Portfolio(initial_cash=self.initial_capital)
        ctx = StrategyContext(symbol=symbol, timeframe=timeframe, portfolio=portfolio)
        trades: list[BacktestTrade] = []
        equity_curve: list[tuple[datetime, Decimal]] = []
        self._pending = []

        for candle in candles:
            self._settle_pending(candle, portfolio, trades)
            ctx.history.append(candle)
            intent = self.strategy_fn(ctx, candle)
            if intent is not None:
                self._submit(intent, candle, portfolio, trades)
            portfolio.record_equity(candle.ts, {symbol: candle.close})
            equity_curve.append((candle.ts, portfolio.equity({symbol: candle.close})))

        metrics = compute_metrics(self.initial_capital, trades, equity_curve)
        return BacktestResult(metrics=metrics, trades=trades, equity_curve=equity_curve)

    def _submit(
        self,
        intent: OrderIntent,
        candle: Candle,
        portfolio: Portfolio,
        trades: list[BacktestTrade],
    ) -> None:
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
            if intent.price is not None and self._limit_crossable(intent, candle):
                self._fill_at_price(intent, candle, intent.price, portfolio, trades)
            return

        self._pending.append(_PendingOrder(intent=intent, submitted_ts=candle.ts))

    def _settle_pending(
        self,
        candle: Candle,
        portfolio: Portfolio,
        trades: list[BacktestTrade],
    ) -> None:
        if not self._pending:
            return

        still_pending: list[_PendingOrder] = []
        for entry in self._pending:
            if not self._try_fill_pending(entry, candle, portfolio, trades):
                still_pending.append(entry)
        self._pending = still_pending

    def _try_fill_pending(
        self,
        entry: _PendingOrder,
        candle: Candle,
        portfolio: Portfolio,
        trades: list[BacktestTrade],
    ) -> bool:
        intent = entry.intent

        if intent.type == OrderType.LIMIT:
            if intent.price is None:
                return True
            if not self._limit_crossable(intent, candle):
                return False
            self._fill_at_price(intent, candle, intent.price, portfolio, trades)
            return True

        if intent.type in {OrderType.STOP, OrderType.STOP_LIMIT}:
            if intent.stop_price is None:
                return True
            if not self._stop_triggered(intent, candle):
                return False
            fill_price = self.slippage_model.fill_price(intent, candle)
            self._fill_at_price(intent, candle, fill_price, portfolio, trades)
            return True

        return True

    @staticmethod
    def _limit_crossable(intent: OrderIntent, candle: Candle) -> bool:
        if intent.price is None:
            return False
        if intent.side == OrderSide.BUY:
            return bool(candle.low <= intent.price)
        return bool(candle.high >= intent.price)

    @staticmethod
    def _stop_triggered(intent: OrderIntent, candle: Candle) -> bool:
        if intent.stop_price is None:
            return False
        if intent.side == OrderSide.BUY:
            return bool(candle.high >= intent.stop_price)
        return bool(candle.low <= intent.stop_price)

    def _fill_at_price(
        self,
        intent: OrderIntent,
        candle: Candle,
        fill_price: Decimal,
        portfolio: Portfolio,
        trades: list[BacktestTrade],
    ) -> None:
        fee = self.fee_model.calc(intent, fill_price)
        try:
            if intent.side == OrderSide.BUY:
                portfolio.apply_buy(intent.symbol, intent.qty, fill_price, fee)
                realized = Decimal("0")
            else:
                realized = portfolio.apply_sell(
                    intent.symbol, intent.qty, fill_price, fee
                )
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
