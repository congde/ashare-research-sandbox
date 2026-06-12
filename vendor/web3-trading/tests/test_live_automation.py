# -*- coding: utf-8 -*-
"""Smoke tests for unified live automation (hybrid gate + arena consensus + futures)."""

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
    "dc_api_security",
    "dc_api_security.kc_eureka",
    "dc_api_security.kc_eureka.http_client",
]
for mod_name in _mock_modules:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()
sys.modules["json_repair"].loads = json.loads
_mock_config = MagicMock()
_mock_config.llm_providers = {}
_mock_config.llm_signal_timeout = None
_mock_config.openai_api_base = "http://localhost"
sys.modules["web.config"] = MagicMock()
sys.modules["web.config"].config = _mock_config
sys.modules["llm"] = MagicMock()
sys.modules["llm.llm"] = MagicMock()
sys.modules["llm.base"] = MagicMock()

from web.api.live_automation import (
    PIPELINE_HYBRID,
    _arena_approved_symbols,
    normalize_automation_config,
    run_live_automation_round,
)


class TestArenaGateMatching(unittest.TestCase):
    def test_buy_matches_long_and_buy(self):
        from arena.engine import _arena_action_matches_llm_gate

        self.assertTrue(_arena_action_matches_llm_gate("buy", "buy"))
        self.assertTrue(_arena_action_matches_llm_gate("LONG", "buy"))

    def test_sell_matches_short(self):
        from arena.engine import _arena_action_matches_llm_gate

        self.assertTrue(_arena_action_matches_llm_gate("short", "sell"))
        self.assertTrue(_arena_action_matches_llm_gate("sell", "sell"))

    def test_mismatch_blocked(self):
        from arena.engine import _arena_action_matches_llm_gate

        self.assertFalse(_arena_action_matches_llm_gate("buy", "sell"))
        self.assertFalse(_arena_action_matches_llm_gate("hold", "buy"))


class TestArenaApprovedSymbols(unittest.TestCase):
    def test_execution_agent_must_agree(self):
        gate = {"BTC": {"side": "buy", "reason": "ok"}}
        arena = {
            "signals": [
                {"agent_name": "claude_agent", "symbol": "BTC", "action": "LONG", "execution_action": "buy"},
                {"agent_name": "trend_hunter", "symbol": "BTC", "action": "SHORT", "execution_action": "short"},
            ],
        }
        approved = _arena_approved_symbols(arena, gate, ["claude_agent"])
        self.assertEqual(approved, ["BTC"])

    def test_no_execution_agents_falls_back_to_all_gated(self):
        gate = {"BTC": {"side": "buy"}, "ETH": {"side": "sell"}}
        approved = _arena_approved_symbols({"signals": []}, gate, [])
        self.assertEqual(approved, ["BTC", "ETH"])


class TestNormalizeAutomationConfig(unittest.TestCase):
    def test_hybrid_default_pipeline(self):
        cfg = normalize_automation_config({"symbols": "BTC", "live": True})
        self.assertEqual(cfg["pipeline"], PIPELINE_HYBRID)
        self.assertTrue(cfg["arena"]["live_enabled"])

    def test_single_model_propagates_to_arena(self):
        cfg = normalize_automation_config({
            "symbols": "BTC",
            "model": "qwen/Qwen3.5-27B",
        })
        self.assertEqual(cfg["model"], "qwen/Qwen3.5-27B")
        self.assertEqual(cfg["arena"]["model"], "qwen/Qwen3.5-27B")
        self.assertEqual(cfg["arena"]["deepseek_model"], "qwen/Qwen3.5-27B")
        self.assertEqual(cfg["arena"]["default_model"], "qwen/Qwen3.5-27B")


class TestHybridRound(unittest.TestCase):
    def test_hybrid_skips_futures_when_gate_empty(self):
        with patch(
            "web.api.live_automation._build_llm_gate",
            new_callable=AsyncMock,
            return_value=({}, [{"symbol": "BTC", "gateSide": None}], {}),
        ):
            result = asyncio.run(run_live_automation_round({"pipeline": "hybrid", "symbols": "BTC"}))
        self.assertTrue(result["ok"])
        self.assertIsNone(result["llmFutures"])
        self.assertIn("门禁", result.get("message", ""))

    def test_hybrid_runs_arena_observe_then_futures(self):
        gate = {"BTC": {"side": "buy", "reason": "aligned", "analysis": {}}}
        analyses = {
            "BTC": {
                "symbol": "BTC",
                "signal": "BUY",
                "confidence": 80,
                "fiveSignalAlignment": {"aligned": True, "side": "buy"},
            },
        }
        arena_compact = {
            "signals": [
                {"agent_name": "claude_agent", "symbol": "BTC", "action": "LONG", "execution_action": "buy"},
            ],
        }
        futures_result = {"ok": True, "executed": 1, "results": []}

        with patch(
            "web.api.live_automation._build_llm_gate",
            new_callable=AsyncMock,
            return_value=(gate, [], analyses),
        ), patch(
            "web.api.live_automation._run_arena_round",
            new_callable=AsyncMock,
            return_value=arena_compact,
        ) as arena_run, patch(
            "web.api.live_automation.run_llm_futures_batch",
            new_callable=AsyncMock,
            return_value=futures_result,
        ) as futures_run:
            result = asyncio.run(
                run_live_automation_round({
                    "pipeline": "hybrid",
                    "symbols": "BTC",
                    "live": True,
                    "executionAgents": ["claude_agent"],
                })
            )

        self.assertEqual(result["pipeline"], PIPELINE_HYBRID)
        self.assertEqual(result["arenaApprovedSymbols"], ["BTC"])
        arena_run.assert_awaited_once()
        arena_cfg = arena_run.await_args.args[0]
        self.assertTrue(arena_cfg["paper_only"])
        self.assertFalse(arena_cfg["execute"])
        futures_body = futures_run.await_args.args[0]
        self.assertTrue(futures_body["execute"])
        self.assertEqual(futures_body["arenaApprovedSymbols"], ["BTC"])
        self.assertIn("BTC", futures_body["precomputedAnalyses"])


class TestArenaApprovedFuturesFilter(unittest.TestCase):
    def test_batch_skips_when_not_in_arena_approved(self):
        from web.api.llm_futures_executor import run_llm_futures_batch

        fake_ltr = MagicMock()
        fake_ltr._resolve_live_futures_account_id = MagicMock(return_value="claude")
        fake_ltr._run_futures_order = AsyncMock(return_value={"ok": True})

        analysis = {
            "symbol": "BTC",
            "futuresSymbol": "BTC/USDT:USDT",
            "signal": "BUY",
            "confidence": 80,
            "executionReadiness": "ready",
            "fiveSignalAlignment": {"aligned": True, "side": "buy", "reason": "ok"},
            "quantFactors": {"available": True, "side": "buy", "aggregateScore": 0.2},
            "tradePlan": {
                "entryLow": 60000,
                "entryHigh": 70000,
                "stop": 58000,
                "target1": 72000,
            },
            "summary": "x",
        }

        with patch.dict(sys.modules, {"web.api.live_trading_routes": fake_ltr}), \
             patch("web.api.llm_futures_executor._fetch_available_usdt", new_callable=AsyncMock, return_value=1000.0), \
             patch("web.api.llm_futures_executor._fetch_open_futures_positions", new_callable=AsyncMock, return_value={}), \
             patch("web.api.llm_futures_executor._resolve_entry_contracts", new_callable=AsyncMock, return_value=(1, {})), \
             patch("web.api.dashboard_service.fetch_futures_mark_price", new_callable=AsyncMock, return_value={"markPrice": 65000}):
            result = asyncio.run(run_llm_futures_batch({
                "symbols": ["BTC"],
                "execute": True,
                "machineAuto": True,
                "requireQuantAlign": True,
                "tradePlanStrict": True,
                "precomputedAnalyses": {"BTC": analysis},
                "arenaApprovedSymbols": [],
            }))
        self.assertTrue(result["ok"])
        self.assertEqual(result["skipped"], 1)
        self.assertIn("Arena", result["results"][0]["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
