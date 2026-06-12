# -*- coding: utf-8 -*-
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from web.api.futures_symbols import spot_pair_to_native_futures_symbol


class TestFuturesSymbolResolve(unittest.TestCase):
    def test_btc_pair(self):
        self.assertEqual(spot_pair_to_native_futures_symbol("BTC-USDT"), "XBTUSDTM")

    def test_ccxt_symbol(self):
        self.assertEqual(spot_pair_to_native_futures_symbol("BTC/USDT:USDT"), "XBTUSDTM")

    def test_eth(self):
        self.assertEqual(spot_pair_to_native_futures_symbol("ETH-USDT"), "ETHUSDTM")


if __name__ == "__main__":
    unittest.main()
