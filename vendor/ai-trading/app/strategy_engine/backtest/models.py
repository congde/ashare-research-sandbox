"""Cost / slippage models + result container for the backtest engine.

Per ADR-0009. Internal-use dataclasses; SQLAlchemy persistence lives
in ``app.domain.backtest``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Protocol, cast

from app.connectors.protocol import OrderIntent, OrderSide
from app.domain.market_data import Candle


# ── Fee models ──────────────────────────────────────────────────
class FeeModel(Protocol):
    def calc(self, intent: OrderIntent, fill_price: Decimal) -> Decimal: ...


@dataclass(frozen=True, slots=True)
class ConstantBpsFee:
    maker_bps: float = 10.0
    taker_bps: float = 10.0

    def calc(self, intent: OrderIntent, fill_price: Decimal) -> Decimal:
        is_taker = intent.type.value in {"market", "stop"}
        bps = self.taker_bps if is_taker else self.maker_bps
        notional = intent.qty * fill_price
        # ``Decimal * Decimal / Decimal`` is statically ``Any`` (operands
        # carry no precision hint). Typed intermediate keeps the public
        # signature honest without changing runtime behaviour.
        fee: Decimal = notional * Decimal(bps) / Decimal(10_000)
        return fee


# ── Slippage models ─────────────────────────────────────────────
class SlippageModel(Protocol):
    def fill_price(self, intent: OrderIntent, candle: Candle) -> Decimal: ...


@dataclass(frozen=True, slots=True)
class ConstantBpsSlippage:
    bps: float = 5.0

    def fill_price(self, intent: OrderIntent, candle: Candle) -> Decimal:
        ref: Decimal = intent.price if intent.price is not None else cast(Decimal, candle.close)
        bps = Decimal(self.bps) / Decimal(10_000)
        if intent.side == OrderSide.BUY:
            return ref * (Decimal(1) + bps)
        return ref * (Decimal(1) - bps)


@dataclass(frozen=True, slots=True)
class VolumeAwareSlippage:
    """Slippage proportional to (qty / candle_volume)."""

    factor: float = 0.5

    def fill_price(self, intent: OrderIntent, candle: Candle) -> Decimal:
        ref: Decimal = intent.price if intent.price is not None else cast(Decimal, candle.close)
        if candle.volume <= 0:
            return ref
        ratio = float(intent.qty) / float(candle.volume)
        slip = Decimal(ratio * self.factor)
        if intent.side == OrderSide.BUY:
            return ref * (Decimal(1) + slip)
        return ref * (Decimal(1) - slip)


# ── Trade record + result container ─────────────────────────────
@dataclass(frozen=True, slots=True)
class BacktestTrade:
    ts: datetime
    symbol: str
    side: str
    qty: Decimal
    price: Decimal
    fee: Decimal
    realized_pnl: Decimal


@dataclass(frozen=True, slots=True)
class BacktestMetrics:
    period_start: datetime
    period_end: datetime
    total_trades: int
    win_rate: float
    pnl_pct: float
    pnl_abs: Decimal
    sharpe: float
    # Sortino — same as Sharpe but downside-only stdev. Default 0.0
    # when there are no negative returns (no downside → "infinite"
    # Sortino is meaningless; report 0.0 and let consumers handle it).
    sortino: float
    max_drawdown_pct: float
    final_equity: Decimal


@dataclass
class BacktestResult:
    metrics: BacktestMetrics
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[tuple[datetime, Decimal]] = field(default_factory=list)


# ── Metrics helper ──────────────────────────────────────────────
def compute_metrics(
    initial_capital: Decimal,
    trades: list[BacktestTrade],
    equity_curve: list[tuple[datetime, Decimal]],
) -> BacktestMetrics:
    if not equity_curve:
        return BacktestMetrics(
            period_start=trades[0].ts if trades else _epoch(),
            period_end=trades[-1].ts if trades else _epoch(),
            total_trades=len(trades),
            win_rate=0.0,
            pnl_pct=0.0,
            pnl_abs=Decimal("0"),
            sharpe=0.0,
            sortino=0.0,
            max_drawdown_pct=0.0,
            final_equity=initial_capital,
        )

    final_equity = equity_curve[-1][1]
    pnl_abs = final_equity - initial_capital
    pnl_pct = float(pnl_abs / initial_capital * Decimal(100))

    wins = [t for t in trades if t.realized_pnl > 0]
    losses = [t for t in trades if t.realized_pnl < 0]
    closed = wins + losses
    win_rate = len(wins) / len(closed) if closed else 0.0

    # Sharpe: (mean / stdev) of step-wise equity returns × sqrt(N)
    returns: list[float] = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1][1]
        curr = equity_curve[i][1]
        if prev > 0:
            returns.append(float((curr - prev) / prev))
    if len(returns) >= 2:
        mean = sum(returns) / len(returns)
        var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        std = math.sqrt(var)
        sharpe = (mean / std) * math.sqrt(len(returns)) if std > 0 else 0.0

        # Sortino — downside-only standard deviation (returns below 0).
        # Use sample stdev (N-1) when there are ≥ 2 negative returns to
        # stay symmetric with the Sharpe denominator. Annualisation
        # factor is sqrt(N) — same convention as Sharpe so they're
        # directly comparable.
        downside = [r for r in returns if r < 0]
        if len(downside) >= 2:
            d_var = sum(r * r for r in downside) / (len(downside) - 1)
            d_std = math.sqrt(d_var)
            sortino = (mean / d_std) * math.sqrt(len(returns)) if d_std > 0 else 0.0
        else:
            # 0 or 1 downside samples → Sortino undefined. Report 0.0
            # rather than +inf so downstream charts / sorts behave.
            sortino = 0.0
    else:
        sharpe = 0.0
        sortino = 0.0

    # Max drawdown
    peak = equity_curve[0][1]
    max_dd = Decimal("0")
    for _, eq in equity_curve:
        peak = max(peak, eq)
        if peak > 0:
            dd = (peak - eq) / peak
            if dd > max_dd:
                max_dd = dd

    return BacktestMetrics(
        period_start=equity_curve[0][0],
        period_end=equity_curve[-1][0],
        total_trades=len(trades),
        win_rate=win_rate,
        pnl_pct=pnl_pct,
        pnl_abs=pnl_abs,
        sharpe=sharpe,
        sortino=sortino,
        max_drawdown_pct=float(max_dd * Decimal(100)),
        final_equity=final_equity,
    )


def _epoch() -> datetime:
    from datetime import UTC
    from datetime import datetime as _dt

    return _dt.fromtimestamp(0, tz=UTC)
