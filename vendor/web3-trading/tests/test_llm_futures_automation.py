# -*- coding: utf-8 -*-
"""Tests for LLM futures automation: five-signal alignment, confirm, sizing, runner."""

from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

_mock_modules = [
    "openai",
    "json_repair",
    "kc_apollo",
    "yaml",
    "aiohttp",
    "motor",
    "motor.motor_asyncio",
    "pymongo",
    "redis",
    "langchain_core",
    "langgraph",
]
for mod_name in _mock_modules:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()
sys.modules["json_repair"].loads = json.loads
_mock_config = MagicMock()
_mock_config.llm_providers = {}
_mock_config.llm_signal_timeout = None
sys.modules["web.config"] = MagicMock()
sys.modules["web.config"].config = _mock_config
sys.modules["llm"] = MagicMock()
sys.modules["llm.llm"] = MagicMock()
sys.modules["llm.base"] = MagicMock()

from web.api.llm_futures_executor import (
    _normalize_symbols,
    _resolve_entry_side,
    _resolve_live_confirm,
    run_llm_futures_batch,
)
from web.api.entry_gate import evaluate_entry_gate_alignment
from web.api.llm_signal_analyzer import is_futures_signal_reversal
from web.api.signal_schema import (
    AnalysisBlock,
    ConsensusBlock,
    ExecutionPlan,
    FactorBlock,
    FactorsBlock,
    SignalOutput,
    TradePlan,
)


def _bullish_market() -> dict:
    return {
        "kline": {
            "15min": {"trend": "weak_bullish"},
            "1hour": {"trend": "bullish"},
            "4hour": {"trend": "bullish"},
            "1day": {"trend": "bullish"},
        },
        "derivatives": {"fundingRate": {"fundingRate": 0.0001}},
        "strategyBacktests": {"available": False},
    }


def _signal_output(
    *,
    signal: str = "BUY",
    technical: str = "bullish",
    onchain: str = "bullish",
    news: str = "bullish",
    positioning: str = "bullish",
    consensus: str = "bullish",
    bias: str = "bullish",
    confidence: float = 80.0,
    readiness: str = "ready",
) -> SignalOutput:
    return SignalOutput(
        signal=signal,
        label=signal,
        score=40.0,
        confidence=confidence,
        reasons=["test"],
        summary="test summary",
        analysis=AnalysisBlock(
            bias=bias,
            executionReadiness=readiness,
            consensus=ConsensusBlock(direction=consensus),
            execution=ExecutionPlan(riskReward1=2.0),
        ),
        tradePlan=TradePlan(
            entryLow=99,
            entryHigh=101,
            stop=95,
            target1=110,
            target2=120,
        ),
        factors=FactorsBlock(
            technical=FactorBlock(direction=technical, score=10, confidence=0.8),
            onchain=FactorBlock(direction=onchain, score=10, confidence=0.8),
            news=FactorBlock(direction=news, score=10, confidence=0.8),
            positioning=FactorBlock(direction=positioning, score=10, confidence=0.8),
        ),
    )


class TestEntryGateAlignment(unittest.TestCase):
    def test_bullish_buy_aligned(self):
        result = _signal_output(signal="BUY")
        quant = {"available": True, "aggregateScore": 0.2, "side": "buy"}
        alignment = evaluate_entry_gate_alignment(
            result,
            market_data=_bullish_market(),
            quant_factors=quant,
        )
        self.assertTrue(alignment["aligned"])
        self.assertEqual(alignment["side"], "buy")

    def test_bearish_sell_aligned(self):
        market = {
            "kline": {
                "15min": {"trend": "weak_bearish"},
                "1hour": {"trend": "bearish"},
                "4hour": {"trend": "bearish"},
                "1day": {"trend": "bearish"},
            },
            "strategyBacktests": {"available": False},
        }
        result = _signal_output(
            signal="SELL",
            technical="bearish",
            positioning="bearish",
            bias="bearish",
        )
        result.tradePlan = TradePlan(
            entryLow=99,
            entryHigh=101,
            stop=105,
            target1=90,
            target2=85,
        )
        alignment = evaluate_entry_gate_alignment(
            result,
            market_data=market,
            quant_factors={"available": True, "aggregateScore": -0.2, "side": "sell"},
        )
        self.assertTrue(alignment["aligned"])
        self.assertEqual(alignment["side"], "sell")

    def test_weak_signal_blocks(self):
        result = _signal_output(signal="WEAK_BUY")
        alignment = evaluate_entry_gate_alignment(
            result,
            market_data=_bullish_market(),
            quant_factors={"available": True, "aggregateScore": 0.2, "side": "buy"},
        )
        self.assertFalse(alignment["aligned"])


class TestSignalReversal(unittest.TestCase):
    def test_long_reversal_on_bearish_direction(self):
        market = {
            "kline": {
                "15min": {"trend": "weak_bearish"},
                "1hour": {"trend": "bearish"},
                "4hour": {"trend": "bearish"},
                "1day": {"trend": "bearish"},
            },
            "strategyBacktests": {"available": False},
        }
        result = _signal_output(
            signal="SELL",
            technical="bearish",
            positioning="bearish",
            bias="bearish",
        )
        alignment = evaluate_entry_gate_alignment(
            result,
            market_data=market,
            quant_factors={"available": True, "aggregateScore": -0.2, "side": "sell"},
        )
        should_stop, reason = is_futures_signal_reversal("long", result, alignment)
        self.assertTrue(should_stop)
        self.assertIn("偏空", reason)

    def test_long_no_reversal_when_still_bullish(self):
        result = _signal_output(signal="BUY")
        alignment = evaluate_entry_gate_alignment(
            result,
            market_data=_bullish_market(),
            quant_factors={"available": True, "aggregateScore": 0.2, "side": "buy"},
        )
        should_stop, _ = is_futures_signal_reversal("long", result, alignment)
        self.assertFalse(should_stop)

    def test_short_reversal_on_weak_buy(self):
        result = _signal_output(signal="WEAK_BUY", onchain="neutral")
        alignment = evaluate_entry_gate_alignment(
            result,
            market_data=_bullish_market(),
            quant_factors={"available": True, "aggregateScore": 0.2, "side": "buy"},
        )
        should_stop, reason = is_futures_signal_reversal("short", result, alignment)
        self.assertTrue(should_stop)
        self.assertTrue(reason)


class TestLiveConfirm(unittest.TestCase):
    def test_machine_auto_injects_confirm(self):
        confirm, ok = _resolve_live_confirm({"machineAuto": True})
        self.assertEqual(confirm, "CONFIRM")
        self.assertTrue(ok)

    def test_manual_requires_confirm_word(self):
        confirm, ok = _resolve_live_confirm({"machineAuto": False, "confirmLive": ""})
        self.assertFalse(ok)
        confirm, ok = _resolve_live_confirm({"machineAuto": False, "confirmLive": "CONFIRM"})
        self.assertTrue(ok)


class TestEntrySideResolution(unittest.TestCase):
    def test_five_signal_required_by_default(self):
        analysis = {
            "signal": "WEAK_SELL",
            "confidence": 70,
            "executionReadiness": "watch_pullback",
            "fiveSignalAlignment": {"aligned": False, "reason": "未对齐"},
        }
        side, reason = _resolve_entry_side(
            analysis,
            min_confidence=55,
            only_ready=False,
            require_five_signal_align=True,
        )
        self.assertIsNone(side)
        self.assertIn("未对齐", reason)

    def test_aligned_analysis_returns_side(self):
        analysis = {
            "signal": "BUY",
            "confidence": 80,
            "executionReadiness": "ready",
            "fiveSignalAlignment": {"aligned": True, "side": "buy", "reason": "结构+资金+可执行对齐，允许合约入场"},
        }
        side, _ = _resolve_entry_side(
            analysis,
            min_confidence=55,
            only_ready=False,
            require_five_signal_align=True,
        )
        self.assertEqual(side, "buy")


class TestSymbolNormalization(unittest.TestCase):
    def test_csv_and_list(self):
        self.assertEqual(_normalize_symbols("btc, eth ,HYPE"), ["BTC", "ETH", "HYPE"])
        self.assertEqual(_normalize_symbols(["BTC/USDT", "ETH-USDT"]), ["BTC", "ETH"])


class TestRunLlmFuturesBatch(unittest.TestCase):
    def _patch_live_routes(self, order_result=None):
        fake_ltr = MagicMock()
        fake_ltr._resolve_live_futures_account_id = MagicMock(return_value="claude")
        fake_ltr._run_futures_order = AsyncMock(return_value=order_result or {"ok": True, "status": "submitted"})
        return patch.dict(sys.modules, {"web.api.live_trading_routes": fake_ltr})

    def test_execute_without_confirm_fails_when_not_machine(self):
        with self._patch_live_routes():
            result = asyncio.run(run_llm_futures_batch({
                "symbols": ["BTC"],
                "execute": True,
                "machineAuto": False,
                "confirmLive": "",
            }))
        self.assertFalse(result["ok"])
        self.assertIn("CONFIRM", result["message"])

    def test_analyze_only_skips_confirm(self):
        with self._patch_live_routes(), \
             patch("web.api.llm_futures_executor.analyze_symbol_for_futures", new_callable=AsyncMock) as analyze:
            analyze.return_value = {
                "symbol": "BTC",
                "signal": "NEUTRAL",
                "confidence": 50,
                "executionReadiness": "wait",
                "fiveSignalAlignment": {"aligned": False, "reason": "test"},
                "summary": "x",
            }
            result = asyncio.run(run_llm_futures_batch({
                "symbols": ["BTC"],
                "execute": False,
            }))
        self.assertTrue(result["ok"])
        self.assertEqual(result["skipped"], 1)

    def test_machine_auto_batch_with_mocks(self):
        with self._patch_live_routes(), \
             patch("web.api.llm_futures_executor.analyze_symbol_for_futures", new_callable=AsyncMock) as analyze, \
             patch("web.api.llm_futures_executor._fetch_available_usdt", new_callable=AsyncMock) as balance, \
             patch("web.api.llm_futures_executor._fetch_open_futures_positions", new_callable=AsyncMock) as positions, \
             patch("web.api.llm_futures_executor._resolve_entry_contracts", new_callable=AsyncMock) as sizing, \
             patch("web.api.dashboard_service.fetch_futures_mark_price", new_callable=AsyncMock) as mark:
            out = _signal_output(signal="BUY")
            align = evaluate_entry_gate_alignment(
                out,
                market_data=_bullish_market(),
                quant_factors={"available": True, "aggregateScore": 0.2, "side": "buy"},
            )
            analyze.return_value = {
                "symbol": "BTC",
                "futuresSymbol": "BTC/USDT:USDT",
                "pair": "BTC-USDT",
                "signal": "BUY",
                "confidence": 80,
                "executionReadiness": "ready",
                "fiveSignalAlignment": align,
                "tradePlan": out.tradePlan.model_dump() if out.tradePlan else {},
                "summary": "x",
                "_result": out,
            }
            mark.return_value = {"markPrice": 100.0}
            balance.return_value = 1000.0
            positions.return_value = {}
            sizing.return_value = (1, {"mode": "auto", "contracts": 1})
            result = asyncio.run(run_llm_futures_batch({
                "symbols": ["BTC"],
                "execute": True,
                "machineAuto": True,
                "autoPositionSize": True,
                "positionPctPerSymbol": 0.05,
            }))
        self.assertTrue(result["ok"])
        self.assertEqual(result["executed"], 1)

    def test_reversal_stop_closes_existing_position(self):
        fake_ltr = MagicMock()
        fake_ltr._resolve_live_futures_account_id = MagicMock(return_value="claude")
        order = AsyncMock(return_value={"ok": True, "status": "submitted"})
        fake_ltr._run_futures_order = order
        with patch.dict(sys.modules, {"web.api.live_trading_routes": fake_ltr}), \
             patch("web.api.llm_futures_executor.analyze_symbol_for_futures", new_callable=AsyncMock) as analyze, \
             patch("web.api.llm_futures_executor._fetch_available_usdt", new_callable=AsyncMock) as balance, \
             patch("web.api.llm_futures_executor._fetch_open_futures_positions", new_callable=AsyncMock) as positions:
            bearish = _signal_output(
                signal="SELL",
                technical="bearish",
                onchain="bearish",
                news="bearish",
                positioning="bearish",
                consensus="bearish",
                bias="bearish",
            )
            market = {
                "kline": {"4hour": {"trend": "bearish"}, "1hour": {"trend": "bearish"}},
                "strategyBacktests": {"available": False},
            }
            alignment = evaluate_entry_gate_alignment(
                bearish,
                market_data=market,
                quant_factors={"available": True, "aggregateScore": -0.2, "side": "sell"},
            )
            analyze.return_value = {
                "symbol": "BTC",
                "futuresSymbol": "BTC/USDT:USDT",
                "signal": "SELL",
                "confidence": 80,
                "executionReadiness": "ready",
                "fiveSignalAlignment": alignment,
                "summary": "x",
                "_result": bearish,
            }
            balance.return_value = 1000.0
            positions.return_value = {"BTC": {"side": "long", "contracts": 2}}
            result = asyncio.run(run_llm_futures_batch({
                "symbols": ["BTC"],
                "execute": True,
                "machineAuto": True,
                "stopOnReversal": True,
            }))
        self.assertTrue(result["ok"])
        self.assertEqual(result["stopped"], 1)
        self.assertEqual(order.await_args.args[0]["reduceOnly"], True)
        self.assertEqual(order.await_args.args[0]["side"], "sell")


class TestLlmFuturesRunnerConfig(unittest.TestCase):
    def test_runner_normalizes_machine_auto_confirm(self):
        from web.api.llm_futures_runner import _normalize_config

        cfg = _normalize_config({"machineAuto": True, "symbols": "BTC,ETH"})
        self.assertTrue(cfg["machineAuto"])
        self.assertEqual(cfg["confirmLive"], "CONFIRM")
        self.assertEqual(cfg["autoPositionSize"], True)
        self.assertGreaterEqual(cfg["leverage"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
