"""Unit tests for walk-forward analysis.

The thing under test is the **stability verdict** — given a strategy
that has known behaviour, does walk-forward correctly pass or fail it?

We use three categories of fixture strategies:

  * **stable_winner** — always profitable on each fold (controlled by
    test fixture data). Should pass.
  * **stable_loser** — always unprofitable on each fold. Should pass
    too (the metric is *direction agreement*, not *positive PNL*).
  * **flipper** — wins one fold, loses the next. Should fail on
    direction-agreement.

Each fixture uses synthetic candles + a strategy whose behaviour is
predictable from those candles.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.connectors.protocol import OrderIntent
from app.domain.market_data import Candle
from app.strategy_engine.backtest import (
    StrategyContext,
    WalkForwardReport,
    walk_forward_analysis,
)
from app.strategy_engine.backtest.walk_forward import (
    MIN_FOLDS,
    _coefficient_of_variation,
    _direction_agreement,
    _split_into_folds,
)

# ── Helpers ──────────────────────────────────────────────────────


def _candle(ts: datetime, price: float, volume: float = 1.0) -> Candle:
    """Build a tight-range candle around ``price`` so any market-order
    fills at approximately ``price``."""
    p = Decimal(f"{price:.2f}")
    return Candle(
        exchange="synthetic",
        symbol="BTC/USDT",
        timeframe="1m",
        ts=ts,
        open=p,
        high=p * Decimal("1.0001"),
        low=p * Decimal("0.9999"),
        close=p,
        volume=Decimal(f"{volume:.4f}"),
    )


def _candles_with_segments(prices_per_segment: list[list[float]]) -> list[Candle]:
    """Concatenate per-segment price sequences into one candle list.

    Each segment is its own "fold" in the analysis — by aligning fold
    boundaries to segments we control per-fold behaviour deterministically.
    """
    base_ts = datetime(2026, 1, 1, tzinfo=UTC)
    out: list[Candle] = []
    minute = 0
    for seg in prices_per_segment:
        for price in seg:
            out.append(_candle(base_ts + timedelta(minutes=minute), price))
            minute += 1
    return out


def _buy_once_factory():
    """Strategy factory: each invocation returns a FRESH closure that
    buys 0.001 on the second tick and does nothing else.

    Result is fully determined by the candle prices: PNL = (last_close
    - second_close) × 0.001 minus fees. The factory is what
    ``walk_forward_analysis`` calls once per fold so the "bought"
    state resets between folds.
    """

    def make() -> object:
        state = {"bought": False}

        def on_tick(ctx: StrategyContext, candle: Candle) -> OrderIntent | None:
            if len(ctx.history) < 2:
                return None
            if state["bought"]:
                return None
            state["bought"] = True
            return ctx.order_intent(side="buy", qty=Decimal("0.001"), type="market")

        return on_tick

    return make


# ── Splitter ─────────────────────────────────────────────────────


def test_split_evenly_divides_when_clean() -> None:
    """N candles, F folds, N % F == 0 → each fold has N/F candles."""
    candles = _candles_with_segments([[100.0] * 20])
    chunks = _split_into_folds(candles, 4)
    assert [len(c) for c in chunks] == [5, 5, 5, 5]


def test_split_distributes_remainder_to_first_folds() -> None:
    """N=23, F=5 → fold sizes [5, 5, 5, 4, 4] (extras in first chunks).
    No empty trailing fold."""
    candles = _candles_with_segments([[100.0] * 23])
    chunks = _split_into_folds(candles, 5)
    assert [len(c) for c in chunks] == [5, 5, 5, 4, 4]


def test_split_preserves_order_and_no_overlap() -> None:
    """Concatenating the chunks should reproduce the input exactly."""
    candles = _candles_with_segments([[100.0 + i for i in range(17)]])
    chunks = _split_into_folds(candles, 3)
    rejoined = [c for chunk in chunks for c in chunk]
    assert rejoined == candles


# ── Aggregation helpers ──────────────────────────────────────────


def test_direction_agreement_all_same_sign() -> None:
    """All-positive → 1.0; all-negative → 1.0."""
    assert _direction_agreement([1.0, 2.0, 3.0]) == 1.0
    assert _direction_agreement([-1.0, -2.0, -3.0]) == 1.0


def test_direction_agreement_half_and_half() -> None:
    """Two positive vs two negative → 0.5."""
    assert _direction_agreement([1.0, 2.0, -1.0, -2.0]) == 0.5


def test_direction_agreement_treats_zero_as_neither() -> None:
    """A 0.0 PNL doesn't count toward either majority. With
    [+1, 0, 0, 0] the metric is 0.25 (one positive of four)."""
    assert _direction_agreement([1.0, 0.0, 0.0, 0.0]) == 0.25


def test_direction_agreement_all_zero_returns_zero() -> None:
    """If every fold has 0 PNL the strategy didn't act. Report 0.0
    rather than 1.0 — "no signal" rather than "perfect agreement"."""
    assert _direction_agreement([0.0, 0.0, 0.0]) == 0.0


def test_coefficient_of_variation_finite_when_mean_nonzero() -> None:
    """Standard CV: stdev / |mean|. Pin the value for one known case."""
    cv = _coefficient_of_variation([1.0, 1.0, 1.0, 1.0])
    assert cv == 0.0  # zero variance


def test_coefficient_of_variation_none_when_mean_zero() -> None:
    """Symmetric ±X averages to 0 → CV undefined → None."""
    cv = _coefficient_of_variation([1.0, -1.0, 1.0, -1.0])
    assert cv is None


def test_coefficient_of_variation_none_for_single_sample() -> None:
    """Need ≥ 2 samples for sample stdev; with 1 sample, return None."""
    assert _coefficient_of_variation([0.5]) is None


# ── Public entry point: validation ───────────────────────────────


def test_walk_forward_rejects_too_few_folds() -> None:
    """folds < MIN_FOLDS is unmeaningful. Surface as ValueError so
    callers learn at the API boundary, not via NaN later."""
    candles = _candles_with_segments([[100.0] * 10])
    with pytest.raises(ValueError, match="below minimum"):
        walk_forward_analysis(
            _buy_once_factory(),
            candles,
            symbol="BTC/USDT",
            timeframe="1m",
            folds=MIN_FOLDS - 1,
        )


def test_walk_forward_rejects_too_few_candles() -> None:
    """Can't make F non-empty folds with fewer than F candles."""
    candles = _candles_with_segments([[100.0, 101.0]])
    with pytest.raises(ValueError, match="at least"):
        walk_forward_analysis(
            _buy_once_factory(),
            candles,
            symbol="BTC/USDT",
            timeframe="1m",
            folds=5,
        )


# ── End-to-end: pass / fail verdicts ─────────────────────────────


def test_walk_forward_pass_when_all_folds_profitable() -> None:
    """Three folds, each one strictly rising from 100 → 200 → 300.
    The "buy on tick 2 and hold" strategy makes money in every fold →
    direction_agreement = 1.0, pass.

    Each segment has 10 candles; 3 segments → 30 candles → 3 folds of
    10. Prices climb monotonically within each segment so the strategy
    buys near the bottom and ends near the top.
    """
    candles = _candles_with_segments(
        [
            [100.0 + i for i in range(10)],  # 100 → 109
            [200.0 + i for i in range(10)],  # 200 → 209
            [300.0 + i for i in range(10)],  # 300 → 309
        ]
    )
    report = walk_forward_analysis(
        _buy_once_factory(),
        candles,
        symbol="BTC/USDT",
        timeframe="1m",
        folds=3,
    )
    assert isinstance(report, WalkForwardReport)
    assert report.folds == 3
    assert report.direction_agreement == 1.0
    # All folds profit → pass; reason mentions "pass"
    assert report.pass_ is True
    assert "pass" in report.reason


def test_walk_forward_pass_when_all_folds_unprofitable() -> None:
    """Mirror of the previous case: all folds lose money. Direction
    agreement is still 1.0 (all negative). The metric is *consistency*,
    not *profitability* — overfit doesn't care which direction."""
    candles = _candles_with_segments(
        [
            [100.0 - i for i in range(10)],  # 100 → 91 (and slippage drags)
            [200.0 - i for i in range(10)],
            [300.0 - i for i in range(10)],
        ]
    )
    report = walk_forward_analysis(
        _buy_once_factory(),
        candles,
        symbol="BTC/USDT",
        timeframe="1m",
        folds=3,
    )
    # All folds lose → direction agreement still 1.0
    assert report.direction_agreement == 1.0
    assert report.pass_ is True


def test_walk_forward_fail_when_direction_flips() -> None:
    """Alternating up/down/up/down folds → direction agreement 0.5,
    well below the 0.8 threshold → fail. The reason field calls out
    the specific gate that tripped.

    Strategy: buy on tick 2, sell on tick 8 — captures the within-fold
    price trend so each fold's PNL sign mirrors its segment's slope.
    """

    def factory():
        # Fresh closure each fold so the in-fold state ("did we buy yet")
        # doesn't leak across the up/down boundary.
        state = {"counter": 0}

        def on_tick(ctx: StrategyContext, candle: Candle) -> OrderIntent | None:
            if len(ctx.history) < 2:
                return None
            state["counter"] += 1
            if state["counter"] == 1:
                return ctx.order_intent(
                    side="buy", qty=Decimal("0.001"), type="market"
                )
            position = ctx.position()
            if state["counter"] == 7 and position.qty > 0:
                return ctx.order_intent(
                    side="sell", qty=position.qty, type="market"
                )
            return None

        return on_tick

    candles = _candles_with_segments(
        [
            [100.0 + i for i in range(10)],   # up
            [200.0 - i for i in range(10)],   # down
            [300.0 + i for i in range(10)],   # up
            [400.0 - i for i in range(10)],   # down
        ]
    )
    report = walk_forward_analysis(
        factory,
        candles,
        symbol="BTC/USDT",
        timeframe="1m",
        folds=4,
    )
    # 2 up + 2 down folds → direction agreement = 0.5 < 0.8 → fail.
    assert report.direction_agreement == 0.5
    assert report.pass_ is False
    assert "fail" in report.reason


def test_report_echoes_thresholds_for_ui_consumption() -> None:
    """A UI showing the verdict needs to display the bands that were
    in effect. Pass through whatever the caller supplied."""
    candles = _candles_with_segments([[100.0 + i for i in range(20)]])
    report = walk_forward_analysis(
        _buy_once_factory(),
        candles,
        symbol="BTC/USDT",
        timeframe="1m",
        folds=4,
        direction_agreement_threshold=0.95,
        sharpe_cv_max=2.0,
    )
    assert report.direction_agreement_threshold == 0.95
    assert report.sharpe_cv_max == 2.0


def test_report_includes_per_fold_pnl_and_sharpe() -> None:
    """Convenience fields for UI sparklines — fold count matches."""
    candles = _candles_with_segments(
        [[100.0 + i for i in range(10)], [200.0 + i for i in range(10)]]
    )
    report = walk_forward_analysis(
        _buy_once_factory(),
        candles,
        symbol="BTC/USDT",
        timeframe="1m",
        folds=2,
    )
    assert len(report.fold_pnl_pct) == 2
    assert len(report.fold_sharpe) == 2
    # Each per-fold result also has its own metrics object
    assert len(report.fold_results) == 2
    assert all(r.candle_count > 0 for r in report.fold_results)
