# -*- coding: utf-8 -*-
"""Standalone KuCoin public API test for L1 kline merge (no dc_api_security)."""

from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from quant.market_analysis import analyze_candles, merge_live_price_into_candles, normalize_candle


def _kucoin_get(path: str) -> dict:
    with urlopen(f"https://api.kucoin.com{path}", timeout=15) as resp:
        return json.loads(resp.read().decode())


class TestRealtimeKlineStandalone(unittest.TestCase):
    def test_merge_changes_analysis_close(self):
        pair = "BTC-USDT"
        tf = "1min"

        raw = (_kucoin_get(f"/api/v1/market/candles?symbol={pair}&type={tf}").get("data") or [])[:120]
        candles = sorted(
            [c for c in (normalize_candle(r) for r in raw) if c],
            key=lambda x: x["tsSec"],
        )
        self.assertGreaterEqual(len(candles), 20)

        level1 = _kucoin_get(f"/api/v1/market/orderbook/level1?symbol={pair}").get("data") or {}
        live_price = float(level1.get("price") or 0)
        self.assertGreater(live_price, 0)

        before = analyze_candles(candles)
        self.assertIsNotNone(before)
        stale_close = float(candles[-1]["close"])

        merged = [dict(c) for c in candles]
        self.assertTrue(merge_live_price_into_candles(merged, live_price))
        after = analyze_candles(merged)
        self.assertIsNotNone(after)

        self.assertEqual(float(merged[-1]["close"]), live_price)
        self.assertTrue(merged[-1].get("liveMerged"))
        if stale_close != live_price:
            self.assertNotEqual(float(before["close"]), float(after["close"]))

        # RSI/trend should be computed on merged close
        self.assertIsNotNone(after.get("rsi"))
        self.assertIn(after.get("trend"), {
            "bullish", "bearish", "weak_bullish", "weak_bearish", "neutral",
        })


if __name__ == "__main__":
    unittest.main()
