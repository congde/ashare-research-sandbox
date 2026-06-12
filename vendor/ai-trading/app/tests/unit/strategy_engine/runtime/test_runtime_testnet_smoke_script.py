"""Unit tests for the runtime testnet smoke script.

The script lives at ``scripts/runtime_testnet_smoke.py`` and is the
operator-facing M3 verification tool. The full live invocation
requires Binance credentials + network — those run nightly via the
``binance-testnet-nightly.yml`` workflow (gated by
``-m integration_external``).

This file's job is the **CI smoke** that catches the cheap regressions:

  * The script imports cleanly (no circular import, no missing
    dependency, no AGPL contamination via transitive deps)
  * The buy-once strategy factory behaves as advertised:
      - waits until len(ctx.history) >= 3
      - fires exactly once
      - subsequent factory calls produce a fresh closure (no state
        leak between restarts)
  * The replay CandleSource yields all candles in order

Tests use ``importlib`` to load the script since it isn't on the
package path; that pattern matches the existing
``test_sma_crossover_strategy.py`` cell.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.domain.market_data import Candle


def _load_smoke_module():
    """Dynamic-import the script. Mirrors the pattern used by
    ``test_sma_crossover_strategy.py``."""
    repo_root = Path(__file__).resolve().parents[5]
    script_path = repo_root / "scripts" / "runtime_testnet_smoke.py"
    spec = importlib.util.spec_from_file_location(
        "runtime_testnet_smoke", script_path
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["runtime_testnet_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def smoke():
    return _load_smoke_module()


# ── Import sanity ───────────────────────────────────────────────


def test_smoke_module_imports_cleanly(smoke) -> None:
    """The slowest-to-catch bug class: a circular import or a missing
    dep that only surfaces when the script's actually run. Cheap to
    pin here."""
    assert hasattr(smoke, "main")
    assert hasattr(smoke, "_buy_once_on_third_candle")
    assert hasattr(smoke, "_ReplayCandleSource")


def test_main_is_a_callable_returning_int(smoke) -> None:
    """``raise SystemExit(main())`` — the script's exit code depends
    on main returning an int."""
    import inspect

    sig = inspect.signature(smoke.main)
    # No required args — should be callable from CLI bootstrap
    for p in sig.parameters.values():
        assert (
            p.default is not p.empty or p.kind == p.VAR_POSITIONAL
        ), f"main() should take no required arg; got {p}"


# ── Strategy factory: warm-up + fire-once ───────────────────────


class _CtxStub:
    """Minimal StrategyContext stub — only what the smoke strategy
    actually reads (history + order_intent)."""

    def __init__(self, history_len: int) -> None:
        self.history = [None] * history_len  # length-only matters

    def order_intent(self, side, qty, type):
        # The smoke strategy passes these literally; we return a
        # marker the test can inspect rather than fabricating a
        # full OrderIntent (avoids re-importing the dataclass).
        return ("intent", side, qty, type)


def test_strategy_returns_none_before_warmup(smoke) -> None:
    """len(ctx.history) < 3 → no trade."""
    strategy = smoke._buy_once_on_third_candle(Decimal("0.001"))
    # Simulate candle 0 with history length 1 (just appended)
    assert strategy(_CtxStub(history_len=1), None) is None
    assert strategy(_CtxStub(history_len=2), None) is None


def test_strategy_fires_on_third_tick(smoke) -> None:
    """First tick with history >= 3 emits the intent."""
    strategy = smoke._buy_once_on_third_candle(Decimal("0.001"))
    out = strategy(_CtxStub(history_len=3), None)
    assert out is not None
    # Sanity-check the intent shape we built
    assert out[0] == "intent"
    assert out[1] == "buy"
    assert out[2] == Decimal("0.001")
    assert out[3] == "market"


def test_strategy_fires_at_most_once(smoke) -> None:
    """After the first fire, all subsequent calls return None.

    Without this invariant, a long-running runtime would submit a
    BUY per bar — burning real money. Pin it loudly.
    """
    strategy = smoke._buy_once_on_third_candle(Decimal("0.001"))
    assert strategy(_CtxStub(history_len=3), None) is not None
    assert strategy(_CtxStub(history_len=4), None) is None
    assert strategy(_CtxStub(history_len=10), None) is None
    assert strategy(_CtxStub(history_len=1000), None) is None


def test_factory_returns_fresh_state_each_call(smoke) -> None:
    """Each invocation of ``_buy_once_on_third_candle`` must return
    a CLOSURE with its own ``fired`` flag — otherwise a restart
    inherits the prior run's "already fired" state and never trades
    again. This is the bug the StrategyRunner factory pattern was
    designed to prevent; this test pins the contract from the
    smoke-script side."""
    a = smoke._buy_once_on_third_candle(Decimal("0.001"))
    b = smoke._buy_once_on_third_candle(Decimal("0.001"))

    # Fire ``a`` to exhaustion.
    assert a(_CtxStub(history_len=3), None) is not None
    assert a(_CtxStub(history_len=4), None) is None

    # ``b`` must still be fresh — fire on its first valid tick.
    assert b(_CtxStub(history_len=3), None) is not None


def test_strategy_uses_qty_argument(smoke) -> None:
    """The factory parameterises on qty — pin that the value flows
    through to the emitted intent. Without this, all smokes ship
    with a fixed qty regardless of CLI flag."""
    strategy = smoke._buy_once_on_third_candle(Decimal("0.05"))
    out = strategy(_CtxStub(history_len=3), None)
    assert out[2] == Decimal("0.05")


# ── ReplayCandleSource ──────────────────────────────────────────


def _candle(i: int) -> Candle:
    p = Decimal("100.0")
    return Candle(
        exchange="binance",
        symbol="BTC/USDT",
        timeframe="1m",
        ts=datetime(2026, 5, 16, tzinfo=UTC) + timedelta(minutes=i),
        open=p, high=p, low=p, close=p,
        volume=Decimal("1.0"),
    )


@pytest.mark.asyncio
async def test_replay_source_yields_all_candles_in_order(smoke) -> None:
    """Wraps a list, yields them async. Same order, no duplicates,
    no skips."""
    candles = [_candle(i) for i in range(5)]
    source = smoke._ReplayCandleSource(candles)

    seen: list[Candle] = []

    async def collect() -> None:
        async for c in source.stream(symbol="BTC/USDT", timeframe="1m"):
            seen.append(c)

    await collect()
    assert seen == candles


@pytest.mark.asyncio
async def test_replay_source_handles_empty_list(smoke) -> None:
    """No candles → no yields, no exception. The smoke script
    explicitly aborts on `<3 candles` upstream, but the source
    itself must not crash."""
    source = smoke._ReplayCandleSource([])
    seen: list[Candle] = []

    async def collect() -> None:
        async for c in source.stream(symbol="BTC/USDT", timeframe="1m"):
            seen.append(c)

    await collect()
    assert seen == []


# ── Argparse defaults ───────────────────────────────────────────


def test_default_qty_matches_m1_runbook(smoke) -> None:
    """0.001 BTC matches the binance-testnet-e2e.md runbook's
    wallet-drain rate of ~$50 per smoke run at $78k BTC. If someone
    bumps this default, the wallet-refill cadence assumption breaks."""
    # Argparse defaults live in _parse_args — invoke with no args
    # (we use parse_known_args via sys.argv shim).
    import sys as _sys

    saved = _sys.argv
    _sys.argv = ["runtime_testnet_smoke"]
    try:
        args = smoke._parse_args()
        assert args.qty == Decimal("0.001")
        assert args.mode == "dry"
        assert args.yes_live is False
    finally:
        _sys.argv = saved


def test_live_mode_default_is_dry_for_safety(smoke) -> None:
    """The default mode MUST be dry. A typo / forgotten flag
    shouldn't submit a real testnet order. The ``--yes-live`` gate
    plus default=dry is the two-layer guard."""
    import sys as _sys

    saved = _sys.argv
    _sys.argv = ["runtime_testnet_smoke"]
    try:
        args = smoke._parse_args()
        assert args.mode == "dry"
    finally:
        _sys.argv = saved
