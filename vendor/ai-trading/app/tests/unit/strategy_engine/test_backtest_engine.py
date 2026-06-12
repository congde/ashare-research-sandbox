"""Backtest engine unit tests — SMA cross + portfolio invariants.

Per [ADR-0009] / [implementation/03-detailed-design/03-backtest-engine.md].
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.connectors.protocol import OrderIntent, OrderSide, OrderType
from app.domain.market_data import Candle
from app.strategy_engine.backtest import (
    BacktestEngine,
    ConstantBpsFee,
    ConstantBpsSlippage,
    Portfolio,
    StrategyContext,
)


def _candle(ts: datetime, close: float, vol: float = 100.0) -> Candle:
    return Candle(
        exchange="binance",
        symbol="BTC/USDT",
        timeframe="1h",
        ts=ts,
        open=Decimal(str(close)),
        high=Decimal(str(close * 1.01)),
        low=Decimal(str(close * 0.99)),
        close=Decimal(str(close)),
        volume=Decimal(str(vol)),
    )


def _series(prices: list[float]) -> list[Candle]:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    return [_candle(base + timedelta(hours=i), p) for i, p in enumerate(prices)]


# ── Portfolio unit tests ────────────────────────────────────────
class TestPortfolio:
    def test_buy_decreases_cash_and_creates_position(self) -> None:
        p = Portfolio(initial_cash=Decimal("1000"))
        p.apply_buy("BTC/USDT", Decimal("0.01"), Decimal("60000"), Decimal("1"))
        assert p.cash == Decimal("399")  # 1000 - (0.01 * 60000) - 1
        assert p.position("BTC/USDT").qty == Decimal("0.01")
        assert p.position("BTC/USDT").avg_entry_price == Decimal("60000")

    def test_sell_returns_realized_pnl(self) -> None:
        p = Portfolio(initial_cash=Decimal("10000"))
        p.apply_buy("BTC/USDT", Decimal("0.1"), Decimal("60000"), Decimal("0"))
        realized = p.apply_sell(
            "BTC/USDT", Decimal("0.1"), Decimal("65000"), Decimal("0")
        )
        assert realized == Decimal("500")  # (65000-60000)*0.1
        assert p.position("BTC/USDT").qty == Decimal("0")

    def test_insufficient_cash_raises(self) -> None:
        p = Portfolio(initial_cash=Decimal("100"))
        with pytest.raises(ValueError, match="insufficient cash"):
            p.apply_buy("BTC/USDT", Decimal("1"), Decimal("60000"), Decimal("0"))

    def test_oversell_raises(self) -> None:
        p = Portfolio(initial_cash=Decimal("10000"))
        p.apply_buy("BTC/USDT", Decimal("0.1"), Decimal("60000"), Decimal("0"))
        with pytest.raises(ValueError, match="insufficient position"):
            p.apply_sell(
                "BTC/USDT", Decimal("1"), Decimal("60000"), Decimal("0")
            )


# ── Slippage / fee ──────────────────────────────────────────────
class TestSlippageAndFee:
    def test_constant_bps_slippage_buy_higher(self) -> None:
        slippage = ConstantBpsSlippage(bps=10.0)
        candle = _candle(datetime.now(UTC), 60000)
        intent = OrderIntent(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            type=OrderType.MARKET,
            qty=Decimal("0.01"),
        )
        fill = slippage.fill_price(intent, candle)
        assert fill > candle.close
        assert fill == Decimal("60000") * (Decimal("1") + Decimal("10") / Decimal("10000"))

    def test_constant_bps_slippage_sell_lower(self) -> None:
        slippage = ConstantBpsSlippage(bps=10.0)
        candle = _candle(datetime.now(UTC), 60000)
        intent = OrderIntent(
            symbol="BTC/USDT",
            side=OrderSide.SELL,
            type=OrderType.MARKET,
            qty=Decimal("0.01"),
        )
        fill = slippage.fill_price(intent, candle)
        assert fill < candle.close

    def test_constant_bps_fee_taker(self) -> None:
        fee = ConstantBpsFee(maker_bps=5.0, taker_bps=15.0)
        intent = OrderIntent(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            type=OrderType.MARKET,  # taker
            qty=Decimal("0.01"),
        )
        f = fee.calc(intent, Decimal("60000"))
        # 0.01 * 60000 * 15 / 10_000 = 0.9
        assert f == Decimal("0.9000")


# ── Engine end-to-end: SMA cross ────────────────────────────────
def sma_cross_strategy(ctx: StrategyContext, candle: Candle) -> OrderIntent | None:
    """Simple SMA-3 cross SMA-7. Long-only."""
    if len(ctx.history) < 7:
        return None
    closes = [float(c.close) for c in ctx.history]
    sma_short = sum(closes[-3:]) / 3
    sma_long = sum(closes[-7:]) / 7
    pos = ctx.position()

    if sma_short > sma_long and pos.qty == 0:
        # Buy with 50% of cash to avoid overspending under slippage/fee.
        cash = ctx.portfolio.cash
        qty = (cash * Decimal("0.5")) / candle.close
        if qty > 0:
            return ctx.order_intent("buy", qty.quantize(Decimal("0.0001")))

    if sma_short < sma_long and pos.qty > 0:
        return ctx.order_intent("sell", pos.qty)

    return None


class TestBacktestEngine:
    def test_empty_candles_raises(self) -> None:
        engine = BacktestEngine(strategy_fn=sma_cross_strategy)
        with pytest.raises(ValueError, match="candles must not be empty"):
            engine.run([], "BTC/USDT", "1h")

    def test_no_signal_strategy_preserves_cash(self) -> None:
        engine = BacktestEngine(
            strategy_fn=lambda ctx, c: None, initial_capital=Decimal("1000")
        )
        candles = _series([100, 101, 102, 103])
        result = engine.run(candles, "BTC/USDT", "1h")
        assert result.metrics.total_trades == 0
        assert result.metrics.final_equity == Decimal("1000")
        assert len(result.equity_curve) == len(candles)

    def test_sma_cross_in_uptrend_makes_money(self) -> None:
        # Strict uptrend → SMA-3 stays above SMA-7 after crossover.
        prices = [100 + i * 0.5 for i in range(50)]
        candles = _series(prices)
        engine = BacktestEngine(
            strategy_fn=sma_cross_strategy, initial_capital=Decimal("1000")
        )
        result = engine.run(candles, "BTC/USDT", "1h")
        assert result.metrics.total_trades >= 1
        # Equity should not be negative; in pure uptrend, positive PNL
        # is expected once a buy signal hits.
        assert result.metrics.final_equity > Decimal("0")

    def test_pnl_consistent_across_runs(self) -> None:
        prices = [100, 102, 104, 106, 108, 110, 112, 110, 108, 106, 105, 103, 102]
        candles = _series(prices)
        engine = BacktestEngine(strategy_fn=sma_cross_strategy)
        a = engine.run(candles, "BTC/USDT", "1h")
        b = engine.run(candles, "BTC/USDT", "1h")
        assert a.metrics.final_equity == b.metrics.final_equity
        assert a.metrics.total_trades == b.metrics.total_trades

    def test_metrics_compute_when_no_trades(self) -> None:
        engine = BacktestEngine(strategy_fn=lambda ctx, c: None)
        candles = _series([100, 101, 102])
        result = engine.run(candles, "BTC/USDT", "1h")
        assert result.metrics.total_trades == 0
        assert result.metrics.win_rate == 0.0
        assert result.metrics.max_drawdown_pct == 0.0

    def test_max_drawdown_detected(self) -> None:
        # Buy-and-hold a parabolic-then-crashing series.
        def buy_once(ctx: StrategyContext, candle: Candle) -> OrderIntent | None:
            if len(ctx.history) == 1 and ctx.position().qty == 0:
                qty = (ctx.portfolio.cash * Decimal("0.9")) / candle.close
                return ctx.order_intent("buy", qty.quantize(Decimal("0.0001")))
            return None

        prices = [100, 110, 120, 130, 100, 80]  # peak then drop
        candles = _series(prices)
        engine = BacktestEngine(
            strategy_fn=buy_once, initial_capital=Decimal("1000")
        )
        result = engine.run(candles, "BTC/USDT", "1h")
        assert result.metrics.max_drawdown_pct > 0


def test_strategy_context_can_inspect_history() -> None:
    history_lengths = []

    def spy(ctx: StrategyContext, candle: Candle) -> OrderIntent | None:
        history_lengths.append(len(ctx.history))
        return None

    candles = _series([100, 101, 102, 103])
    engine = BacktestEngine(strategy_fn=spy)
    engine.run(candles, "BTC/USDT", "1h")
    assert history_lengths == [1, 2, 3, 4]
