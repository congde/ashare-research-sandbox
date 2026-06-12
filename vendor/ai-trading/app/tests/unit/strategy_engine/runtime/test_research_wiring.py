"""ctx.research wiring into the live runtime (ADR-0020 PR-A).

The strategy-facing research surface is injected through
``StrategyRuntime(research=...)`` → ``StrategyContext.research``. ``None`` (the
default, used by the backtest engine and any flag-off live runner) lazy-resolves
to ``NoOpResearch``, which raises on any tool call — preserving backtest
determinism. The ``/start`` endpoint injects a real adapter only when
``DE_LIVE_RESEARCH_ENABLED`` is set.

These tests pin the construction-time wiring (no asyncio, no endpoint).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.ai_trading_api import NoOpResearch
from app.domain.market_data import Candle
from app.strategy_engine.runtime import SimOrderRouter, StrategyRuntime
from app.strategy_engine.runtime.protocol import CandleSource
from app.strategy_engine.runtime.runner import make_runtime_factory


class _EmptySource(CandleSource):
    async def stream(self, *, symbol: str, timeframe: str) -> AsyncIterator[Candle]:
        if False:  # type: ignore[unreachable]
            yield


class _StubResearch:
    """Stand-in for a ResearchSurface — identity is all the wiring asserts."""

    async def query(self, tool: str, payload: Any = None) -> dict[str, Any]:
        return {}

    async def resolve_symbol(self, symbol: str) -> int:
        return 1


def _runtime(**over: object) -> StrategyRuntime:
    kwargs: dict[str, object] = {
        "strategy_fn": lambda ctx, c: None,
        "candle_source": _EmptySource(),
        "order_router": SimOrderRouter(),
        "symbol": "BTC/USDT",
        "timeframe": "1m",
    }
    kwargs.update(over)
    return StrategyRuntime(**kwargs)  # type: ignore[arg-type]


def test_runtime_defaults_to_noop_research() -> None:
    # No research passed → backtest/flag-off contract: NoOpResearch (raises on use).
    assert isinstance(_runtime()._ctx.research, NoOpResearch)


def test_runtime_injects_provided_research() -> None:
    stub = _StubResearch()
    assert _runtime(research=stub)._ctx.research is stub


def test_make_runtime_factory_threads_research_to_ctx() -> None:
    stub = _StubResearch()
    factory = make_runtime_factory(
        strategy_fn=lambda ctx, c: None,
        candle_source=_EmptySource(),
        order_router=SimOrderRouter(),
        symbol="BTC/USDT",
        timeframe="1m",
        research=stub,
    )
    # The same instance is reused across restarts.
    assert factory()._ctx.research is stub
    assert factory()._ctx.research is stub


def test_make_runtime_factory_without_research_is_noop() -> None:
    factory = make_runtime_factory(
        strategy_fn=lambda ctx, c: None,
        candle_source=_EmptySource(),
        order_router=SimOrderRouter(),
        symbol="BTC/USDT",
        timeframe="1m",
    )
    assert isinstance(factory()._ctx.research, NoOpResearch)
