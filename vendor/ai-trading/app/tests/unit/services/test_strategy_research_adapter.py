"""Unit tests for app.services.strategy_research_adapter.

The adapter exists to give strategy code a small, stable surface
(`ai_trading.api.ResearchSurface`) backed by the bigger
`ResearchAgentService`. Tests verify the surface bridges the calls
correctly + maps each native error class to its strategy-facing
equivalent.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.ai_trading_api.research import (
    NoOpResearch,
    ResearchCreditExceededError,
    ResearchNotConfiguredError,
    ResearchToolError,
    ResearchToolNotFoundError,
    ResearchUpstreamError,
)
from app.core.resilience import CircuitBreaker, CircuitState
from app.integrations.dexscan import DexScanConfig
from app.integrations.dexscan.client import DexScanClient
from app.integrations.valuescan import ValueScanConfig
from app.integrations.valuescan.client import ValueScanClient
from app.services.research_agent import (
    ResearchAgentCreditExceededError,
    ResearchAgentNotConfiguredError,
    ResearchAgentService,
    ResearchAgentToolError,
    ResearchAgentUpstreamError,
)
from app.services.research_credit_governor import ResearchCreditGovernor
from app.services.strategy_research_adapter import StrategyResearchAdapter


def _service_with_invoke(
    invoke: AsyncMock,
    resolve: AsyncMock | None = None,
) -> ResearchAgentService:
    """Build a service whose .invoke / .resolve_symbol can be mocked."""
    svc = ResearchAgentService(
        valuescan=ValueScanClient(
            config=ValueScanConfig(api_key="ak_x", secret_key="sk_x"),
        ),
        dexscan=DexScanClient(config=DexScanConfig(api_key="dk_x")),
    )
    svc.invoke = invoke  # type: ignore[method-assign]
    if resolve is not None:
        svc.resolve_symbol = resolve  # type: ignore[method-assign]
    return svc


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestQueryHappyPath:
    @pytest.mark.asyncio
    async def test_query_delegates_to_service_invoke(self) -> None:
        invoke = AsyncMock(return_value={"code": 200, "data": {"id": "1"}})
        svc = _service_with_invoke(invoke)
        adapter = StrategyResearchAdapter(service=svc, turn_id="t-1")

        out = await adapter.query("vs.tokens", {"search": "BTC"})

        invoke.assert_awaited_once_with(
            "vs.tokens",
            payload={"search": "BTC"},
            turn_id="t-1",
        )
        assert out["code"] == 200

    @pytest.mark.asyncio
    async def test_query_without_turn_id_passes_none(self) -> None:
        invoke = AsyncMock(return_value={"code": 200})
        svc = _service_with_invoke(invoke)
        adapter = StrategyResearchAdapter(service=svc)  # no turn_id

        await adapter.query("vs.tokens", {"search": "BTC"})
        invoke.assert_awaited_once_with(
            "vs.tokens",
            payload={"search": "BTC"},
            turn_id=None,
        )

    @pytest.mark.asyncio
    async def test_query_accepts_list_payload(self) -> None:
        """DexScan endpoints accept array bodies — the adapter forwards
        them unchanged."""
        invoke = AsyncMock(return_value={"code": 200})
        svc = _service_with_invoke(invoke)
        adapter = StrategyResearchAdapter(service=svc, turn_id="t")

        payload = [{"chainName": "ETH", "tokenContractAddress": "0xabc"}]
        await adapter.query("dex.current_price", payload)
        invoke.assert_awaited_once_with(
            "dex.current_price",
            payload=payload,
            turn_id="t",
        )


class TestResolveSymbolHappyPath:
    @pytest.mark.asyncio
    async def test_resolve_symbol_delegates_to_service(self) -> None:
        invoke = AsyncMock()
        resolve = AsyncMock(return_value=1)
        svc = _service_with_invoke(invoke, resolve)
        adapter = StrategyResearchAdapter(service=svc)

        vid = await adapter.resolve_symbol("BTC")
        assert vid == 1
        resolve.assert_awaited_once_with("BTC")


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


class TestErrorMapping:
    @pytest.mark.asyncio
    async def test_credit_exceeded_maps_correctly(self) -> None:
        invoke = AsyncMock(
            side_effect=ResearchAgentCreditExceededError(
                turn_id="t",
                attempted_cost=3,
                already_spent=18,
                ceiling=20,
            ),
        )
        svc = _service_with_invoke(invoke)
        adapter = StrategyResearchAdapter(service=svc, turn_id="t")

        with pytest.raises(ResearchCreditExceededError):
            await adapter.query("vs.opportunity_list", {})

    @pytest.mark.asyncio
    async def test_not_configured_maps_correctly(self) -> None:
        invoke = AsyncMock(
            side_effect=ResearchAgentNotConfiguredError("VS not configured"),
        )
        svc = _service_with_invoke(invoke)
        adapter = StrategyResearchAdapter(service=svc)

        with pytest.raises(ResearchNotConfiguredError):
            await adapter.query("vs.tokens", {})

    @pytest.mark.asyncio
    async def test_tool_error_maps_to_not_found(self) -> None:
        invoke = AsyncMock(
            side_effect=ResearchAgentToolError("unknown tool"),
        )
        svc = _service_with_invoke(invoke)
        adapter = StrategyResearchAdapter(service=svc)

        with pytest.raises(ResearchToolNotFoundError):
            await adapter.query("vs.nonexistent", {})

    @pytest.mark.asyncio
    async def test_upstream_error_maps_correctly(self) -> None:
        invoke = AsyncMock(
            side_effect=ResearchAgentUpstreamError("HTTP 500"),
        )
        svc = _service_with_invoke(invoke)
        adapter = StrategyResearchAdapter(service=svc)

        with pytest.raises(ResearchUpstreamError):
            await adapter.query("vs.tokens", {})

    @pytest.mark.asyncio
    async def test_all_mapped_classes_are_research_tool_error_subclasses(
        self,
    ) -> None:
        """The strategy-facing API contract says callers can `except
        ResearchToolError` to catch any failure. Verify the inheritance
        chain holds for all subclasses."""
        for cls in (
            ResearchCreditExceededError,
            ResearchNotConfiguredError,
            ResearchToolNotFoundError,
            ResearchUpstreamError,
        ):
            assert issubclass(cls, ResearchToolError)


# ---------------------------------------------------------------------------
# Trade-path guards (ADR-0020 PR-B): timeout + circuit breaker
# ---------------------------------------------------------------------------


async def _slow_invoke(*_a: object, **_k: object) -> dict[str, Any]:
    await asyncio.sleep(1.0)  # far longer than the test timeout
    return {}


class TestTradePathGuards:
    @pytest.mark.asyncio
    async def test_timeout_maps_to_upstream_error(self) -> None:
        # An upstream that stalls past the timeout fails fast as an upstream
        # error — never an unbounded await that would block the tick.
        svc = _service_with_invoke(_slow_invoke)  # type: ignore[arg-type]
        adapter = StrategyResearchAdapter(service=svc, turn_id="t", timeout_seconds=0.05)

        with pytest.raises(ResearchUpstreamError):
            await adapter.query("vs.tokens", {})

    @pytest.mark.asyncio
    async def test_resolve_symbol_timeout_maps_to_upstream_error(self) -> None:
        invoke = AsyncMock()
        svc = _service_with_invoke(invoke, _slow_invoke)  # type: ignore[arg-type]
        adapter = StrategyResearchAdapter(service=svc, timeout_seconds=0.05)

        with pytest.raises(ResearchUpstreamError):
            await adapter.resolve_symbol("BTC")

    @pytest.mark.asyncio
    async def test_breaker_excludes_business_errors(self) -> None:
        # not-configured is a business error: it maps cleanly AND must NOT trip
        # the breaker (a misconfigured key shouldn't open the circuit for all).
        invoke = AsyncMock(side_effect=ResearchAgentNotConfiguredError("no key"))
        svc = _service_with_invoke(invoke)
        breaker = CircuitBreaker(
            name="t",
            failure_threshold=2,
            excluded_exceptions=(ResearchAgentNotConfiguredError,),
        )
        adapter = StrategyResearchAdapter(service=svc, breaker=breaker)

        for _ in range(5):
            with pytest.raises(ResearchNotConfiguredError):
                await adapter.query("vs.tokens", {})
        assert breaker.state is CircuitState.CLOSED  # never tripped

    @pytest.mark.asyncio
    async def test_breaker_opens_after_repeated_transport_failures(self) -> None:
        # Transport failures DO count; after the threshold the breaker opens and
        # subsequent calls fail fast (CircuitOpenError → ResearchUpstreamError).
        invoke = AsyncMock(side_effect=ResearchAgentUpstreamError("HTTP 503"))
        svc = _service_with_invoke(invoke)
        breaker = CircuitBreaker(
            name="t",
            failure_threshold=2,
            recovery_timeout=60.0,
            excluded_exceptions=(ResearchAgentNotConfiguredError,),
        )
        adapter = StrategyResearchAdapter(service=svc, breaker=breaker)

        for _ in range(3):
            with pytest.raises(ResearchUpstreamError):
                await adapter.query("vs.tokens", {})
        assert breaker.state is CircuitState.OPEN
        # Once open, it fails fast without calling the upstream again.
        assert invoke.await_count == 2  # 3rd call short-circuited by the breaker


# ---------------------------------------------------------------------------
# Per-window rate limit (ADR-0020 §4.3): windowed credit "turn"
# ---------------------------------------------------------------------------


class TestPerWindowRateLimit:
    @pytest.mark.asyncio
    async def test_effective_turn_id_windows_by_clock(self) -> None:
        now = [0.0]
        svc = _service_with_invoke(AsyncMock(return_value={}))
        adapter = StrategyResearchAdapter(
            service=svc, turn_id="run", window_seconds=60.0, clock=lambda: now[0]
        )
        assert adapter._effective_turn_id() == "run:w0"
        now[0] = 59.9
        assert adapter._effective_turn_id() == "run:w0"
        now[0] = 60.0
        assert adapter._effective_turn_id() == "run:w1"
        now[0] = 125.0
        assert adapter._effective_turn_id() == "run:w2"

    @pytest.mark.asyncio
    async def test_no_window_uses_fixed_turn_id(self) -> None:
        # Backtest / LLM-loop callers (no window) keep the fixed turn_id.
        invoke = AsyncMock(return_value={"code": 200})
        adapter = StrategyResearchAdapter(service=_service_with_invoke(invoke), turn_id="run")
        await adapter.query("vs.tokens", {})
        assert invoke.await_args.kwargs["turn_id"] == "run"

    @pytest.mark.asyncio
    async def test_credit_budget_resets_across_windows(self) -> None:
        # Real service.invoke (so the governor actually charges); only the
        # upstream client call is mocked. Ceiling 2/window: 2 calls pass, the
        # 3rd in the SAME window is rate-limited, and the next WINDOW is fresh.
        now = [0.0]
        svc = ResearchAgentService(
            valuescan=ValueScanClient(config=ValueScanConfig(api_key="ak", secret_key="sk")),
            dexscan=DexScanClient(config=DexScanConfig(api_key="dk")),
            credit_governor=ResearchCreditGovernor(ceiling=2),
        )
        svc._valuescan.post_endpoint = AsyncMock(return_value={"code": 200})  # type: ignore[method-assign]
        adapter = StrategyResearchAdapter(
            service=svc, turn_id="run", window_seconds=60.0, clock=lambda: now[0]
        )

        await adapter.query("vs.tokens", {})  # 1 credit (window 0)
        await adapter.query("vs.tokens", {})  # 2 credits — at ceiling
        with pytest.raises(ResearchCreditExceededError):
            await adapter.query("vs.tokens", {})  # 3rd in window 0 → rate-limited

        now[0] = 61.0  # cross into window 1 → fresh budget
        await adapter.query("vs.tokens", {})  # ok again


# ---------------------------------------------------------------------------
# NoOpResearch — backtest contexts fail closed
# ---------------------------------------------------------------------------


class TestNoOpResearch:
    @pytest.mark.asyncio
    async def test_query_raises_not_configured(self) -> None:
        noop = NoOpResearch()
        with pytest.raises(ResearchNotConfiguredError, match="not wired"):
            await noop.query("vs.tokens", {"search": "BTC"})

    @pytest.mark.asyncio
    async def test_resolve_symbol_raises_not_configured(self) -> None:
        noop = NoOpResearch()
        with pytest.raises(ResearchNotConfiguredError, match="not wired"):
            await noop.resolve_symbol("BTC")


# ---------------------------------------------------------------------------
# StrategyContext.research default wiring
# ---------------------------------------------------------------------------


class TestStrategyContextResearchDefault:
    def test_default_research_is_noop(self) -> None:
        """A bare StrategyContext (backtest default) gets NoOpResearch
        so the strategy code can attribute `ctx.research` without
        a NoneType error — calls fail with a clear message."""
        from app.strategy_engine.backtest.engine import StrategyContext
        from app.strategy_engine.backtest.portfolio import Portfolio

        ctx = StrategyContext(
            symbol="BTC/USDT",
            timeframe="1h",
            portfolio=Portfolio(initial_cash=10000),
        )
        assert isinstance(ctx.research, NoOpResearch)

    def test_caller_can_override_research(self) -> None:
        """Tests + the live runtime pass their own research surface."""
        from app.strategy_engine.backtest.engine import StrategyContext
        from app.strategy_engine.backtest.portfolio import Portfolio

        custom_research: Any = object()
        ctx = StrategyContext(
            symbol="BTC/USDT",
            timeframe="1h",
            portfolio=Portfolio(initial_cash=10000),
            research=custom_research,
        )
        assert ctx.research is custom_research
