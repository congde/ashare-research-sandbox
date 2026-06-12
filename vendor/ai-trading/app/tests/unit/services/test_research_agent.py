"""Unit tests for app.services.research_agent.

Covers catalogue construction, namespace resolution, error mapping
between integration-layer errors and Research-layer errors, and
end-to-end invoke with both ValueScan + DexScan client doubles.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.integrations.dexscan import (
    DEXSCAN_ENDPOINTS,
    DexScanClient,
    DexScanConfig,
    DexScanConfigurationError,
    DexScanEndpointError,
    DexScanHTTPError,
)
from app.integrations.valuescan import (
    VALUESCAN_ENDPOINTS,
    ValueScanClient,
    ValueScanConfig,
    ValueScanConfigurationError,
    ValueScanEndpointError,
)
from app.integrations.valuescan.client import ValueScanHTTPError
from app.services.research_agent import (
    NAMESPACE_SEP,
    ResearchAgentNotConfiguredError,
    ResearchAgentService,
    ResearchAgentToolError,
    ResearchAgentUpstreamError,
    ResearchSource,
    build_research_tool_catalogue,
    resolve_research_tool,
)


# ---------------------------------------------------------------------------
# Catalogue construction
# ---------------------------------------------------------------------------


class TestCatalogue:
    def test_catalogue_includes_every_underlying_endpoint(self) -> None:
        tools = build_research_tool_catalogue()
        expected_count = len(VALUESCAN_ENDPOINTS) + len(DEXSCAN_ENDPOINTS)
        assert len(tools) == expected_count

    def test_namespace_separator_is_dot(self) -> None:
        # If this fails, the dashboard and any consumers need a
        # coordinated rename. Lock the convention.
        assert NAMESPACE_SEP == "."

    def test_valuescan_tools_have_vs_prefix(self) -> None:
        tools = build_research_tool_catalogue()
        vs_tools = [t for t in tools if t.source == ResearchSource.VALUESCAN]
        assert vs_tools, "expected at least one valuescan tool"
        for t in vs_tools:
            assert t.qualified_key.startswith("vs.")

    def test_dexscan_tools_have_dex_prefix(self) -> None:
        tools = build_research_tool_catalogue()
        dex_tools = [t for t in tools if t.source == ResearchSource.DEXSCAN]
        assert dex_tools, "expected at least one dexscan tool"
        for t in dex_tools:
            assert t.qualified_key.startswith("dex.")

    def test_local_key_matches_underlying_endpoint_key(self) -> None:
        tools = build_research_tool_catalogue()
        for t in tools:
            assert t.qualified_key.endswith(t.local_key)
            assert NAMESPACE_SEP not in t.local_key  # un-prefixed

    def test_no_duplicate_qualified_keys(self) -> None:
        tools = build_research_tool_catalogue()
        keys = [t.qualified_key for t in tools]
        assert len(keys) == len(set(keys))


# ---------------------------------------------------------------------------
# Tool resolution
# ---------------------------------------------------------------------------


class TestResolveResearchTool:
    def test_resolves_known_vs_tool(self) -> None:
        tool = resolve_research_tool("vs.tokens")
        assert tool.source == ResearchSource.VALUESCAN
        assert tool.local_key == "tokens"

    def test_resolves_known_dex_tool(self) -> None:
        tool = resolve_research_tool("dex.current_price")
        assert tool.source == ResearchSource.DEXSCAN
        assert tool.local_key == "current_price"

    def test_unknown_tool_raises_with_sample(self) -> None:
        with pytest.raises(ResearchAgentToolError) as exc_info:
            resolve_research_tool("invalid.thing")
        # Error message should list some valid keys to help recovery
        msg = str(exc_info.value)
        assert "Sample" in msg

    def test_empty_key_raises(self) -> None:
        with pytest.raises(ResearchAgentToolError, match="empty"):
            resolve_research_tool("  ")

    def test_unprefixed_key_raises(self) -> None:
        # "tokens" alone is the underlying key, not the qualified one;
        # the resolver must reject it to keep the namespace consistent.
        with pytest.raises(ResearchAgentToolError):
            resolve_research_tool("tokens")


# ---------------------------------------------------------------------------
# Service catalogue snapshot
# ---------------------------------------------------------------------------


def _fake_vs_client(*, configured: bool) -> ValueScanClient:
    config = ValueScanConfig(
        api_key="ak_x" if configured else "",
        secret_key="sk_x" if configured else "",
    )
    return ValueScanClient(config=config)


def _fake_dex_client(*, configured: bool) -> DexScanClient:
    config = DexScanConfig(api_key="dk_x" if configured else "")
    return DexScanClient(config=config)


class TestServiceCatalogue:
    def test_both_configured(self) -> None:
        svc = ResearchAgentService(
            valuescan=_fake_vs_client(configured=True),
            dexscan=_fake_dex_client(configured=True),
        )
        cat = svc.catalogue()
        assert cat.valuescan_configured is True
        assert cat.dexscan_configured is True
        assert cat.tool_count == len(VALUESCAN_ENDPOINTS) + len(DEXSCAN_ENDPOINTS)

    def test_only_vs_configured(self) -> None:
        svc = ResearchAgentService(
            valuescan=_fake_vs_client(configured=True),
            dexscan=_fake_dex_client(configured=False),
        )
        cat = svc.catalogue()
        assert cat.valuescan_configured is True
        assert cat.dexscan_configured is False
        # Catalogue still lists ALL tools; configuration is independent
        # of which tools are visible to the UI.
        assert cat.tool_count == len(VALUESCAN_ENDPOINTS) + len(DEXSCAN_ENDPOINTS)

    def test_by_source_grouping(self) -> None:
        svc = ResearchAgentService(
            valuescan=_fake_vs_client(configured=True),
            dexscan=_fake_dex_client(configured=True),
        )
        cat = svc.catalogue()
        groups = cat.by_source
        assert len(groups[ResearchSource.VALUESCAN]) == len(VALUESCAN_ENDPOINTS)
        assert len(groups[ResearchSource.DEXSCAN]) == len(DEXSCAN_ENDPOINTS)


# ---------------------------------------------------------------------------
# Tool invocation — happy paths
# ---------------------------------------------------------------------------


class TestInvoke:
    @pytest.mark.asyncio
    async def test_invoke_vs_tool_routes_to_valuescan_client(self) -> None:
        vs = _fake_vs_client(configured=True)
        vs.post_endpoint = AsyncMock(return_value={"code": 200, "data": {"id": "1"}})

        svc = ResearchAgentService(
            valuescan=vs,
            dexscan=_fake_dex_client(configured=True),
        )
        result = await svc.invoke("vs.tokens", payload={"search": "BTC"})

        vs.post_endpoint.assert_awaited_once_with("tokens", {"search": "BTC"})
        assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_invoke_dex_tool_routes_to_dexscan_client(self) -> None:
        dex = _fake_dex_client(configured=True)
        dex.post_endpoint = AsyncMock(return_value={"code": 200, "data": {"price": 0.0001}})

        svc = ResearchAgentService(
            valuescan=_fake_vs_client(configured=True),
            dexscan=dex,
        )
        body = [{"name": "USDT", "chain": "ETH"}]
        result = await svc.invoke("dex.current_price", payload=body)

        dex.post_endpoint.assert_awaited_once_with("current_price", body)
        assert result["data"]["price"] == 0.0001

    @pytest.mark.asyncio
    async def test_vs_rejects_list_payload(self) -> None:
        """ValueScan endpoints only accept dict bodies — list should
        raise a tool error BEFORE hitting the client."""
        vs = _fake_vs_client(configured=True)
        vs.post_endpoint = AsyncMock()

        svc = ResearchAgentService(
            valuescan=vs, dexscan=_fake_dex_client(configured=True),
        )
        with pytest.raises(ResearchAgentToolError, match="expects a dict"):
            await svc.invoke("vs.tokens", payload=[{"search": "x"}])

        vs.post_endpoint.assert_not_awaited()


# ---------------------------------------------------------------------------
# Tool invocation — error mapping
# ---------------------------------------------------------------------------


class TestErrorMapping:
    @pytest.mark.asyncio
    async def test_unknown_tool_raises_tool_error(self) -> None:
        svc = ResearchAgentService(
            valuescan=_fake_vs_client(configured=True),
            dexscan=_fake_dex_client(configured=True),
        )
        with pytest.raises(ResearchAgentToolError):
            await svc.invoke("not.real")

    @pytest.mark.asyncio
    async def test_vs_unconfigured_maps_to_not_configured(self) -> None:
        vs = _fake_vs_client(configured=True)
        vs.post_endpoint = AsyncMock(
            side_effect=ValueScanConfigurationError("VS not configured"),
        )

        svc = ResearchAgentService(
            valuescan=vs, dexscan=_fake_dex_client(configured=True),
        )
        with pytest.raises(ResearchAgentNotConfiguredError):
            await svc.invoke("vs.tokens", payload={})

    @pytest.mark.asyncio
    async def test_dex_unconfigured_maps_to_not_configured(self) -> None:
        dex = _fake_dex_client(configured=True)
        dex.post_endpoint = AsyncMock(
            side_effect=DexScanConfigurationError("DEX not configured"),
        )

        svc = ResearchAgentService(
            valuescan=_fake_vs_client(configured=True), dexscan=dex,
        )
        with pytest.raises(ResearchAgentNotConfiguredError):
            await svc.invoke("dex.current_price", payload={})

    @pytest.mark.asyncio
    async def test_vs_http_error_maps_to_upstream_error(self) -> None:
        vs = _fake_vs_client(configured=True)
        vs.post_endpoint = AsyncMock(
            side_effect=ValueScanHTTPError("HTTP 500"),
        )

        svc = ResearchAgentService(
            valuescan=vs, dexscan=_fake_dex_client(configured=True),
        )
        with pytest.raises(ResearchAgentUpstreamError):
            await svc.invoke("vs.tokens", payload={})

    @pytest.mark.asyncio
    async def test_dex_http_error_maps_to_upstream_error(self) -> None:
        dex = _fake_dex_client(configured=True)
        dex.post_endpoint = AsyncMock(
            side_effect=DexScanHTTPError("HTTP 500 upstream"),
        )

        svc = ResearchAgentService(
            valuescan=_fake_vs_client(configured=True), dexscan=dex,
        )
        with pytest.raises(ResearchAgentUpstreamError):
            await svc.invoke("dex.current_price", payload={})

    @pytest.mark.asyncio
    async def test_vs_bad_endpoint_maps_to_tool_error(self) -> None:
        vs = _fake_vs_client(configured=True)
        vs.post_endpoint = AsyncMock(
            side_effect=ValueScanEndpointError("bad endpoint"),
        )

        svc = ResearchAgentService(
            valuescan=vs, dexscan=_fake_dex_client(configured=True),
        )
        with pytest.raises(ResearchAgentToolError):
            await svc.invoke("vs.tokens", payload={})

    @pytest.mark.asyncio
    async def test_dex_bad_endpoint_maps_to_tool_error(self) -> None:
        dex = _fake_dex_client(configured=True)
        dex.post_endpoint = AsyncMock(
            side_effect=DexScanEndpointError("bad endpoint"),
        )

        svc = ResearchAgentService(
            valuescan=_fake_vs_client(configured=True), dexscan=dex,
        )
        with pytest.raises(ResearchAgentToolError):
            await svc.invoke("dex.current_price", payload={})


# ---------------------------------------------------------------------------
# Lazy client construction
# ---------------------------------------------------------------------------


class TestLazyClients:
    def test_catalogue_uses_default_clients_when_none_injected(self) -> None:
        """Service without injected clients should still build the
        catalogue (the underlying clients construct from settings
        without raising)."""
        svc = ResearchAgentService()
        # Should not raise — catalogue() does NOT call upstream.
        cat = svc.catalogue()
        assert cat.tool_count > 0


# ---------------------------------------------------------------------------
# Token cache + credit governor wiring
# ---------------------------------------------------------------------------


class TestSymbolResolution:
    @pytest.mark.asyncio
    async def test_resolve_symbol_calls_cache(self) -> None:
        from app.services.valuescan_token_cache import ValueScanTokenCache

        cache = ValueScanTokenCache(client=_fake_vs_client(configured=True))
        cache.resolve = AsyncMock(return_value=42)  # type: ignore[method-assign]

        svc = ResearchAgentService(
            valuescan=_fake_vs_client(configured=True),
            dexscan=_fake_dex_client(configured=True),
            token_cache=cache,
        )
        vid = await svc.resolve_symbol("BTC")
        assert vid == 42
        cache.resolve.assert_awaited_once_with("BTC")

    @pytest.mark.asyncio
    async def test_resolve_symbol_not_found_maps_to_tool_error(self) -> None:
        from app.services.valuescan_token_cache import (
            TokenNotFoundError,
            ValueScanTokenCache,
        )

        cache = ValueScanTokenCache(client=_fake_vs_client(configured=True))
        cache.resolve = AsyncMock(  # type: ignore[method-assign]
            side_effect=TokenNotFoundError("nope"),
        )
        svc = ResearchAgentService(
            valuescan=_fake_vs_client(configured=True),
            dexscan=_fake_dex_client(configured=True),
            token_cache=cache,
        )
        with pytest.raises(ResearchAgentToolError):
            await svc.resolve_symbol("UNKNOWN")


class TestMCPRouting:
    @pytest.mark.asyncio
    async def test_resolve_mcp_key_synthesises_tool(self) -> None:
        from app.services.research_agent import resolve_research_tool

        tool = resolve_research_tool("mcp.vs_token_detail")
        assert tool.source == ResearchSource.MCP
        assert tool.local_key == "vs_token_detail"
        assert tool.body_shape == "mcp"

    @pytest.mark.asyncio
    async def test_resolve_empty_mcp_name_raises(self) -> None:
        from app.services.research_agent import resolve_research_tool

        with pytest.raises(ResearchAgentToolError, match="missing name"):
            resolve_research_tool("mcp.")

    @pytest.mark.asyncio
    async def test_invoke_mcp_routes_to_mcp_client(self) -> None:
        """MCP tools route through ValueScanMCPClient.call_tool."""
        from app.integrations.valuescan import (
            ValueScanMCPClient,
            ValueScanMCPConfig,
        )

        mcp = ValueScanMCPClient(
            config=ValueScanMCPConfig(api_key="ak_x", secret_key="sk_x"),
        )
        mcp.call_tool = AsyncMock(  # type: ignore[method-assign]
            return_value={"content": [{"type": "text", "text": "ok"}]},
        )

        svc = ResearchAgentService(
            valuescan=_fake_vs_client(configured=True),
            dexscan=_fake_dex_client(configured=True),
            mcp=mcp,
        )

        out = await svc.invoke("mcp.vs_token_detail", payload={"vsTokenId": 1})
        mcp.call_tool.assert_awaited_once_with(
            "vs_token_detail", {"vsTokenId": 1},
        )
        assert "content" in out

    @pytest.mark.asyncio
    async def test_invoke_mcp_rejects_list_payload(self) -> None:
        from app.integrations.valuescan import (
            ValueScanMCPClient,
            ValueScanMCPConfig,
        )

        mcp = ValueScanMCPClient(
            config=ValueScanMCPConfig(api_key="ak_x", secret_key="sk_x"),
        )
        mcp.call_tool = AsyncMock()  # type: ignore[method-assign]

        svc = ResearchAgentService(
            valuescan=_fake_vs_client(configured=True),
            dexscan=_fake_dex_client(configured=True),
            mcp=mcp,
        )

        with pytest.raises(ResearchAgentToolError, match="dict"):
            await svc.invoke("mcp.vs_token_detail", payload=[1, 2, 3])
        mcp.call_tool.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_catalogue_with_mcp_includes_discovered_tools(self) -> None:
        """catalogue_with_mcp() augments the REST catalogue with
        MCP-discovered tools."""
        from app.integrations.valuescan import (
            MCPTool,
            ValueScanMCPClient,
            ValueScanMCPConfig,
        )

        mcp = ValueScanMCPClient(
            config=ValueScanMCPConfig(api_key="ak_x", secret_key="sk_x"),
        )
        mcp.list_tools = AsyncMock(  # type: ignore[method-assign]
            return_value=(
                MCPTool(name="vs_kline", description="K-line data"),
                MCPTool(name="ai_chance_coin_list", description="opportunity"),
            ),
        )

        svc = ResearchAgentService(
            valuescan=_fake_vs_client(configured=True),
            dexscan=_fake_dex_client(configured=True),
            mcp=mcp,
        )

        cat = await svc.catalogue_with_mcp()
        mcp_qualified_keys = {
            t.qualified_key for t in cat.tools if t.source == ResearchSource.MCP
        }
        assert "mcp.vs_kline" in mcp_qualified_keys
        assert "mcp.ai_chance_coin_list" in mcp_qualified_keys

    @pytest.mark.asyncio
    async def test_catalogue_caches_mcp_discovery(self) -> None:
        """Second call to catalogue_with_mcp() should NOT re-issue the
        SSE handshake."""
        from app.integrations.valuescan import (
            MCPTool,
            ValueScanMCPClient,
            ValueScanMCPConfig,
        )

        mcp = ValueScanMCPClient(
            config=ValueScanMCPConfig(api_key="ak_x", secret_key="sk_x"),
        )
        mcp.list_tools = AsyncMock(  # type: ignore[method-assign]
            return_value=(MCPTool(name="vs_kline", description="K-line"),),
        )

        svc = ResearchAgentService(
            valuescan=_fake_vs_client(configured=True),
            dexscan=_fake_dex_client(configured=True),
            mcp=mcp,
        )

        await svc.catalogue_with_mcp()
        await svc.catalogue_with_mcp()
        await svc.catalogue_with_mcp()
        # Cache hit on calls 2 + 3.
        assert mcp.list_tools.await_count == 1

        # Explicit refresh hits upstream again.
        await svc.catalogue_with_mcp(refresh=True)
        assert mcp.list_tools.await_count == 2


class TestCreditGovernor:
    @pytest.mark.asyncio
    async def test_invoke_with_turn_id_charges_governor(self) -> None:
        from app.services.research_credit_governor import ResearchCreditGovernor

        vs = _fake_vs_client(configured=True)
        vs.post_endpoint = AsyncMock(return_value={"code": 200})

        gov = ResearchCreditGovernor(ceiling=20)
        svc = ResearchAgentService(
            valuescan=vs,
            dexscan=_fake_dex_client(configured=True),
            credit_governor=gov,
        )

        await svc.invoke("vs.tokens", payload={}, turn_id="t-1")
        assert await gov.spent_for("t-1") == 1  # vs.tokens = 1 credit

    @pytest.mark.asyncio
    async def test_invoke_without_turn_id_skips_charge(self) -> None:
        from app.services.research_credit_governor import ResearchCreditGovernor

        vs = _fake_vs_client(configured=True)
        vs.post_endpoint = AsyncMock(return_value={"code": 200})

        gov = ResearchCreditGovernor(ceiling=20)
        svc = ResearchAgentService(
            valuescan=vs,
            dexscan=_fake_dex_client(configured=True),
            credit_governor=gov,
        )

        await svc.invoke("vs.tokens", payload={})
        # No turn → no charge accumulation
        assert await gov.spent_for("anything") == 0

    @pytest.mark.asyncio
    async def test_ceiling_exceeded_raises_credit_error_without_upstream_call(
        self,
    ) -> None:
        """Important: the charge must happen BEFORE the upstream call
        so we don't waste a paid credit when a turn is over budget."""
        from app.services.research_agent import (
            ResearchAgentCreditExceededError,
        )
        from app.services.research_credit_governor import ResearchCreditGovernor

        vs = _fake_vs_client(configured=True)
        vs.post_endpoint = AsyncMock(return_value={"code": 200})

        # Tiny ceiling — second call over the limit
        gov = ResearchCreditGovernor(ceiling=1)
        svc = ResearchAgentService(
            valuescan=vs,
            dexscan=_fake_dex_client(configured=True),
            credit_governor=gov,
        )

        await svc.invoke("vs.tokens", payload={}, turn_id="t-1")
        vs.post_endpoint.reset_mock()

        with pytest.raises(ResearchAgentCreditExceededError) as exc_info:
            await svc.invoke("vs.tokens", payload={}, turn_id="t-1")

        # Upstream MUST NOT have been called after the ceiling kicked in.
        vs.post_endpoint.assert_not_awaited()
        exc = exc_info.value
        assert exc.turn_id == "t-1"
        assert exc.ceiling == 1
