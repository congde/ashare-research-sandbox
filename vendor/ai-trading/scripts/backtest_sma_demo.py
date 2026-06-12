"""SMA-20/50 crossover backtest demo + 1y performance benchmark.

Two modes, same code path:

  * ``--mode demo``     — small N, prints the result. Sanity check that
    the BacktestEngine actually executes trades on a textbook strategy.
  * ``--mode benchmark`` — synthesises 1y of 1m candles (~525,600 bars)
    and asserts the run completes inside the Sprint-S3 DoD budget of
    60 s.

The strategy is intentionally textbook: buy when SMA-20 crosses above
SMA-50, sell when it crosses back. It's not meant to be profitable —
it's meant to exercise the entire pipeline (history, intent, fill,
metrics, equity curve) on realistic data shapes.

This script writes nothing to MinIO / PG. The Parquet publish path is
exercised by the unit tests in
``app/tests/unit/strategy_engine/test_backtest_result_builder.py``;
keeping this demo zero-IO lets it run anywhere without infra.

Usage:

  uv run python scripts/backtest_sma_demo.py --mode demo
  uv run python scripts/backtest_sma_demo.py --mode benchmark
  uv run python scripts/backtest_sma_demo.py --mode benchmark --max-seconds 60
"""

from __future__ import annotations

import argparse
import math
import random
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.connectors.protocol import OrderIntent
from app.domain.market_data import Candle
from app.strategy_engine.backtest import (
    BacktestEngine,
    StrategyContext,
)

# ── Strategy: SMA-20/50 crossover ────────────────────────────────


def make_sma_crossover_strategy(
    short_window: int = 20,
    long_window: int = 50,
    qty: Decimal = Decimal("0.001"),
):
    """Return an ``on_tick`` callable closing over the two SMA windows.

    State machine: hold no position by default; flip long on golden
    cross (short crosses above long); flat on death cross (short
    crosses below long). Single-symbol, single-position — by design,
    this strategy is the minimum that exercises both BUY and SELL
    paths through the engine.
    """

    # We need ONE bar of memory (the previous short/long values) to
    # detect a cross. Capture via closure rather than ctx — keeps the
    # strategy signature pure (ctx, candle) → intent.
    state: dict[str, float | None] = {"prev_short": None, "prev_long": None}

    def on_tick(ctx: StrategyContext, candle: Candle) -> OrderIntent | None:
        history = ctx.history
        # Insufficient history → wait. The engine has already appended
        # ``candle`` to ``history`` so len(history) is N+1 after N
        # prior bars.
        if len(history) < long_window:
            return None

        # SMAs of the most recent windows.
        short_vals = history[-short_window:]
        long_vals = history[-long_window:]
        short = sum(float(c.close) for c in short_vals) / short_window
        long_ = sum(float(c.close) for c in long_vals) / long_window

        prev_short = state["prev_short"]
        prev_long = state["prev_long"]
        state["prev_short"] = short
        state["prev_long"] = long_

        # Need a previous SMA pair to detect a crossing event.
        if prev_short is None or prev_long is None:
            return None

        position = ctx.position()
        held = position.qty > 0

        # Golden cross: short crosses ABOVE long. Buy if flat.
        if prev_short <= prev_long and short > long_ and not held:
            return ctx.order_intent(side="buy", qty=qty, type="market")
        # Death cross: short crosses BELOW long. Sell if held.
        if prev_short >= prev_long and short < long_ and held:
            return ctx.order_intent(side="sell", qty=position.qty, type="market")
        return None

    return on_tick


# ── Candle synthesiser ───────────────────────────────────────────


def synthesise_candles(
    n: int,
    *,
    start: datetime | None = None,
    timeframe_minutes: int = 1,
    base_price: float = 60_000.0,
    seed: int = 42,
) -> list[Candle]:
    """Generate ``n`` synthetic 1-minute BTC/USDT candles with a
    mean-reverting random walk + a slow sinusoidal trend.

    The sinusoid guarantees the SMA-20/50 actually crosses (a pure
    random walk doesn't reliably produce crosses at our windows),
    so the benchmark exercises both BUY and SELL fill paths. Seeded
    for determinism: same seed → identical candles → identical
    metrics → CI-friendly.

    The shape (open/high/low/close/volume) is realistic enough that
    slippage and fee models behave the same as on real data. We're
    not pretending this IS real market data — it's a load-test
    fixture.
    """
    rng = random.Random(seed)
    if start is None:
        start = datetime(2025, 1, 1, tzinfo=UTC)

    candles: list[Candle] = []
    price = base_price
    for i in range(n):
        # Slow sinusoidal trend: one full cycle every ~30 days at 1m
        # bars → period = 43_200 ticks. Amplitude ±2.5 %.
        trend = base_price * 0.025 * math.sin(2 * math.pi * i / 43_200)
        # Mean-reverting noise: pull toward (base + trend); ±0.1 % per
        # bar typical.
        target = base_price + trend
        price += (target - price) * 0.05 + rng.gauss(0, base_price * 0.001)

        # Intra-bar high/low: ±0.05 % around close. Open = previous close
        # (slight gap on bar 0).
        open_ = candles[-1].close if candles else Decimal(str(price))
        close = Decimal(f"{price:.2f}")
        high_v = max(float(open_), float(close)) * 1.0005
        low_v = min(float(open_), float(close)) * 0.9995
        high = Decimal(f"{high_v:.2f}")
        low = Decimal(f"{low_v:.2f}")

        candles.append(
            Candle(
                exchange="synthetic",
                symbol="BTC/USDT",
                timeframe=f"{timeframe_minutes}m",
                ts=start + timedelta(minutes=i * timeframe_minutes),
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=Decimal(f"{rng.uniform(0.5, 5.0):.4f}"),
            )
        )
    return candles


# ── Run wrappers ─────────────────────────────────────────────────


def run_demo() -> None:
    """Small-N demo. Prints metrics + a few sample trades."""
    candles = synthesise_candles(2_000)
    engine = BacktestEngine(strategy_fn=make_sma_crossover_strategy())

    t0 = time.perf_counter()
    result = engine.run(candles, symbol="BTC/USDT", timeframe="1m")
    elapsed = time.perf_counter() - t0

    m = result.metrics
    print(f"Demo: SMA-20/50 cross on {len(candles)} synthetic 1m candles")
    print(f"  runtime:        {elapsed:.3f}s")
    print(f"  trades:         {m.total_trades}")
    print(f"  win_rate:       {m.win_rate:.2%}")
    print(f"  pnl_pct:        {m.pnl_pct:+.2f}%")
    print(f"  sharpe:         {m.sharpe:+.3f}")
    print(f"  sortino:        {m.sortino:+.3f}")
    print(f"  max_drawdown:   {m.max_drawdown_pct:.2f}%")
    print(f"  final_equity:   {m.final_equity}")
    if result.trades:
        print("\n  first 3 trades:")
        for t in result.trades[:3]:
            print(f"    {t.ts.isoformat()} {t.side:4s} {t.qty} @ {t.price}")


def run_benchmark(*, n_candles: int, max_seconds: float) -> int:
    """1y 1m benchmark. Asserts runtime < max_seconds (DoD: 60s).

    Returns: 0 on success, 1 on budget violation. Suitable as a
    non-zero exit code for CI / nightly.
    """
    print(f"Benchmark: SMA-20/50 cross on {n_candles:,} synthetic 1m candles…")
    t_gen0 = time.perf_counter()
    candles = synthesise_candles(n_candles)
    t_gen = time.perf_counter() - t_gen0
    print(f"  candle synthesis: {t_gen:.2f}s ({n_candles / t_gen:.0f} candles/s)")

    engine = BacktestEngine(strategy_fn=make_sma_crossover_strategy())
    t_run0 = time.perf_counter()
    result = engine.run(candles, symbol="BTC/USDT", timeframe="1m")
    t_run = time.perf_counter() - t_run0
    print(f"  engine.run:       {t_run:.2f}s ({n_candles / t_run:.0f} candles/s)")
    print(f"  trades:           {result.metrics.total_trades}")
    print(f"  budget:           {max_seconds:.0f}s")

    if t_run > max_seconds:
        print(f"  VERDICT:          ❌ over budget by {t_run - max_seconds:.2f}s")
        return 1
    print(f"  VERDICT:          ✅ {max_seconds - t_run:.2f}s under budget")
    return 0


# ── CLI ──────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=["demo", "benchmark"],
        default="demo",
        help="demo prints metrics on a small run; benchmark times a 1y run",
    )
    parser.add_argument(
        "--n-candles",
        type=int,
        default=525_600,  # 1y × 365d × 24h × 60m
        help="Candles to generate in benchmark mode (default: 525_600 = 1y of 1m)",
    )
    parser.add_argument(
        "--max-seconds",
        type=float,
        default=60.0,
        help="Benchmark budget; non-zero exit if exceeded (DoD: 60s)",
    )
    args = parser.parse_args()

    if args.mode == "demo":
        run_demo()
        return 0
    return run_benchmark(n_candles=args.n_candles, max_seconds=args.max_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
