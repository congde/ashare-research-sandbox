# -*- coding: utf-8 -*-
"""Safety tests for live futures: quant align, trade plan, entry/exit gates."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
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
_mock_config.live_quant_factors_require_align = True
_mock_config.live_trade_plan_strict = True
_mock_config.live_trade_plan_enforce_stop = True
_mock_config.live_trade_plan_enforce_targets = True
_mock_config.llm_providers = {}
_mock_config.llm_signal_timeout = None
_mock_config.openai_api_base = "http://localhost"
sys.modules["web.config"] = MagicMock()
sys.modules["web.config"].config = _mock_config
sys.modules["llm"] = MagicMock()
sys.modules["llm.llm"] = MagicMock()
sys.modules["llm.base"] = MagicMock()

from web.api.llm_futures_executor import _resolve_entry_side, run_llm_futures_batch
from web.api.llm_signal_analyzer import resolve_futures_auto_exit
from web.api.quant_factors_bridge import evaluate_quant_alignment
from web.api.trade_plan_executor import evaluate_trade_plan_entry, normalize_trade_plan
from web.api import trade_plan_store


class TestQuantAlignFailClosed(unittest.TestCase):
    def test_unavailable_blocks_entry(self):
        ok, msg = evaluate_quant_alignment(
            "buy",
            {"available": False, "reason": "timeout"},
            require_align=True,
            min_aggregate=0.12,
        )
        self.assertFalse(ok)
        self.assertIn("不可用", msg)

    def test_resolve_entry_side_blocks_without_quant(self):
        analysis = {
            "confidence": 80,
            "executionReadiness": "ready",
            "fiveSignalAlignment": {"aligned": True, "side": "buy", "reason": "ok"},
            "quantFactors": {"available": False, "reason": "timeout"},
        }
        side, reason = _resolve_entry_side(
            analysis,
            min_confidence=55,
            only_ready=False,
            require_five_signal_align=True,
            require_quant_align=True,
            quant_min_aggregate=0.12,
        )
        self.assertIsNone(side)
        self.assertIn("量化因子", reason)


class TestTradePlanEntry(unittest.TestCase):
    def test_market_order_when_in_zone(self):
        plan = normalize_trade_plan({
            "entryLow": 64010,
            "entryHigh": 64520,
            "stop": 67110,
            "target1": 64000,
            "target2": 61380,
        })
        allowed, _, meta = evaluate_trade_plan_entry(plan, "sell", 64258, tolerance_pct=0.15)
        self.assertTrue(allowed)
        self.assertEqual(meta.get("orderType"), "market")


class TestPlanExitPriority(unittest.TestCase):
    def test_stop_before_target(self):
        plan = normalize_trade_plan({
            "entryLow": 64010,
            "entryHigh": 64520,
            "stop": 67110,
            "target1": 64000,
        })
        position = {"side": "short", "markPrice": 67200}
        should, reason, action = resolve_futures_auto_exit(
            position,
            None,
            {},
            stop_on_reversal=False,
            stop_on_loss=False,
            max_loss_pct=0.0,
            trade_plan=plan,
            enforce_plan_stop=True,
            enforce_plan_targets=True,
        )
        self.assertTrue(should)
        self.assertEqual(action, "plan_stop")

    def test_target_exit_short(self):
        plan = normalize_trade_plan({
            "stop": 67110,
            "target1": 64000,
            "entryLow": 64010,
            "entryHigh": 64520,
        })
        position = {"side": "short", "markPrice": 63900}
        should, _, action = resolve_futures_auto_exit(
            position,
            None,
            {},
            stop_on_reversal=False,
            stop_on_loss=False,
            max_loss_pct=0.0,
            trade_plan=plan,
            enforce_plan_stop=False,
            enforce_plan_targets=True,
        )
        self.assertTrue(should)
        self.assertEqual(action, "plan_target")


class TestTradePlanStore(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        trade_plan_store._STORE_PATH = Path(self._tmpdir.name) / "plans.json"

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_save_and_resolve_locked_plan(self):
        plan = {"stop": 67110, "target1": 64000, "entryLow": 64010, "entryHigh": 64520}
        trade_plan_store.save_entry_trade_plan("claude", "BTC", plan, side="sell")
        locked = trade_plan_store.resolve_position_trade_plan(
            "claude",
            "BTC",
            fallback={"stop": 99999},
        )
        self.assertEqual(locked["stop"], 67110)

    def test_clear_after_close(self):
        plan = {"stop": 67110, "target1": 64000, "entryLow": 1, "entryHigh": 2}
        trade_plan_store.save_entry_trade_plan("claude", "ETH", plan, side="sell")
        trade_plan_store.clear_entry_trade_plan("claude", "ETH")
        self.assertEqual(trade_plan_store.get_entry_trade_plan("claude", "ETH"), None)

    def test_reconcile_removes_orphan_plan(self):
        plan = {"stop": 67110, "target1": 64000, "entryLow": 1, "entryHigh": 2}
        trade_plan_store.save_entry_trade_plan("claude", "SOL", plan, side="sell")
        removed = trade_plan_store.reconcile_stored_plans("claude", set())
        self.assertIn("SOL", removed)
        self.assertIsNone(trade_plan_store.get_entry_trade_plan("claude", "SOL"))


class TestRunLlmFuturesBatchSafety(unittest.TestCase):
    def test_strict_plan_blocks_outside_zone(self):
        fake_ltr = MagicMock()
        fake_ltr._resolve_live_futures_account_id = MagicMock(return_value="claude")
        fake_ltr._run_futures_order = AsyncMock(return_value={"ok": True})

        plan = {
            "entryLow": 64010,
            "entryHigh": 64520,
            "stop": 67110,
            "target1": 64000,
            "target2": 61380,
        }
        analysis = {
            "symbol": "BTC",
            "pair": "BTC-USDT",
            "futuresSymbol": "BTC/USDT:USDT",
            "signal": "SELL",
            "confidence": 80,
            "executionReadiness": "ready",
            "fiveSignalAlignment": {"aligned": True, "side": "sell", "reason": "ok"},
            "quantFactors": {"available": True, "side": "sell", "aggregateScore": -0.2},
            "tradePlan": plan,
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
                "tradePlanStrict": True,
                "requireQuantAlign": True,
                "precomputedAnalyses": {"BTC": analysis},
            }))

        self.assertEqual(result["skipped"], 1)
        self.assertIn("入场区间", result["results"][0]["reason"])
        fake_ltr._run_futures_order.assert_not_awaited()

    def test_plan_stop_triggers_exit_without_reversal_flag(self):
        fake_ltr = MagicMock()
        fake_ltr._resolve_live_futures_account_id = MagicMock(return_value="claude")
        fake_ltr._run_futures_order = AsyncMock(return_value={"ok": True, "status": "submitted"})

        plan = {
            "entryLow": 64010,
            "entryHigh": 64520,
            "stop": 67110,
            "target1": 64000,
        }
        analysis = {
            "symbol": "BTC",
            "pair": "BTC-USDT",
            "futuresSymbol": "BTC/USDT:USDT",
            "signal": "SELL",
            "confidence": 80,
            "tradePlan": plan,
            "fiveSignalAlignment": {"aligned": True, "side": "sell"},
        }
        open_pos = {
            "side": "short",
            "contracts": 1,
            "markPrice": 67200,
            "entryPrice": 64200,
            "leverage": 5,
        }

        with patch.dict(sys.modules, {"web.api.live_trading_routes": fake_ltr}), \
             patch("web.api.llm_futures_executor._fetch_available_usdt", new_callable=AsyncMock, return_value=1000.0), \
             patch("web.api.llm_futures_executor._fetch_open_futures_positions", new_callable=AsyncMock, return_value={"BTC": open_pos}), \
             patch("web.api.llm_futures_executor.resolve_position_trade_plan", return_value=plan), \
             patch("web.api.llm_futures_executor.clear_entry_trade_plan") as clear_plan:
            result = asyncio.run(run_llm_futures_batch({
                "symbols": ["BTC"],
                "execute": True,
                "machineAuto": True,
                "stopOnReversal": False,
                "stopOnLoss": False,
                "enforceTradePlanStop": True,
                "precomputedAnalyses": {"BTC": analysis},
            }))

        self.assertEqual(result["stopped"], 1)
        self.assertEqual(result["results"][0]["action"], "plan_stop")
        clear_plan.assert_called_once()
        fake_ltr._run_futures_order.assert_awaited()


if __name__ == "__main__":
    unittest.main(verbosity=2)
