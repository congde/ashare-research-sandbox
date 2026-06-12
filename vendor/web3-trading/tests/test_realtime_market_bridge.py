# -*- coding: utf-8 -*-
"""Unit tests for realtime market bridge."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

_mock_config = MagicMock()
_mock_config.live_realtime_enabled = True
_mock_config.live_realtime_kline_timeframes = "1min,5min"
_mock_config.live_realtime_kline_merge_timeframes = "1min,5min,15min"
sys.modules.setdefault("web.config", MagicMock())
sys.modules["web.config"].config = _mock_config
from quant.market_analysis import merge_live_price_into_candles  # noqa: E402
from web.api.realtime_market_bridge import (  # noqa: E402
    live_kline_merge_timeframes,
    resolve_live_mark_price,
    resolve_realtime_options,
    signal_kline_timeframes,
)


class TestRealtimeMarketBridge(unittest.TestCase):
    def test_resolve_realtime_options_defaults(self):
        opts = resolve_realtime_options()
        self.assertTrue(opts["enabled"])
        self.assertEqual(opts["kline_timeframes"], ("1min", "5min"))
        self.assertEqual(opts["kline_merge_timeframes"], ("1min", "5min", "15min"))

    def test_live_kline_merge_timeframes(self):
        self.assertEqual(live_kline_merge_timeframes(), ("1min", "5min", "15min"))

    def test_merge_live_price_into_candles(self):
        candles = [{"open": 100.0, "close": 101.0, "high": 102.0, "low": 99.0, "volume": 1.0}]
        self.assertTrue(merge_live_price_into_candles(candles, 103.5))
        self.assertEqual(candles[-1]["close"], 103.5)
        self.assertEqual(candles[-1]["high"], 103.5)
        self.assertEqual(candles[-1]["low"], 99.0)
        self.assertTrue(candles[-1]["liveMerged"])

    def test_signal_kline_timeframes_prepends_short_periods(self):
        tfs = signal_kline_timeframes()
        self.assertEqual(tfs[0], "1min")
        self.assertEqual(tfs[1], "5min")
        self.assertIn("15min", tfs)
        self.assertIn("1day", tfs)

    def test_resolve_live_mark_price_prefers_futures_mark(self):
        data = {
            "market": {"last": 100.0},
            "realtime": {
                "futuresMarkPrice": {"value": 101.5},
                "level1": {"price": 100.2},
            },
        }
        self.assertEqual(resolve_live_mark_price(data), 101.5)

    def test_resolve_live_mark_price_falls_back_to_market(self):
        data = {"market": {"last": 99.0}}
        self.assertEqual(resolve_live_mark_price(data), 99.0)


if __name__ == "__main__":
    unittest.main()
