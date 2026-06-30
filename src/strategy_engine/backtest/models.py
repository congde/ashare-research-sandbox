from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol, cast

from strategy_engine.backtest.candles import Candle
from strategy_engine.backtest.protocol import OrderIntent, OrderSide


class FeeModel(Protocol):
    def calc(self, intent: OrderIntent, fill_price: Decimal) -> Decimal: ...


class SlippageModel(Protocol):
    def fill_price(self, intent: OrderIntent, candle: Candle) -> Decimal: ...


@dataclass(frozen=True, slots=True)
class ZeroFee:
    def calc(self, intent: OrderIntent, fill_price: Decimal) -> Decimal:
        return Decimal("0")


@dataclass(frozen=True, slots=True)
class ZeroSlippage:
    def fill_price(self, intent: OrderIntent, candle: Candle) -> Decimal:
        return candle.close


@dataclass(frozen=True, slots=True)
class ConstantBpsFee:
    maker_bps: float = 10.0
    taker_bps: float = 10.0

    def calc(self, intent: OrderIntent, fill_price: Decimal) -> Decimal:
        is_taker = intent.type.value in {"market", "stop"}
        bps = self.taker_bps if is_taker else self.maker_bps
        notional = intent.qty * fill_price
        fee: Decimal = notional * Decimal(bps) / Decimal(10_000)
        return fee


@dataclass(frozen=True, slots=True)
class ConstantBpsSlippage:
    bps: float = 5.0

    def fill_price(self, intent: OrderIntent, candle: Candle) -> Decimal:
        ref: Decimal = (
            intent.price if intent.price is not None else cast(Decimal, candle.close)
        )
        bps = Decimal(self.bps) / Decimal(10_000)
        if intent.side == OrderSide.BUY:
            return ref * (Decimal(1) + bps)
        return ref * (Decimal(1) - bps)


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
class RiskRejection:
    ts: datetime
    symbol: str
    side: str
    rule_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class BacktestMetrics:
    period_start: datetime
    period_end: datetime
    total_trades: int
    win_rate: float
    pnl_pct: float
    pnl_abs: Decimal
    sharpe: float
    sortino: float
    max_drawdown_pct: float
    final_equity: Decimal


@dataclass
class BacktestResult:
    metrics: BacktestMetrics
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[tuple[datetime, Decimal]] = field(default_factory=list)
    risk_rejections: list[RiskRejection] = field(default_factory=list)


def compute_metrics(
    initial_capital: Decimal,
    trades: list[BacktestTrade],
    equity_curve: list[tuple[datetime, Decimal]],
) -> BacktestMetrics:
    if not equity_curve:
        return BacktestMetrics(
            period_start=trades[0].ts if trades else datetime.fromtimestamp(0, tz=timezone.utc),
            period_end=trades[-1].ts if trades else datetime.fromtimestamp(0, tz=timezone.utc),
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

    wins = [trade for trade in trades if trade.realized_pnl > 0]
    losses = [trade for trade in trades if trade.realized_pnl < 0]
    closed = wins + losses
    win_rate = len(wins) / len(closed) if closed else 0.0

    returns: list[float] = []
    for index in range(1, len(equity_curve)):
        prev = equity_curve[index - 1][1]
        curr = equity_curve[index][1]
        if prev > 0:
            returns.append(float((curr - prev) / prev))

    if len(returns) >= 2:
        mean = sum(returns) / len(returns)
        var = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
        std = math.sqrt(var)
        sharpe = (mean / std) * math.sqrt(len(returns)) if std > 0 else 0.0

        downside = [value for value in returns if value < 0]
        if len(downside) >= 2:
            d_var = sum(value * value for value in downside) / (len(downside) - 1)
            d_std = math.sqrt(d_var)
            sortino = (mean / d_std) * math.sqrt(len(returns)) if d_std > 0 else 0.0
        else:
            sortino = 0.0
    else:
        sharpe = 0.0
        sortino = 0.0

    peak = equity_curve[0][1]
    max_dd = Decimal("0")
    for _, equity in equity_curve:
        peak = max(peak, equity)
        if peak > 0:
            drawdown = (peak - equity) / peak
            if drawdown > max_dd:
                max_dd = drawdown

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
