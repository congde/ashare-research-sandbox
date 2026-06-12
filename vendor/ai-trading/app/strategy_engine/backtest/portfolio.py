"""Portfolio bookkeeping for the backtest engine.

Simple cash + single-asset position tracker. Mirrors the live
PositionTracker contract so the same Strategy.on_tick(...) code
can run against both backtest and live runtimes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass(slots=True)
class Position:
    symbol: str
    qty: Decimal = Decimal("0")
    avg_entry_price: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")

    def mark_to_market(self, last_price: Decimal) -> Decimal:
        """Return current unrealized PNL at ``last_price``."""
        if self.qty == 0:
            return Decimal("0")
        return (last_price - self.avg_entry_price) * self.qty


@dataclass(slots=True)
class EquityPoint:
    ts: datetime
    cash: Decimal
    position_value: Decimal
    equity: Decimal


@dataclass
class Portfolio:
    """Cash + single-asset book keeping."""

    initial_cash: Decimal
    cash: Decimal = field(init=False)
    positions: dict[str, Position] = field(default_factory=dict)
    equity_curve: list[EquityPoint] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.cash = self.initial_cash

    # ── Mutations on fill ──────────────────────────────────────
    def apply_buy(self, symbol: str, qty: Decimal, price: Decimal, fee: Decimal) -> None:
        if qty <= 0 or price <= 0:
            raise ValueError("buy qty / price must be positive")
        cost = qty * price + fee
        if cost > self.cash:
            raise ValueError(f"insufficient cash: need {cost}, have {self.cash}")
        pos = self.positions.setdefault(symbol, Position(symbol=symbol))
        new_qty = pos.qty + qty
        # Weighted average entry price (long-only v1.0).
        pos.avg_entry_price = (
            (pos.avg_entry_price * pos.qty + price * qty) / new_qty if new_qty > 0 else Decimal("0")
        )
        pos.qty = new_qty
        self.cash -= cost

    def apply_sell(self, symbol: str, qty: Decimal, price: Decimal, fee: Decimal) -> Decimal:
        """Returns realized PNL from this sell."""
        if qty <= 0 or price <= 0:
            raise ValueError("sell qty / price must be positive")
        pos = self.positions.get(symbol)
        if pos is None or pos.qty < qty:
            raise ValueError(f"insufficient position to sell {qty} {symbol}")
        proceeds = qty * price - fee
        realized = (price - pos.avg_entry_price) * qty - fee
        pos.qty -= qty
        pos.realized_pnl += realized
        if pos.qty == 0:
            pos.avg_entry_price = Decimal("0")
        self.cash += proceeds
        return realized

    # ── Read-only ──────────────────────────────────────────────
    def position(self, symbol: str) -> Position:
        return self.positions.get(symbol, Position(symbol=symbol))

    def equity(self, last_prices: dict[str, Decimal]) -> Decimal:
        position_value = sum(
            (
                pos.qty * last_prices.get(sym, pos.avg_entry_price)
                for sym, pos in self.positions.items()
            ),
            start=Decimal("0"),
        )
        return self.cash + position_value

    def record_equity(self, ts: datetime, last_prices: dict[str, Decimal]) -> None:
        position_value = sum(
            (
                pos.qty * last_prices.get(sym, pos.avg_entry_price)
                for sym, pos in self.positions.items()
            ),
            start=Decimal("0"),
        )
        self.equity_curve.append(
            EquityPoint(
                ts=ts,
                cash=self.cash,
                position_value=position_value,
                equity=self.cash + position_value,
            )
        )
