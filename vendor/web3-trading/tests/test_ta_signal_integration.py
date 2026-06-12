# -*- coding: utf-8 -*-
"""Tests for TradingAgents ↔ LLM Signal Analyzer integration."""

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
    "fastapi", "fastapi.responses", "fastapi.requests",
    "langchain_core", "langchain_core.tools", "langchain_core.callbacks",
    "langgraph", "langgraph.prebuilt",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = _Stub()
sys.modules["json_repair"].loads = json.loads
sys.modules["web.config"] = _Stub(config=_Stub(llm_providers={}, llm_signal_timeout=None))
sys.modules["llm"] = _Stub()
sys.modules["llm.llm"] = _Stub(DefaultLLM=_Stub())
sys.modules["llm.base"] = _Stub()


# ===================================================================
# TradingAgentsDebateBlock schema
# ===================================================================

class TestTradingAgentsDebateBlock:
    def test_default_block(self) -> None:
        from web.api.signal_schema import TradingAgentsDebateBlock
        block = TradingAgentsDebateBlock()
        assert not block.available
        assert block.dataSource == ""
        assert block.latencyMs == 0
        assert block.marketSummary == ""
        assert block.finalDecision == ""

    def test_populated_block(self) -> None:
        from web.api.signal_schema import TradingAgentsDebateBlock
        block = TradingAgentsDebateBlock(
            available=True,
            dataSource="kucoin",
            latencyMs=5000,
            marketSummary="BTC is trending up",
            sentimentSummary="Market sentiment is positive",
            newsSummary="No major news",
            fundamentalsSummary="On-chain activity increasing",
            bullArgument="Strong momentum, buy the dip",
            bearArgument="Overextended, likely pullback",
            riskAssessment="Moderate risk due to leverage",
            traderPlan="Entry at 95000, stop at 93000",
            finalDecision="Buy with caution",
        )
        assert block.available
        assert block.dataSource == "kucoin"
        assert block.latencyMs == 5000
        assert "trending up" in block.marketSummary

    def test_signal_output_has_ta_debate(self) -> None:
        from web.api.signal_schema import SignalOutput, TradingAgentsDebateBlock
        output = SignalOutput()
        assert isinstance(output.tradingAgentsDebate, TradingAgentsDebateBlock)
        assert not output.tradingAgentsDebate.available

    def test_signal_output_serialization(self) -> None:
        from web.api.signal_schema import SignalOutput, TradingAgentsDebateBlock
        output = SignalOutput(
            signal="BUY",
            tradingAgentsDebate=TradingAgentsDebateBlock(
                available=True,
                dataSource="all",
                finalDecision="Strong buy signal",
            ),
        )
        d = output.model_dump()
        assert "tradingAgentsDebate" in d
        assert d["tradingAgentsDebate"]["available"]
        assert d["tradingAgentsDebate"]["finalDecision"] == "Strong buy signal"


# ===================================================================
# TA Signal Bridge
# ===================================================================

class TestTASignalBridge:
    def test_format_empty_ta(self) -> None:
        from web.api.ta_signal_bridge import format_ta_for_llm_context
        assert format_ta_for_llm_context(None) == ""
        assert format_ta_for_llm_context({}) == ""
        assert format_ta_for_llm_context({"available": False}) == ""

    def test_format_basic_ta(self) -> None:
        from web.api.ta_signal_bridge import format_ta_for_llm_context
        ta_data = {
            "available": True,
            "dataSource": "kucoin",
            "latencyMs": 12345,
            "marketReport": "BTC shows strong momentum above 95000 with volume confirmation.",
            "sentimentReport": "Social sentiment is bullish, fear-greed at 72.",
            "newsReport": "",
            "fundamentalsReport": "Network hash rate at ATH.",
            "traderPlan": "Entry 94800-95200, stop 93500.",
            "finalDecision": "Buy with moderate conviction.",
        }
        text = format_ta_for_llm_context(ta_data)
        assert "TradingAgents" in text
        assert "kucoin" in text
        assert "Market Analyst" in text
        assert "strong momentum" in text
        assert "Sentiment Analyst" in text
        assert "Fundamentals Analyst" in text
        assert "Trader Plan" in text
        assert "Final Decision" in text
        assert "News Analyst" not in text

    def test_format_with_debate(self) -> None:
        from web.api.ta_signal_bridge import format_ta_for_llm_context
        ta_data = {
            "available": True,
            "dataSource": "all",
            "latencyMs": 8000,
            "marketReport": "Uptrend intact.",
            "bullAnalystReport": "Volume supports continuation.",
            "bearAnalystReport": "RSI divergence warns of pullback.",
            "riskManagerReport": "Keep position size moderate.",
            "finalDecision": "Cautious long.",
        }
        text = format_ta_for_llm_context(ta_data)
        assert "Bull Analyst" in text
        assert "Bear Analyst" in text
        assert "Risk Manager" in text
        assert "Volume supports" in text
        assert "RSI divergence" in text

    def test_extract_hints_bullish(self) -> None:
        from web.api.ta_signal_bridge import extract_ta_signal_hints
        hints = extract_ta_signal_hints({
            "available": True,
            "finalDecision": "We recommend a Buy position with accumulate strategy.",
            "traderPlan": "Entry at 95000.",
        })
        assert hints.get("bias") == "bullish"
        assert len(hints.get("reasons", [])) >= 1

    def test_extract_hints_bearish(self) -> None:
        from web.api.ta_signal_bridge import extract_ta_signal_hints
        hints = extract_ta_signal_hints({
            "available": True,
            "finalDecision": "Sell signal confirmed, bearish outlook for short term.",
        })
        assert hints.get("bias") == "bearish"

    def test_extract_hints_neutral(self) -> None:
        from web.api.ta_signal_bridge import extract_ta_signal_hints
        hints = extract_ta_signal_hints({
            "available": True,
            "finalDecision": "Hold current position, wait for better entry.",
        })
        assert hints.get("bias") == "neutral"

    def test_extract_hints_unavailable(self) -> None:
        from web.api.ta_signal_bridge import extract_ta_signal_hints
        assert extract_ta_signal_hints(None) == {}
        assert extract_ta_signal_hints({"available": False}) == {}

    def test_camel_conversion(self) -> None:
        from web.api.ta_signal_bridge import _camel
        assert _camel("bull_analyst_report") == "bullAnalystReport"
        assert _camel("risk_manager_report") == "riskManagerReport"
        assert _camel("market_report") == "marketReport"
        assert _camel("single") == "single"


# ===================================================================
# LLM Signal Analyzer — TA integration
# ===================================================================

class TestLLMSignalAnalyzerTAIntegration:
    def test_fmt_trading_agents_unavailable(self) -> None:
        from web.api.llm_signal_analyzer import _fmt_trading_agents
        assert "未启用" in _fmt_trading_agents({})
        assert "未启用" in _fmt_trading_agents({"tradingAgents": None})
        assert "未启用" in _fmt_trading_agents({"tradingAgents": {"available": False}})

    def test_fmt_trading_agents_available(self) -> None:
        from web.api.llm_signal_analyzer import _fmt_trading_agents
        data = {
            "tradingAgents": {
                "available": True,
                "dataSource": "kucoin",
                "latencyMs": 5000,
                "marketReport": "BTC bullish above 95000.",
                "finalDecision": "Buy.",
            }
        }
        result = _fmt_trading_agents(data)
        assert "TradingAgents" in result
        assert "BTC bullish" in result

    def test_build_context_includes_ta(self) -> None:
        from web.api.llm_signal_analyzer import _build_context
        data = {
            "symbol": "BTC",
            "market": {"last": 95000},
            "kline": {},
            "onchain": {},
            "news": [],
            "valuescan": {},
            "tradingAgents": {
                "available": True,
                "dataSource": "all",
                "latencyMs": 3000,
                "marketReport": "Strong trend.",
                "finalDecision": "Accumulate BTC.",
            }
        }
        context = _build_context(data)
        assert "TradingAgents 多智能体辩论" in context
        assert "Strong trend" in context
        assert "Accumulate BTC" in context

    def test_build_data_quality_with_ta(self) -> None:
        from web.api.llm_signal_analyzer import _build_data_quality
        data = {
            "market": {"last": 95000},
            "kline": {
                "15min": {"trend": "bullish"},
                "1hour": {"trend": "bullish"},
                "4hour": {"trend": "bullish"},
                "1day": {"trend": "bullish"},
            },
            "onchain": {"summary": "ok"},
            "onchainMetrics": {"symbol": "BTC"},
            "news": [{"title": "test", "publishedAt": "2026-06-05T10:00:00Z"}],
            "newsMeta": {"totalCount": 1, "freshCount": 1, "gateHours": 12, "gateApplicable": True},
            "derivatives": {"fundingRate": {"fundingRate": 0.0001}, "openInterest": {"value": 1}},
            "microstructure": {"orderbook": {"imbalance": 0.1}, "recentTrades": {"buyRatio": 0.55}},
            "valuescan": {
                "fund": {"net": 1},
                "sentiment": {"score": 1},
                "tokenFlow": {"in": 1},
                "priceIndicators": {"price": 1},
                "whaleCost": [{"cost": 1}],
                "supportResistance": [{"level": 1}],
                "tokenDetail": {"id": 1},
            },
            "tradingAgents": {
                "available": True,
                "finalDecision": "This is a comprehensive buy signal with detailed analysis.",
            }
        }
        dq = _build_data_quality(data)
        assert "tradingAgents" in dq.sourceStatus
        assert dq.sourceStatus["tradingAgents"] == "ok"
        assert dq.coverageScore > 0.7

    def test_build_data_quality_without_ta(self) -> None:
        from web.api.llm_signal_analyzer import _build_data_quality
        data = {
            "market": {"last": 95000},
            "kline": {
                "15min": {"trend": "bullish"},
                "1hour": {"trend": "bullish"},
                "4hour": {"trend": "bullish"},
                "1day": {"trend": "bullish"},
            },
            "onchain": {"summary": "ok"},
            "onchainMetrics": {"symbol": "BTC"},
            "news": [{"title": "test", "publishedAt": "2026-06-05T10:00:00Z"}],
            "newsMeta": {"totalCount": 1, "freshCount": 1, "gateHours": 12, "gateApplicable": True},
            "derivatives": {"fundingRate": {"fundingRate": 0.0001}, "openInterest": {"value": 1}},
            "microstructure": {"orderbook": {"imbalance": 0.1}, "recentTrades": {"buyRatio": 0.55}},
            "valuescan": {
                "fund": {"net": 1},
                "sentiment": {"score": 1},
                "tokenFlow": {"in": 1},
                "priceIndicators": {"price": 1},
                "whaleCost": [{"cost": 1}],
                "supportResistance": [{"level": 1}],
                "tokenDetail": {"id": 1},
            },
        }
        dq = _build_data_quality(data)
        assert "tradingAgents" not in dq.sourceStatus
        assert dq.coverageScore > 0.5

    def test_build_data_quality_ta_partial(self) -> None:
        from web.api.llm_signal_analyzer import _build_data_quality
        data = {
            "market": {"last": 95000},
            "kline": {},
            "onchain": {},
            "news": [],
            "valuescan": {},
            "tradingAgents": {
                "available": True,
                "marketReport": "Some analysis",
                "finalDecision": "",
            }
        }
        dq = _build_data_quality(data)
        assert "tradingAgents" in dq.sourceStatus
        assert dq.sourceStatus["tradingAgents"] == "partial"


# ===================================================================
# _enrich_result with TA
# ===================================================================

class TestEnrichResultWithTA:
    def test_enrich_with_ta_data(self) -> None:
        from web.api.signal_schema import (
            SignalOutput, EngineMeta, DataQuality,
        )
        from web.api.llm_signal_analyzer import _enrich_result

        class MockRuleResult:
            signal = "NEUTRAL"
            score = 0.0
            confidence = 50.0
            reasons = []
            summary = ""
            trade_plan = None

        data = {
            "symbol": "BTC",
            "kline": {},
            "market": {},
            "tradingAgents": {
                "available": True,
                "dataSource": "kucoin",
                "latencyMs": 5000,
                "marketReport": "Bullish trend confirmed.",
                "sentimentReport": "Positive sentiment.",
                "newsReport": "No major news.",
                "fundamentalsReport": "Hash rate at ATH.",
                "bullAnalystReport": "Strong buy signal.",
                "bearAnalystReport": "Potential pullback.",
                "riskManagerReport": "Moderate risk.",
                "traderPlan": "Entry at 95000.",
                "finalDecision": "Buy with caution.",
            }
        }

        result = SignalOutput(
            signal="BUY",
            score=50.0,
            confidence=70.0,
            engineMeta=EngineMeta(model="test", analysisVersion="v2"),
        )

        enriched = _enrich_result(
            result,
            data=data,
            rule_result=MockRuleResult(),
            data_quality=DataQuality(coverageScore=0.8, sourceStatus={"market": "ok"}),
            model="test",
        )

        ta_block = enriched.tradingAgentsDebate
        assert ta_block.available
        assert ta_block.dataSource == "kucoin"
        assert ta_block.latencyMs == 5000
        assert "Bullish trend" in ta_block.marketSummary
        assert "Strong buy" in ta_block.bullArgument
        assert "pullback" in ta_block.bearArgument
        assert "Buy with caution" in ta_block.finalDecision

        assert enriched.debug.sourceRefs.get("tradingAgents")
        assert enriched.debug.sourceRefs.get("tradingAgentsSource") == "kucoin"

    def test_enrich_without_ta_data(self) -> None:
        from web.api.signal_schema import SignalOutput, EngineMeta, DataQuality
        from web.api.llm_signal_analyzer import _enrich_result

        class MockRuleResult:
            signal = "NEUTRAL"
            score = 0.0
            confidence = 50.0
            reasons = []
            summary = ""
            trade_plan = None

        data = {"symbol": "BTC", "kline": {}, "market": {}}

        result = SignalOutput(
            signal="NEUTRAL",
            engineMeta=EngineMeta(model="test", analysisVersion="v2"),
        )

        enriched = _enrich_result(
            result,
            data=data,
            rule_result=MockRuleResult(),
            data_quality=DataQuality(coverageScore=0.5),
            model="test",
        )

        assert not enriched.tradingAgentsDebate.available
        assert "tradingAgents" not in enriched.debug.sourceRefs
