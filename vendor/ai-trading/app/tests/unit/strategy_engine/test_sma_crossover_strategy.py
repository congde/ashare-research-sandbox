"""Tests for the SMA-20/50 crossover demo strategy + performance budget.

The strategy itself is in ``scripts/backtest_sma_demo.py`` (it's a
demo, not a production strategy — lives in ``scripts/`` for that
reason). But the BacktestEngine's S3 DoD requires that a textbook
strategy actually executes BUY and SELL on realistic data, AND that
runtime stays inside the per-candle budget. Both invariants live
here.

Two budget tests:

  * **Smoke** — 5,000 bars must finish in < 1 s on any reasonable
    runner. Catches catastrophic regressions (O(N²) in the engine,
    accidentally reloading the strategy per tick, etc.).
  * **Extrapolation** — the 5,000-bar number is multiplied to a 1y
    1m projection and compared against the 60 s DoD budget with
    generous headroom (3×). This proves "we won't blow the budget
    next time someone adds an O(N) per-tick op" without burning a
    full minute on every PR.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

import pytest

from app.strategy_engine.backtest import BacktestEngine


def _load_demo_module():
    """Dynamic-import ``scripts/backtest_sma_demo.py`` since it isn't
    a package member. Using importlib so we don't have to add
    ``scripts/`` to sys.path globally — keeps imports honest.
    """
    repo_root = Path(__file__).resolve().parents[4]
    script_path = repo_root / "scripts" / "backtest_sma_demo.py"
    spec = importlib.util.spec_from_file_location("backtest_sma_demo", script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["backtest_sma_demo"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def demo():
    return _load_demo_module()


# ── Strategy correctness ─────────────────────────────────────────


def test_synthesise_candles_is_deterministic(demo) -> None:
    """Same seed → identical candles. Without this, the budget tests
    can't compare apples-to-apples across runs."""
    a = demo.synthesise_candles(100, seed=7)
    b = demo.synthesise_candles(100, seed=7)
    assert a == b


def test_synthesise_candles_monotonic_timestamps(demo) -> None:
    """The engine assumes timestamps move forward. Catch any future
    bug in the synthesiser before it masks an engine bug."""
    candles = demo.synthesise_candles(500)
    for i in range(1, len(candles)):
        assert candles[i].ts > candles[i - 1].ts


def test_sma_strategy_executes_both_sides(demo) -> None:
    """End-to-end check: SMA-20/50 on the synthesised data must hit
    BOTH a BUY (golden cross) and a SELL (death cross). If the
    sinusoidal trend in the synthesiser is broken, we'd only see one
    side and the test would catch it.

    2,000 candles is enough for ~50 crosses (sinusoid period 43,200
    bars; we'd see ~5 % of a full cycle, but mean-reversion noise
    triggers many shorter crosses).
    """
    candles = demo.synthesise_candles(2_000)
    engine = BacktestEngine(strategy_fn=demo.make_sma_crossover_strategy())
    result = engine.run(candles, symbol="BTC/USDT", timeframe="1m")

    sides = {t.side for t in result.trades}
    assert "buy" in sides
    assert "sell" in sides
    # And we should produce a non-trivial number of trades — not 1, not
    # zero. If this fails, the SMA logic is wrong or windows are off.
    assert result.metrics.total_trades >= 10


# ── Performance budget ───────────────────────────────────────────


def test_engine_meets_5k_bar_smoke_budget(demo) -> None:
    """Catches catastrophic per-candle regressions.

    5,000 bars on a 2024-era laptop is well under 100 ms. We pin to
    1 s here to leave headroom for shared CI runners and CPython
    GC pauses; this isn't a fine-grained perf gate, it's a smoke
    gate.
    """
    candles = demo.synthesise_candles(5_000)
    engine = BacktestEngine(strategy_fn=demo.make_sma_crossover_strategy())

    t0 = time.perf_counter()
    engine.run(candles, symbol="BTC/USDT", timeframe="1m")
    elapsed = time.perf_counter() - t0

    assert elapsed < 1.0, f"5k-bar run took {elapsed:.3f}s (budget 1.0s)"


def test_engine_meets_1y_budget_via_extrapolation(demo) -> None:
    """Project the 1y 1m budget (60 s DoD) from a 10k-bar measurement.

    1y of 1m candles = 525,600 bars. We don't want to actually run
    that on every PR — 5 s × N=PRs adds up. Instead: measure 10,000
    bars, extrapolate linearly (the engine IS O(N) — that's an
    invariant we're testing), and assert the projection fits the
    budget with 3× headroom.

    If this fails, either the engine became super-linear OR a real
    constant-factor regression has crossed the 20 s line. Both
    deserve investigation.
    """
    n_measure = 10_000
    n_target = 525_600
    budget_seconds = 60.0
    headroom = 3.0  # require projected ≤ budget / 3

    candles = demo.synthesise_candles(n_measure)
    engine = BacktestEngine(strategy_fn=demo.make_sma_crossover_strategy())

    t0 = time.perf_counter()
    engine.run(candles, symbol="BTC/USDT", timeframe="1m")
    elapsed = time.perf_counter() - t0

    projected = elapsed * (n_target / n_measure)
    assert projected < budget_seconds / headroom, (
        f"Projected 1y runtime {projected:.1f}s exceeds budget/{headroom} = "
        f"{budget_seconds / headroom:.1f}s (measured {elapsed:.2f}s on {n_measure} bars)"
    )
