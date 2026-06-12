# -*- coding: utf-8 -*-
"""Integration smoke test: L1 merge into short-TF kline signals."""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def _module_is_stub(mod) -> bool:
    if mod is None:
        return False
    if isinstance(mod, MagicMock):
        return True
    return type(mod).__name__ == "_Stub"


def _aiohttp_is_stubbed() -> bool:
    return _module_is_stub(sys.modules.get("aiohttp"))


class TestRealtimeKlineIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_signal_kline_signals_live_merge(self):
        if _aiohttp_is_stubbed():
            self.skipTest("aiohttp stubbed by another test module")
        from web.api.realtime_market_bridge import (
            fetch_signal_kline_signals,
            live_kline_merge_timeframes,
            resolve_realtime_options,
        )

        opts = resolve_realtime_options()
        if not opts["enabled"]:
            self.skipTest("live_realtime_enabled=false")

        merge_tfs = set(live_kline_merge_timeframes())
        kline = await fetch_signal_kline_signals("BTC-USDT")

        self.assertIsInstance(kline, dict)
        self.assertGreater(len(kline), 0, "expected at least one timeframe")

        merged = [tf for tf in merge_tfs if (kline.get(tf) or {}).get("liveMerged")]
        self.assertGreater(
            len(merged),
            0,
            f"expected liveMerged on one of {sorted(merge_tfs)}, got keys={sorted(kline.keys())}",
        )

        for tf in merged:
            block = kline[tf]
            self.assertIn("liveClose", block)
            self.assertGreater(float(block["liveClose"]), 0)
            recent = block.get("recentCandles") or []
            self.assertGreater(len(recent), 0)
            self.assertEqual(recent[-1]["c"], block["liveClose"])

    async def test_enrich_signal_data_roundtrip(self):
        if _aiohttp_is_stubbed():
            self.skipTest("aiohttp stubbed by another test module")
        from web.api.realtime_market_bridge import enrich_signal_data, fetch_signal_kline_signals

        pair = "BTC-USDT"
        aggregated = {
            "symbol": "BTC",
            "pair": pair,
            "kline": await fetch_signal_kline_signals(pair),
            "market": {},
        }
        await enrich_signal_data(aggregated, pair)

        rt = aggregated.get("realtime") or {}
        self.assertTrue(rt.get("available"), f"realtime snapshot missing: {rt}")
        self.assertGreater(float(rt.get("markPrice") or rt.get("spotLast") or 0), 0)


if __name__ == "__main__":
    unittest.main()
