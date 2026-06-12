"""Backtest engine — pending LIMIT / STOP fill tests (S3-1).

The base SMA-cross / portfolio invariant tests live in
``test_backtest_engine.py``. This file focuses on the order types
beyond MARKET that S3-1 adds: LIMIT (resting), STOP / STOP_LIMIT,
time-in-force semantics (IOC / FOK / GTC).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.connectors.protocol import OrderIntent, OrderSide, OrderType, TimeInForce
from app.domain.market_data import Candle
from app.strategy_engine.backtest import BacktestEngine


def _candle(
    ts: datetime,
    low: float,
    high: float,
    close: float | None = None,
    vol: float = 100.0,
) -> Candle:
    """Build a candle with custom low / high so tests can place
    LIMIT / STOP prices precisely on either side of the range."""
    close_val = close if close is not None else (low + high) / 2
    return Candle(
        exchange="binance",
        symbol="BTC/USDT",
        timeframe="1h",
        ts=ts,
        open=Decimal(str(close_val)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close_val)),
        volume=Decimal(str(vol)),
    )


_BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _series(specs: list[tuple[float, float]]) -> list[Candle]:
    """``specs`` is list of (low, high) per hour. Close defaults to mid."""
    return [_candle(_BASE + timedelta(hours=i), low, high) for i, (low, high) in enumerate(specs)]


def _one_shot(intent: OrderIntent):
    """Strategy that submits ``intent`` on the first candle, never again.

    Useful for isolating the engine's fill logic from any
    strategy-side bookkeeping.
    """
    fired = [False]

    def strategy(ctx, candle):  # type: ignore[no-untyped-def]
        if fired[0]:
            return None
        fired[0] = True
        return intent

    return strategy


# ── LIMIT order fills ─────────────────────────────────────────────


def test_limit_buy_resting_fills_when_low_crosses() -> None:
    """LIMIT BUY at 100 stays pending until a candle's low crosses 100,
    then fills at the limit price (no slippage on resting orders)."""
    candles = _series(
        [
            (110, 120),  # candle 0 — submission; low=110 > limit, no fill
            (108, 115),  # candle 1 — low=108 > 100, still no fill
            (95, 105),  # candle 2 — low=95 ≤ 100 → FILL
            (96, 99),  # candle 3 — already filled, no second fire
        ]
    )
    intent = OrderIntent(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        type=OrderType.LIMIT,
        qty=Decimal("0.1"),
        price=Decimal("100"),
    )
    engine = BacktestEngine(strategy_fn=_one_shot(intent), initial_capital=Decimal("10000"))
    result = engine.run(candles, "BTC/USDT", "1h")

    assert len(result.trades) == 1
    assert result.trades[0].price == Decimal("100")
    assert result.trades[0].ts == candles[2].ts


def test_limit_buy_never_fills_if_low_stays_above() -> None:
    """LIMIT BUY at 100 with all candles' low > 100 → 0 fills."""
    candles = _series([(110, 120), (108, 115), (105, 112)])
    intent = OrderIntent(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        type=OrderType.LIMIT,
        qty=Decimal("0.1"),
        price=Decimal("100"),
    )
    engine = BacktestEngine(strategy_fn=_one_shot(intent), initial_capital=Decimal("10000"))
    result = engine.run(candles, "BTC/USDT", "1h")

    assert result.trades == []
    # The pending book should still hold this order (callable from
    # the engine for inspection).
    assert len(engine.pending_orders_snapshot()) == 1


def test_limit_sell_resting_fills_when_high_crosses() -> None:
    """LIMIT SELL at 110 fills when a candle's high reaches 110."""
    # Pre-load position with a market buy via injected strategy.
    candles = _series(
        [
            (90, 100),  # MARKET BUY 0.5 @ ~95 to set up position
            (95, 105),  # LIMIT SELL 0.5 @ 110 — pending
            (108, 109),  # high=109 < 110 — no fill
            (109, 112),  # high=112 ≥ 110 → FILL
        ]
    )
    market_buy = OrderIntent(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        type=OrderType.MARKET,
        qty=Decimal("0.5"),
    )
    limit_sell = OrderIntent(
        symbol="BTC/USDT",
        side=OrderSide.SELL,
        type=OrderType.LIMIT,
        qty=Decimal("0.5"),
        price=Decimal("110"),
    )
    steps = [market_buy, limit_sell, None, None]
    idx = [0]

    def strategy(ctx, candle):  # type: ignore[no-untyped-def]
        step = steps[idx[0]] if idx[0] < len(steps) else None
        idx[0] += 1
        return step

    engine = BacktestEngine(strategy_fn=strategy, initial_capital=Decimal("10000"))
    result = engine.run(candles, "BTC/USDT", "1h")

    # 2 trades: the market buy + the limit sell at 110.
    assert len(result.trades) == 2
    sell_trade = result.trades[1]
    assert sell_trade.side == "sell"
    assert sell_trade.price == Decimal("110")
    assert sell_trade.ts == candles[3].ts


def test_limit_ioc_cancels_when_not_immediately_crossable() -> None:
    """IOC LIMIT BUY at 100, current candle low=105 → cancelled,
    never queued. Next candle's low=95 must NOT produce a fill."""
    candles = _series([(105, 115), (95, 100)])
    intent = OrderIntent(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        type=OrderType.LIMIT,
        qty=Decimal("0.1"),
        price=Decimal("100"),
        time_in_force=TimeInForce.IOC,
    )
    engine = BacktestEngine(strategy_fn=_one_shot(intent), initial_capital=Decimal("10000"))
    result = engine.run(candles, "BTC/USDT", "1h")

    assert result.trades == []
    assert engine.pending_orders_snapshot() == []


def test_limit_ioc_fills_on_same_candle_when_crossable() -> None:
    """IOC LIMIT BUY at 100, current candle low=98 → fill immediately
    at the limit price."""
    candles = _series([(98, 110), (95, 100)])
    intent = OrderIntent(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        type=OrderType.LIMIT,
        qty=Decimal("0.1"),
        price=Decimal("100"),
        time_in_force=TimeInForce.IOC,
    )
    engine = BacktestEngine(strategy_fn=_one_shot(intent), initial_capital=Decimal("10000"))
    result = engine.run(candles, "BTC/USDT", "1h")

    assert len(result.trades) == 1
    assert result.trades[0].price == Decimal("100")
    assert result.trades[0].ts == candles[0].ts


# ── STOP order triggers ───────────────────────────────────────────


def test_stop_loss_sell_triggers_when_low_crosses() -> None:
    """Hold a long; STOP SELL at stop_price=95 fires when a candle's
    low drops to 95. Fill at slipped price (worst-case stop)."""
    candles = _series(
        [
            (100, 105),  # MARKET BUY 0.5 to open position
            (98, 102),  # STOP SELL 0.5 @ stop=95 — pending
            (97, 99),  # low=97 > 95 — not triggered
            (90, 96),  # low=90 ≤ 95 → FILL
        ]
    )
    market_buy = OrderIntent(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        type=OrderType.MARKET,
        qty=Decimal("0.5"),
    )
    stop_sell = OrderIntent(
        symbol="BTC/USDT",
        side=OrderSide.SELL,
        type=OrderType.STOP,
        qty=Decimal("0.5"),
        stop_price=Decimal("95"),
    )
    steps = [market_buy, stop_sell, None, None]
    idx = [0]

    def strategy(ctx, candle):  # type: ignore[no-untyped-def]
        step = steps[idx[0]] if idx[0] < len(steps) else None
        idx[0] += 1
        return step

    engine = BacktestEngine(strategy_fn=strategy, initial_capital=Decimal("10000"))
    result = engine.run(candles, "BTC/USDT", "1h")

    # 2 trades: market buy + stop sell.
    assert len(result.trades) == 2
    stop_trade = result.trades[1]
    assert stop_trade.side == "sell"
    assert stop_trade.ts == candles[3].ts


def test_stop_buy_breakout_triggers_when_high_crosses() -> None:
    """STOP BUY at stop_price=110 fires when a candle's high reaches
    110 (breakout entry pattern)."""
    candles = _series(
        [
            (100, 105),  # submission; high=105 < 110
            (102, 108),  # high=108 < 110
            (105, 112),  # high=112 ≥ 110 → FILL
        ]
    )
    stop_buy = OrderIntent(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        type=OrderType.STOP,
        qty=Decimal("0.1"),
        stop_price=Decimal("110"),
    )
    engine = BacktestEngine(strategy_fn=_one_shot(stop_buy), initial_capital=Decimal("10000"))
    result = engine.run(candles, "BTC/USDT", "1h")

    assert len(result.trades) == 1
    assert result.trades[0].ts == candles[2].ts


def test_stop_never_triggered_remains_pending() -> None:
    """If stop_price never crossed, the order stays in the pending
    book at run end."""
    candles = _series([(100, 105), (101, 106), (102, 107)])
    stop_buy = OrderIntent(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        type=OrderType.STOP,
        qty=Decimal("0.1"),
        stop_price=Decimal("200"),  # never reachable
    )
    engine = BacktestEngine(strategy_fn=_one_shot(stop_buy), initial_capital=Decimal("10000"))
    result = engine.run(candles, "BTC/USDT", "1h")

    assert result.trades == []
    assert len(engine.pending_orders_snapshot()) == 1


# ── Engine invariants ────────────────────────────────────────────


def test_pending_orders_fifo_within_one_candle() -> None:
    """If a single candle crosses two pending LIMIT prices, they fill
    in submission order."""
    candles = _series([(150, 160), (140, 145), (50, 200)])

    limit_low = OrderIntent(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        type=OrderType.LIMIT,
        qty=Decimal("0.05"),
        price=Decimal("100"),
    )
    limit_mid = OrderIntent(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        type=OrderType.LIMIT,
        qty=Decimal("0.05"),
        price=Decimal("130"),
    )
    steps = [limit_low, limit_mid, None]
    idx = [0]

    def strategy(ctx, candle):  # type: ignore[no-untyped-def]
        step = steps[idx[0]] if idx[0] < len(steps) else None
        idx[0] += 1
        return step

    engine = BacktestEngine(strategy_fn=strategy, initial_capital=Decimal("100000"))
    result = engine.run(candles, "BTC/USDT", "1h")

    # On candle 2 (low=50, high=200) both limits cross. FIFO →
    # 100 fills first, then 130.
    assert len(result.trades) == 2
    assert result.trades[0].price == Decimal("100")
    assert result.trades[1].price == Decimal("130")


def test_pending_orders_snapshot_is_copy() -> None:
    """Mutating the snapshot must not affect the engine's internal
    list. Protects callers that want to inspect without coupling."""
    candles = _series([(100, 105), (101, 106)])
    intent = OrderIntent(
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        type=OrderType.LIMIT,
        qty=Decimal("0.1"),
        price=Decimal("50"),  # never fills
    )
    engine = BacktestEngine(strategy_fn=_one_shot(intent), initial_capital=Decimal("10000"))
    engine.run(candles, "BTC/USDT", "1h")

    snap = engine.pending_orders_snapshot()
    assert len(snap) == 1
    snap.clear()  # mutate the copy
    assert len(engine.pending_orders_snapshot()) == 1  # engine state unchanged


def test_strategy_context_history_excludes_future() -> None:
    """``ctx.history`` at the strategy's nth call contains exactly
    n candles ending at the current one — no peek at future candles.
    """
    candles = _series([(100, 105), (101, 106), (102, 107)])
    history_lengths: list[int] = []

    def strategy(ctx, candle):  # type: ignore[no-untyped-def]
        history_lengths.append(len(ctx.history))
        # The current candle must be the LAST item of history.
        assert ctx.history[-1] is candle
        return None

    engine = BacktestEngine(strategy_fn=strategy, initial_capital=Decimal("10000"))
    engine.run(candles, "BTC/USDT", "1h")
    assert history_lengths == [1, 2, 3]


@pytest.mark.parametrize(
    ("side", "limit", "low", "high", "expected"),
    [
        ("buy", 100, 95, 110, True),  # low crosses
        ("buy", 100, 105, 110, False),  # never reached
        ("buy", 100, 100, 110, True),  # exact touch counts (≤)
        ("sell", 100, 95, 110, True),  # high crosses
        ("sell", 100, 95, 99, False),  # never reached
        ("sell", 100, 95, 100, True),  # exact touch counts (≥)
    ],
)
def test_limit_crossable_boundary_cases(
    side: str, limit: float, low: float, high: float, expected: bool
) -> None:
    """Boundary semantics: a touch on the limit price counts as a
    crossing in both directions. Aligns with how venue match engines
    treat resting orders at-the-money."""
    from app.strategy_engine.backtest.engine import BacktestEngine as Engine

    intent = OrderIntent(
        symbol="BTC/USDT",
        side=OrderSide(side),
        type=OrderType.LIMIT,
        qty=Decimal("0.1"),
        price=Decimal(str(limit)),
    )
    candle = _candle(_BASE, low, high)
    assert Engine._limit_crossable(intent, candle) is expected
