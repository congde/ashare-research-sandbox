# -*- coding: utf-8 -*-
"""End-to-end self-test: simulates the full data flow for both
TradingAgents LLM signal integration and Opportunity Scanner
with mocked external services."""

import sys
import os
import json
from dataclasses import dataclass, field
from unittest.mock import patch

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
    "langgraph", "langgraph.prebuilt", "dc_api_security",
    "dc_api_security.kc_eureka", "dc_api_security.kc_eureka.http_client",
    "httpx", "libs", "libs.http",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = _Stub()
sys.modules["json_repair"].loads = json.loads
sys.modules["web.config"] = _Stub(config=_Stub(llm_providers={}, llm_signal_timeout=None))
sys.modules["llm"] = _Stub()
sys.modules["llm.llm"] = _Stub(DefaultLLM=_Stub())
sys.modules["llm.base"] = _Stub()


@dataclass
class MockSignalResult:
    signal: str = "WEAK_BUY"
    label: str = "偏多观望"
    score: float = 25.0
    confidence: float = 60.0
    reasons: list = field(default_factory=lambda: ["4h 均线多头", "RSI 55 中性偏多", "量比 1.2x"])
    summary: str = "BTC 4h 趋势偏多"
    trade_plan: dict = field(default_factory=lambda: {
        "support": 93000, "resistance": 97000,
        "entryLow": 94500, "entryHigh": 95500,
        "stop": 92500, "target1": 97000, "target2": 99000,
    })


@pytest.mark.asyncio
class TestE2EOpportunityScanner:
    async def test_scan_with_explicit_symbols(self) -> None:
        from web.api.opportunity_scanner import scan_opportunities

        mock_kline = {
            "1hour": {"trend": "bullish", "rsi": 55, "regime": "trending", "breakout": "none",
                      "volRatio": 1.2, "rangePos": 60, "bbPctB": 55, "bbWidth": 3.5},
            "4hour": {"trend": "bullish", "rsi": 58, "regime": "trending", "breakout": "none",
                      "volRatio": 1.1, "rangePos": 65, "bbPctB": 60, "bbWidth": 4.0},
        }
        mock_market = {"last": 95000, "changeRate": 0.025, "volValue": 5000000000,
                       "vol": 52000, "high": 96000, "low": 93500, "buy": 94990, "sell": 95010}
        mock_vs = {"fund": {"net": 1000000}, "sentiment": {"score": 72}, "priceIndicators": {}}

        async def mock_kline_signals(pair):
            return mock_kline

        async def mock_market_stats(pair):
            return mock_market

        async def mock_vs_data(sym):
            return mock_vs

        with (
            patch("web.api.dashboard_service.fetch_kline_signals", side_effect=mock_kline_signals),
            patch("web.api.dashboard_service.fetch_market_stats", side_effect=mock_market_stats),
            patch("web.api.dashboard_service.fetch_valuescan_signal_data", side_effect=mock_vs_data),
            patch("web.api.signal_analyzer.compute_signal") as mock_compute,
        ):

            results_map = {
                0: MockSignalResult(signal="BUY", score=45, confidence=75, reasons=["强势突破"]),
                1: MockSignalResult(signal="WEAK_BUY", score=25, confidence=55, reasons=["偏多震荡"]),
                2: MockSignalResult(signal="NEUTRAL", score=5, confidence=30, reasons=["方向不明"]),
            }
            call_count = [0]

            def _compute(data):
                idx = call_count[0] % 3
                call_count[0] += 1
                return results_map[idx]

            mock_compute.side_effect = _compute

            result = await scan_opportunities(
                symbols=["BTC", "ETH", "SOL"],
                top_k=3,
                use_valuescan=True,
            )

        assert result.totalScanned == 3
        assert len(result.opportunities) == 3
        assert result.scanDurationMs >= 0
        assert "扫描 3 个币种" in result.marketOverview

        scores = [o.score for o in result.opportunities]
        abs_scores = [abs(s) for s in scores]
        assert abs_scores == sorted(abs_scores, reverse=True)

        assert result.opportunities[0].rank == 1
        assert result.opportunities[1].rank == 2

        top = result.opportunities[0]
        assert top.signal == "BUY"
        assert top.score == 45
        assert top.volume24h == 5000000000
        assert top.change24h == 0.025

    async def test_scan_handles_partial_failures(self) -> None:
        from web.api.opportunity_scanner import scan_opportunities

        async def mock_kline_signals(pair):
            if "FAIL" in pair:
                raise ConnectionError("Network timeout")
            return {"1hour": {"trend": "bullish", "rsi": 50}}

        async def mock_market_stats(pair):
            return {"last": 100, "changeRate": 0.01, "volValue": 1e6}

        async def mock_vs_data(sym):
            return {}

        with (
            patch("web.api.dashboard_service.fetch_kline_signals", side_effect=mock_kline_signals),
            patch("web.api.dashboard_service.fetch_market_stats", side_effect=mock_market_stats),
            patch("web.api.dashboard_service.fetch_valuescan_signal_data", side_effect=mock_vs_data),
            patch("web.api.signal_analyzer.compute_signal") as mock_compute,
        ):
            mock_compute.return_value = MockSignalResult(signal="NEUTRAL", score=10, confidence=40)

            result = await scan_opportunities(
                symbols=["BTC", "FAIL-TOKEN", "ETH"],
                top_k=5,
                use_valuescan=False,
            )

        assert result.totalScanned == 3
        assert len(result.opportunities) >= 2

    async def test_scan_empty_candidates(self) -> None:
        from web.api.opportunity_scanner import scan_opportunities

        result = await scan_opportunities(symbols=[], top_k=10)

        assert result.totalScanned == 0
        assert len(result.opportunities) == 0
        assert len(result.errors) > 0


class TestE2ETradingAgentsBridge:
    def test_full_ta_to_llm_context_pipeline(self) -> None:
        from web.api.ta_signal_bridge import format_ta_for_llm_context, extract_ta_signal_hints
        from web.api.llm_signal_analyzer import _fmt_trading_agents, _build_context, _build_data_quality

        ta_data = {
            "available": True,
            "symbol": "BTC",
            "dataSource": "kucoin",
            "latencyMs": 8500,
            "marketReport": "BTC is in a clear uptrend on 4h timeframe.",
            "sentimentReport": "Social sentiment is moderately bullish.",
            "newsReport": "No major negative news.",
            "fundamentalsReport": "Hash rate at all-time high.",
            "bullAnalystReport": "Strong technical setup with volume confirmation.",
            "bearAnalystReport": "RSI approaching overbought on daily.",
            "riskManagerReport": "Overall risk is moderate.",
            "traderPlan": "Entry zone: 94500-95200. Stop: 92500.",
            "finalDecision": "Buy BTC with moderate conviction.",
        }

        formatted = format_ta_for_llm_context(ta_data)
        assert "Market Analyst" in formatted
        assert "Bull Analyst" in formatted
        assert "Bear Analyst" in formatted
        assert "Risk Manager" in formatted
        assert "Trader Plan" in formatted
        assert "Final Decision" in formatted
        assert "uptrend" in formatted
        assert "92500" in formatted

        hints = extract_ta_signal_hints(ta_data)
        assert hints.get("bias") == "bullish"
        assert len(hints.get("reasons", [])) >= 1

        data = {
            "symbol": "BTC",
            "market": {"last": 95000, "changeRate": 0.025, "volValue": 5e9},
            "kline": {
                "15min": {"trend": "bullish", "rsi": 54},
                "1hour": {"trend": "bullish", "rsi": 55},
                "4hour": {"trend": "bullish", "rsi": 58},
                "1day": {"trend": "weak_bullish", "rsi": 52},
            },
            "onchain": {"summary": "Active addresses up"},
            "onchainMetrics": {"fearGreed": {"value": 68, "label": "Greed"}},
            "news": [{"title": "BTC ETF inflows surge", "publishedAt": "2026-06-05T10:00:00Z"}],
            "newsMeta": {"totalCount": 1, "freshCount": 1, "gateHours": 12, "gateApplicable": True},
            "realtime": {"available": True, "markPrice": 95000, "spotLast": 95000},
            "quantFactors": {"available": True, "overallCompleteness": 0.85, "aggregateScore": 0.2, "side": "buy"},
            "valuescan": {
                "vsTokenId": 1,
                "fund": {"net": 5000000},
                "sentiment": {"score": 72},
                "tokenFlow": {"spot": 3000000, "futures": 2000000},
                "priceIndicators": {"price": 95000},
                "whaleCost": [{"date": "2026-04-24", "cost": 93500}],
                "supportResistance": [{"price": 93000, "type": "support"}],
                "largeTransactions": [{"amount": 1}],
                "holderList": [{"label": "whale"}],
                "tokenDetail": {"id": 1},
                "aiSignals": {"score": 1},
            },
            "derivatives": {
                "futuresSymbol": "XBTUSDTM",
                "fundingRate": 0.0001,
                "predictedFundingRate": 0.00012,
                "openInterest": 12345678,
                "futuresLast": 95120,
            },
            "microstructure": {
                "orderbook": {
                    "spread": 1.5,
                    "spreadPct": 0.0016,
                    "imbalance": 0.12,
                    "bidNotional": 2500000,
                    "askNotional": 2200000,
                },
                "recentTrades": {
                    "count": 50,
                    "buyRatio": 0.57,
                    "buyNotional": 1800000,
                    "sellNotional": 1350000,
                },
            },
            "tradingAgents": ta_data,
        }

        ta_text = _fmt_trading_agents(data)
        assert "TradingAgents" in ta_text
        assert "uptrend" in ta_text

        context = _build_context(data)
        assert "TradingAgents 多智能体辩论" in context
        assert "Final Decision" in context

        dq = _build_data_quality(data)
        assert "tradingAgents" in dq.sourceStatus
        assert dq.sourceStatus["tradingAgents"] == "ok"
        assert dq.coverageScore >= 0.85

    def test_ta_enrichment_populates_debate_block(self) -> None:
        from web.api.signal_schema import SignalOutput, EngineMeta, DataQuality
        from web.api.llm_signal_analyzer import _enrich_result

        class MockRule:
            signal = "WEAK_BUY"
            score = 20.0
            confidence = 55.0
            reasons = ["技术面偏多"]
            summary = ""
            trade_plan = None

        data = {
            "symbol": "BTC",
            "kline": {"4hour": {"trend": "bullish"}},
            "market": {"last": 95000},
            "tradingAgents": {
                "available": True,
                "dataSource": "all",
                "latencyMs": 12000,
                "marketReport": "Strong uptrend confirmed.",
                "sentimentReport": "Bullish consensus.",
                "newsReport": "Positive institutional adoption.",
                "fundamentalsReport": "Hash rate at highs.",
                "bullAnalystReport": "Clear buy setup with volume breakout.",
                "bearAnalystReport": "Caution: daily RSI approaching 70.",
                "riskManagerReport": "Risk moderate. Use 60% position.",
                "traderPlan": "Buy 94500-95200, stop 92500.",
                "finalDecision": "Strong buy with risk management.",
            }
        }

        result = SignalOutput(
            signal="BUY",
            score=45.0,
            confidence=75.0,
            engineMeta=EngineMeta(model="test-e2e", analysisVersion="v2"),
        )

        enriched = _enrich_result(
            result, data=data,
            rule_result=MockRule(),
            data_quality=DataQuality(coverageScore=0.9, sourceStatus={"market": "ok"}),
            model="test-e2e",
        )

        ta = enriched.tradingAgentsDebate
        assert ta.available
        assert ta.dataSource == "all"
        assert ta.latencyMs == 12000
        assert "Strong uptrend" in ta.marketSummary
        assert "buy setup" in ta.bullArgument
        assert "RSI approaching" in ta.bearArgument
        assert "Risk moderate" in ta.riskAssessment
        assert "Strong buy" in ta.finalDecision

        assert enriched.debug.sourceRefs.get("tradingAgents")

        d = enriched.model_dump()
        assert d["tradingAgentsDebate"]["available"]
        assert d["tradingAgentsDebate"]["latencyMs"] == 12000
