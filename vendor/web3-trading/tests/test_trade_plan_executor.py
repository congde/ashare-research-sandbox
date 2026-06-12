# -*- coding: utf-8 -*-
"""Unit tests for trade_plan_executor."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from web.api.trade_plan_executor import (
    evaluate_trade_plan_entry,
    evaluate_trade_plan_exit,
    is_trade_plan_stop_hit,
    normalize_trade_plan,
    validate_trade_plan_shape,
)


class TestTradePlanShape(unittest.TestCase):
    def test_short_plan_valid(self):
        plan = normalize_trade_plan({
            "entryLow": 64010,
            "entryHigh": 64520,
            "stop": 67110,
            "target1": 64000,
            "target2": 61380,
        })
        ok, _ = validate_trade_plan_shape(plan, "sell")
        self.assertTrue(ok)

    def test_short_stop_too_low(self):
        plan = normalize_trade_plan({
            "entryLow": 64010,
            "entryHigh": 64520,
            "stop": 64000,
        })
        ok, msg = validate_trade_plan_shape(plan, "sell")
        self.assertFalse(ok)
        self.assertIn("止损", msg)


class TestTradePlanEntry(unittest.TestCase):
    def test_price_inside_band(self):
        plan = normalize_trade_plan({
            "entryLow": 64010,
            "entryHigh": 64520,
            "stop": 67110,
            "target1": 64000,
            "target2": 61380,
        })
        allowed, reason, meta = evaluate_trade_plan_entry(plan, "sell", 64258, tolerance_pct=0.15)
        self.assertTrue(allowed)
        self.assertIn("入场区间", reason)
        self.assertEqual(meta.get("orderType"), "market")

    def test_price_above_band_rejected(self):
        plan = normalize_trade_plan({
            "entryLow": 64010,
            "entryHigh": 64520,
            "stop": 67110,
            "target1": 64000,
        })
        allowed, reason, _ = evaluate_trade_plan_entry(plan, "sell", 65000, tolerance_pct=0.0)
        self.assertFalse(allowed)
        self.assertIn("高于入场区间", reason)


class TestTradePlanExit(unittest.TestCase):
    def test_short_stop_hit(self):
        plan = normalize_trade_plan({"stop": 67110, "target1": 64000})
        position = {"side": "short", "markPrice": 67200}
        hit, reason = is_trade_plan_stop_hit(position, plan)
        self.assertTrue(hit)

    def test_exit_pipeline(self):
        plan = normalize_trade_plan({"stop": 67110, "target1": 64000})
        position = {"side": "short", "markPrice": 63900}
        should, reason, action = evaluate_trade_plan_exit(
            position,
            plan,
            enforce_stop=True,
            enforce_targets=True,
        )
        self.assertTrue(should)
        self.assertEqual(action, "plan_target")


if __name__ == "__main__":
    unittest.main()
