"""Unit tests for :func:`compile_strategy` — the validated-source →
``on_tick`` compiler shared by the backtest engine and the live runtime.

Covers: ctx-only strategies, SDK-importing strategies, end-to-end drive
through the real ``BacktestEngine``, and rejection of every failure mode
(denied import, missing on_tick, syntax error, eval) plus the runtime
import guard.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.connectors.protocol import OrderIntent
from app.domain.market_data import Candle
from app.strategy_engine.backtest import BacktestEngine, Portfolio, StrategyContext
from app.strategy_engine.dsl.loader import (
    StrategyCompileError,
    _guarded_import,
    compile_strategy,
)

# ── Fixtures ─────────────────────────────────────────────────────


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


def _ctx(history: list[Candle]) -> StrategyContext:
    return StrategyContext(
        symbol="BTC/USDT",
        timeframe="1h",
        portfolio=Portfolio(initial_cash=Decimal("1000")),
        history=history,
    )


def _wrap(body: str) -> str:
    indented = "\n".join("    " + line for line in body.splitlines())
    return f"def on_tick(ctx, candle):\n{indented}\n"


# Minimal valid strategy using ONLY ctx (no imports) — harness style.
CTX_ONLY = (
    "def on_tick(ctx, candle):\n"
    "    if ctx.position().qty > 0 or len(ctx.history) < 3:\n"
    "        return None\n"
    "    return ctx.order_intent(side='buy', qty=0.01, type='market')\n"
)

# Valid strategy importing the SDK surface — example_sma_cross style.
SDK_IMPORT = (
    "from ai_trading.api import market_buy\n"
    "def on_tick(ctx, candle):\n"
    "    if ctx.position().qty > 0 or len(ctx.history) < 3:\n"
    "        return None\n"
    "    return market_buy(ctx.symbol, 0.01)\n"
)

# Deterministic buy-then-sell so the engine records a closed trade.
CLOSED_TRADE = (
    "from ai_trading.api import market_buy, market_sell\n"
    "def on_tick(ctx, candle):\n"
    "    n = len(ctx.history)\n"
    "    pos = ctx.position()\n"
    "    if n == 3 and pos.qty <= 0:\n"
    "        return market_buy(ctx.symbol, 0.01)\n"
    "    if n == 5 and pos.qty > 0:\n"
    "        return market_sell(ctx.symbol, pos.qty)\n"
    "    return None\n"
)


# ── Compile + execute ────────────────────────────────────────────


class TestCompileAndRun:
    def test_ctx_only_strategy_compiles_and_runs(self) -> None:
        fn = compile_strategy(CTX_ONLY)
        assert callable(fn)
        ctx = _ctx(_series([100, 101, 102]))
        intent = fn(ctx, ctx.history[-1])
        assert isinstance(intent, OrderIntent)
        assert intent.side.value == "buy"

    def test_sdk_import_strategy_compiles_and_runs(self) -> None:
        fn = compile_strategy(SDK_IMPORT)
        ctx = _ctx(_series([100, 101, 102]))
        intent = fn(ctx, ctx.history[-1])
        assert isinstance(intent, OrderIntent)
        assert intent.symbol == "BTC/USDT"

    def test_warmup_returns_none(self) -> None:
        fn = compile_strategy(CTX_ONLY)
        ctx = _ctx(_series([100]))  # history < 3
        assert fn(ctx, ctx.history[-1]) is None

    def test_compiled_strategy_drives_backtest_engine(self) -> None:
        """End-to-end: loader output drives the REAL engine to a trade."""
        fn = compile_strategy(CLOSED_TRADE)
        engine = BacktestEngine(strategy_fn=fn, initial_capital=Decimal("1000"))
        result = engine.run(_series([100, 101, 102, 103, 104]), "BTC/USDT", "1h")
        assert result.metrics.total_trades >= 1
        assert result.metrics.final_equity > 0


# ── Rejection paths ──────────────────────────────────────────────


class TestRejection:
    def test_denied_import_rejected_with_errors(self) -> None:
        with pytest.raises(StrategyCompileError) as ei:
            compile_strategy("import os\n" + _wrap("return None"))
        assert ei.value.errors  # validator errors carried for feedback

    def test_missing_on_tick_rejected(self) -> None:
        with pytest.raises(StrategyCompileError):
            compile_strategy("x = 1\n")

    def test_syntax_error_rejected(self) -> None:
        with pytest.raises(StrategyCompileError):
            compile_strategy("def on_tick(ctx, candle)\n    return None\n")

    def test_eval_rejected(self) -> None:
        with pytest.raises(StrategyCompileError):
            compile_strategy(_wrap("eval('1 + 1')\nreturn None"))

    def test_wrong_signature_rejected(self) -> None:
        with pytest.raises(StrategyCompileError):
            compile_strategy("def on_tick(ctx):\n    return None\n")


# ── Runtime import guard (defense in depth) ──────────────────────


class TestImportGuard:
    def test_guarded_import_blocks_denied(self) -> None:
        with pytest.raises(ImportError):
            _guarded_import("os")
        with pytest.raises(ImportError):
            _guarded_import("subprocess")

    def test_guarded_import_blocks_unauthorized(self) -> None:
        with pytest.raises(ImportError):
            _guarded_import("requests")

    def test_guarded_import_allows_safelist(self) -> None:
        mod = _guarded_import("math")
        assert hasattr(mod, "sqrt")
