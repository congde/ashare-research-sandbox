# -*- coding: utf-8 -*-
"""Unit tests for quant_factors_bridge (no live ValueScan calls)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

_mock_config = MagicMock()
_mock_config.live_quant_factors_enabled = True
_mock_config.live_quant_factors_market = "contract"
_mock_config.live_quant_factors_timeout_s = 45
_mock_config.live_quant_factors_min_aggregate = 0.12
_mock_config.live_quant_factors_require_align = False
sys.modules.setdefault("web.config", MagicMock())
sys.modules["web.config"].config = _mock_config

from web.api.quant_factors_bridge import (
    compact_factor_bundle,
    evaluate_quant_alignment,
    format_quant_factors_for_llm,
    _side_from_aggregate,
)


class TestQuantSideMapping(unittest.TestCase):
    def test_buy_sell_neutral_bands(self):
        self.assertEqual(_side_from_aggregate(0.2, min_aggregate=0.12), "buy")
        self.assertEqual(_side_from_aggregate(-0.15, min_aggregate=0.12), "sell")
        self.assertIsNone(_side_from_aggregate(0.05, min_aggregate=0.12))


class TestCompactBundle(unittest.TestCase):
    def _make_result(self, name: str, score: float, conf: float = 0.8, weight: float = 2.0):
        trace = SimpleNamespace(
            conclusion=f"{name} conclusion",
            evidence_chain=[SimpleNamespace(interpretation="step1", data_point="dp")],
        )
        return SimpleNamespace(
            factor_name=name,
            display_name=name.upper(),
            category="fund_flow",
            factor_tier="tier_1",
            signal_direction="bullish",
            normalized_score=score,
            confidence=conf,
            weight=weight,
            trace=trace,
        )

    def test_compact_includes_aggregate_and_top(self):
        class B:
            errors = []
            symbol = "BTC"
            vs_token_id = "1"
            tier1_results = [self._make_result("a", 0.5)]
            tier2_results = [self._make_result("b", -0.2)]
            tier3_results = tier4_results = tier5_results = []
            cross_factors = []

            @property
            def all_results(self):
                return self.tier1_results + self.tier2_results

            @property
            def aggregate_score(self):
                return 0.25

            overall_completeness = 0.9

        compact = compact_factor_bundle(B(), min_aggregate=0.12)
        self.assertTrue(compact["available"])
        self.assertEqual(compact["symbol"], "BTC")
        self.assertEqual(compact["side"], "buy")
        self.assertGreaterEqual(len(compact["topFactors"]), 1)
        text = format_quant_factors_for_llm(compact)
        self.assertIn("加权综合得分", text)


class TestQuantAlignment(unittest.TestCase):
    def test_fail_closed_when_unavailable(self):
        ok, msg = evaluate_quant_alignment(
            "buy",
            {"available": False, "reason": "timeout"},
            require_align=True,
            min_aggregate=0.12,
        )
        self.assertFalse(ok)
        self.assertIn("不可用", msg)

    def test_reject_mismatch(self):
        ok, msg = evaluate_quant_alignment(
            "buy",
            {"available": True, "side": "sell", "aggregateScore": -0.2},
            require_align=True,
            min_aggregate=0.12,
        )
        self.assertFalse(ok)
        self.assertIn("不一致", msg)

    def test_accept_match(self):
        ok, msg = evaluate_quant_alignment(
            "sell",
            {"available": True, "side": "sell", "aggregateScore": -0.3},
            require_align=True,
            min_aggregate=0.12,
        )
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
