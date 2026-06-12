# -*- coding: utf-8 -*-
"""Tests for the Opportunity Scanner (multi-coin signal scanning)."""

import sys
import os
import json
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class _Stub:
    """Lenient stub: returns itself for any attribute/call, like MagicMock."""
    def __init__(self, **kw):
        self.__dict__.update(kw)
    def __getattr__(self, _name):
        return _Stub()
    def __call__(self, *_a, **_kw):
        return _Stub()


# Module-level stubs for heavy dependencies
for mod_name in [
    "openai", "json_repair", "kc_apollo", "yaml", "aiohttp",
    "motor", "motor.motor_asyncio", "pymongo", "redis",
    "langchain_core", "langchain_core.tools", "langchain_core.callbacks",
    "langgraph", "langgraph.prebuilt",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = _Stub()
sys.modules["json_repair"].loads = json.loads
sys.modules["web.config"] = _Stub(config=_Stub(llm_providers={}, llm_signal_timeout=None))
sys.modules["llm"] = _Stub()
sys.modules["llm.llm"] = _Stub()
sys.modules["llm.base"] = _Stub()


class TestOpportunitySchemas:
    def test_opportunity_item_defaults(self) -> None:
        from web.api.signal_schema import OpportunityItem
        item = OpportunityItem()
        assert item.rank == 0
        assert item.symbol == ""
        assert item.signal == "NEUTRAL"
        assert item.score == 0
        assert item.tradePlan is None
        assert item.riskLevel == "medium"

    def test_opportunity_item_populated(self) -> None:
        from web.api.signal_schema import OpportunityItem, TradePlan
        item = OpportunityItem(
            rank=1,
            symbol="SOL",
            pair="SOL-USDT",
            signal="BUY",
            label="买入",
            score=65.0,
            confidence=82.0,
            change24h=0.058,
            volume24h=2500000000,
            last=172.5,
            keyReasons=["趋势多头排列", "资金流入", "突破前高"],
            tradePlan=TradePlan(entryLow=168, entryHigh=172, stop=162, target1=185),
            riskLevel="low",
            bias="bullish",
            marketState="trend_continuation",
        )
        assert item.rank == 1
        assert item.symbol == "SOL"
        assert item.signal == "BUY"
        assert item.tradePlan.entryLow == 168
        d = item.model_dump()
        assert d["rank"] == 1
        assert "tradePlan" in d

    def test_scan_result_defaults(self) -> None:
        from web.api.signal_schema import OpportunityScanResult
        result = OpportunityScanResult()
        assert result.totalScanned == 0
        assert result.opportunities == []
        assert result.engine == "rule"

    def test_scan_result_serialization(self) -> None:
        from web.api.signal_schema import OpportunityScanResult, OpportunityItem
        result = OpportunityScanResult(
            scanTime="2026-04-25T11:20:00Z",
            totalScanned=50,
            topK=3,
            opportunities=[
                OpportunityItem(rank=1, symbol="BTC", score=45),
                OpportunityItem(rank=2, symbol="ETH", score=38),
                OpportunityItem(rank=3, symbol="SOL", score=35),
            ],
            marketOverview="市场整体偏多。",
            scanDurationMs=1234,
        )
        d = result.model_dump()
        assert d["totalScanned"] == 50
        assert len(d["opportunities"]) == 3
        assert d["opportunities"][0]["symbol"] == "BTC"


class TestOpportunityScannerHelpers:
    def test_extract_symbol(self) -> None:
        from web.api.opportunity_scanner import _extract_symbol
        assert _extract_symbol("BTC-USDT") == "BTC"
        assert _extract_symbol("ETH-USDT") == "ETH"
        assert _extract_symbol("SOL") == "SOL"

    def test_build_market_overview_empty(self) -> None:
        from web.api.opportunity_scanner import _build_market_overview
        overview = _build_market_overview([], 0)
        assert "暂无" in overview

    def test_build_market_overview_bullish(self) -> None:
        from web.api.opportunity_scanner import _build_market_overview
        from web.api.signal_schema import OpportunityItem
        items = [
            OpportunityItem(symbol="BTC", signal="BUY", score=50, change24h=0.03, volume24h=1e9),
            OpportunityItem(symbol="ETH", signal="WEAK_BUY", score=30, change24h=0.02, volume24h=5e8),
            OpportunityItem(symbol="SOL", signal="BUY", score=45, change24h=0.05, volume24h=3e8),
            OpportunityItem(symbol="DOGE", signal="NEUTRAL", score=5, change24h=-0.01, volume24h=1e8),
        ]
        overview = _build_market_overview(items, 20)
        assert "扫描 20 个币种" in overview
        assert "多头信号 3 个" in overview
        assert "BTC" in overview

    def test_build_market_overview_bearish(self) -> None:
        from web.api.opportunity_scanner import _build_market_overview
        from web.api.signal_schema import OpportunityItem
        items = [
            OpportunityItem(symbol="BTC", signal="SELL", score=-50, change24h=-0.05, volume24h=1e9),
            OpportunityItem(symbol="ETH", signal="WEAK_SELL", score=-30, change24h=-0.03, volume24h=5e8),
            OpportunityItem(symbol="SOL", signal="SELL", score=-45, change24h=-0.04, volume24h=3e8),
        ]
        overview = _build_market_overview(items, 10)
        assert "偏空" in overview
        assert "空头信号 3 个" in overview

    def test_build_market_overview_mixed(self) -> None:
        from web.api.opportunity_scanner import _build_market_overview
        from web.api.signal_schema import OpportunityItem
        items = [
            OpportunityItem(symbol="BTC", signal="BUY", score=40, change24h=0.02, volume24h=1e9),
            OpportunityItem(symbol="ETH", signal="SELL", score=-35, change24h=-0.03, volume24h=5e8),
            OpportunityItem(symbol="SOL", signal="NEUTRAL", score=5, change24h=0.01, volume24h=3e8),
        ]
        overview = _build_market_overview(items, 15)
        assert "扫描 15 个币种" in overview


@pytest.mark.asyncio
class TestNoop:
    async def test_noop_returns_value(self) -> None:
        from web.api.opportunity_scanner import _noop
        result = await _noop({"test": 42})
        assert result == {"test": 42}

    async def test_noop_returns_none(self) -> None:
        from web.api.opportunity_scanner import _noop
        result = await _noop(None)
        assert result is None
