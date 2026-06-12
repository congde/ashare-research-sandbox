# -*- coding: utf-8 -*-
"""Contract trading safety tests for dashboard live trading endpoints/helpers."""

from __future__ import annotations

import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure src is importable when running tests directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from web.api import live_trading_routes as ltr


class _FakeClient:
    def __init__(self, *, price: float, contract_size: float, free_usdt: float, market_id: str = "XBTUSDTM"):
        self._price = price
        self._contract_size = contract_size
        self._free_usdt = free_usdt
        self._market_id = market_id

    async def fetch_ticker(self, _symbol: str):
        return {"last": self._price}

    def market(self, _symbol: str):
        return {"contractSize": self._contract_size, "id": self._market_id}

    async def fetch_balance(self):
        return {"free": {"USDT": self._free_usdt}}

    async def set_leverage(self, _leverage: int, _symbol: str):
        return None

    async def set_margin_mode(self, _mode: str, _symbol: str):
        return None

    async def create_order(self, *, symbol: str, type: str, side: str, amount: int, price, params):
        return {
            "id": f"order-{side}-{amount}",
            "status": "closed",
            "side": side,
            "amount": amount,
            "filled": amount,
            "average": self._price,
            "price": self._price,
            "info": {"orderId": f"oid-{side}-{amount}", "symbol": symbol, "params": params, "type": type},
        }

    async def fetch_order(self, order_id: str, symbol: str):
        return {
            "id": order_id,
            "status": "closed",
            "side": "buy",
            "amount": 1,
            "filled": 1,
            "average": self._price,
            "price": self._price,
            "info": {"orderId": order_id, "symbol": symbol},
        }


class _FakeExchange:
    def __init__(self, *, price: float, contract_size: float, free_usdt: float, market_id: str = "XBTUSDTM"):
        self.client = _FakeClient(
            price=price,
            contract_size=contract_size,
            free_usdt=free_usdt,
            market_id=market_id,
        )

    async def _ensure_markets_loaded(self):
        return None

    async def close(self):
        return None


class _FakeNativeClient:
    def __init__(self, _market: str, **_kwargs):
        self._open_ok = True
        self._close_ok = True

    async def futures_account_overview(self, _currency: str):
        return {"code": "200000", "data": {"availableBalance": "50"}}

    async def futures_order(
        self,
        _symbol: str,
        side: str,
        *,
        size: int,
        leverage: int,
        margin_mode: str,
        position_side: str,
        reduce_only: bool,
        remark: str,
    ):
        ok = self._close_ok if reduce_only else self._open_ok
        if not ok:
            return {"code": "500001", "msg": "native order rejected"}
        suffix = "close" if reduce_only else "open"
        return {
            "code": "200000",
            "data": {"orderId": f"native-{suffix}-{side}-{size}"},
            "meta": {
                "leverage": leverage,
                "margin_mode": margin_mode,
                "position_side": position_side,
                "reduce_only": reduce_only,
                "remark": remark,
            },
        }

    async def futures_order_test(
        self,
        _symbol: str,
        side: str,
        *,
        size: int,
        leverage: int,
        margin_mode: str,
        position_side: str,
    ):
        return {
            "code": "200000",
            "data": {"orderId": f"native-test-{side}-{size}"},
            "meta": {
                "leverage": leverage,
                "margin_mode": margin_mode,
                "position_side": position_side,
            },
        }

    async def futures_order_detail(self, order_id: str):
        return {
            "code": "200000",
            "data": {
                "id": order_id,
                "status": "done",
                "filledSize": "1",
                "dealPrice": "100",
            },
        }


class TestLiveFuturesTrading(unittest.TestCase):
    def _install_quant_modules(self, *, exchange: _FakeExchange, native_cls=_FakeNativeClient):
        exchange_mod = types.ModuleType("quant.exchange")
        kucoin_mod = types.ModuleType("quant.kucoin_native")

        class _FactoryExchange:
            def __new__(cls, *args, **kwargs):
                return exchange

        exchange_mod.CCXTExchange = _FactoryExchange
        kucoin_mod.KuCoinNativeClient = native_cls
        return patch.dict(sys.modules, {
            "quant.exchange": exchange_mod,
            "quant.kucoin_native": kucoin_mod,
        })

    def test_guess_native_symbol(self):
        self.assertEqual(ltr._guess_native_futures_symbol("BTC/USDT:USDT"), "XBTUSDTM")
        self.assertEqual(ltr._guess_native_futures_symbol("ETH-USDT"), "ETHUSDTM")

    def test_resolve_native_symbol_prefers_market_id(self):
        exchange = _FakeExchange(price=100, contract_size=1, free_usdt=100, market_id="BTCUSDTM")
        resolved = asyncio.run(ltr._resolve_native_futures_symbol(exchange, "BTC/USDT:USDT"))
        self.assertEqual(resolved, "BTCUSDTM")

    def test_futures_order_invalid_side(self):
        result = asyncio.run(ltr._run_futures_order({"side": "hold"}))
        self.assertFalse(result["ok"])
        self.assertIn("side", result["message"])

    def test_futures_order_preflight_notional_exceeds_max(self):
        fake_exchange = _FakeExchange(price=1000, contract_size=1, free_usdt=1000)
        with self._install_quant_modules(exchange=fake_exchange), patch.dict("os.environ", {"QUANT_KUCOIN_NATIVE_REST": "false"}, clear=False):
            result = asyncio.run(ltr._run_futures_order({
                "symbol": "BTC/USDT:USDT",
                "side": "buy",
                "contracts": 1,
                "leverage": 10,
                "maxNotionalUsd": 100,
                "maxMarginUsd": 100,
            }))
        self.assertFalse(result["ok"])
        self.assertEqual(result.get("status"), "preflight_failed")
        self.assertEqual(result.get("reason"), "notional exceeds max")

    def test_futures_order_insufficient_margin_when_opening(self):
        fake_exchange = _FakeExchange(price=100, contract_size=1, free_usdt=0.1)
        with self._install_quant_modules(exchange=fake_exchange), patch.dict("os.environ", {"QUANT_KUCOIN_NATIVE_REST": "false"}, clear=False):
            result = asyncio.run(ltr._run_futures_order({
                "symbol": "BTC/USDT:USDT",
                "side": "buy",
                "contracts": 1,
                "leverage": 5,
                "maxNotionalUsd": 500,
                "maxMarginUsd": 500,
                "reduceOnly": False,
            }))
        self.assertFalse(result["ok"])
        self.assertEqual(result.get("status"), "preflight_failed")
        self.assertEqual(result.get("reason"), "insufficient futures USDT margin")

    def test_futures_order_reduce_only_can_pass_with_low_margin(self):
        fake_exchange = _FakeExchange(price=100, contract_size=1, free_usdt=0.0)
        with self._install_quant_modules(exchange=fake_exchange), \
             patch.object(ltr, "_append_live_rows") as append_rows, \
             patch.dict("os.environ", {"QUANT_KUCOIN_NATIVE_REST": "false"}, clear=False):
            result = asyncio.run(ltr._run_futures_order({
                "symbol": "BTC/USDT:USDT",
                "side": "sell",
                "contracts": 1,
                "leverage": 10,
                "maxNotionalUsd": 500,
                "maxMarginUsd": 500,
                "reduceOnly": True,
            }))
        self.assertTrue(result["ok"])
        self.assertEqual(result.get("status"), "submitted")
        self.assertTrue(result.get("order", {}).get("reduce_only"))
        append_rows.assert_called_once()

    def test_futures_order_native_submit_failed(self):
        class _FailNative(_FakeNativeClient):
            async def futures_order(self, *args, **kwargs):
                return {"code": "400100", "msg": "reject"}

        fake_exchange = _FakeExchange(price=100, contract_size=1, free_usdt=100)
        with self._install_quant_modules(exchange=fake_exchange, native_cls=_FailNative), patch.dict("os.environ", {"QUANT_KUCOIN_NATIVE_REST": "true"}, clear=False):
            result = asyncio.run(ltr._run_futures_order({
                "symbol": "BTC/USDT:USDT",
                "side": "buy",
                "contracts": 1,
                "leverage": 3,
                "maxNotionalUsd": 500,
                "maxMarginUsd": 500,
            }))
        self.assertFalse(result["ok"])
        self.assertEqual(result.get("status"), "submit_failed")

    def test_futures_roundtrip_native_close_failed(self):
        class _CloseFailNative(_FakeNativeClient):
            async def futures_order(self, symbol, side, **kwargs):
                if kwargs.get("reduce_only"):
                    return {"code": "500002", "msg": "close failed"}
                return await super().futures_order(symbol, side, **kwargs)

        fake_exchange = _FakeExchange(price=100, contract_size=1, free_usdt=100)
        with self._install_quant_modules(exchange=fake_exchange, native_cls=_CloseFailNative), \
             patch.object(ltr, "_append_live_rows") as append_rows, \
             patch.dict("os.environ", {"QUANT_KUCOIN_NATIVE_REST": "true"}, clear=False):
            result = asyncio.run(ltr._run_futures_roundtrip({
                "symbol": "BTC/USDT:USDT",
                "side": "buy",
                "contracts": 1,
                "leverage": 2,
                "maxNotionalUsd": 500,
                "maxMarginUsd": 500,
            }))
        self.assertFalse(result["ok"])
        self.assertEqual(result.get("status"), "close_failed")
        append_rows.assert_called_once()

    def test_futures_roundtrip_ccxt_success(self):
        fake_exchange = _FakeExchange(price=100, contract_size=1, free_usdt=100)
        with self._install_quant_modules(exchange=fake_exchange), \
             patch.object(ltr, "_append_live_rows") as append_rows, \
             patch.dict("os.environ", {"QUANT_KUCOIN_NATIVE_REST": "false"}, clear=False):
            result = asyncio.run(ltr._run_futures_roundtrip({
                "symbol": "BTC/USDT:USDT",
                "side": "buy",
                "contracts": 1,
                "leverage": 2,
                "maxNotionalUsd": 500,
                "maxMarginUsd": 500,
            }))
        self.assertTrue(result["ok"])
        self.assertEqual(result.get("status"), "submitted")
        self.assertIn("open_order", result)
        self.assertIn("close_order", result)
        append_rows.assert_called_once()

    def test_futures_test_order_success(self):
        fake_exchange = _FakeExchange(price=100, contract_size=1, free_usdt=0)
        with self._install_quant_modules(exchange=fake_exchange):
            result = asyncio.run(ltr._run_futures_order_test({
                "symbol": "BTC/USDT:USDT",
                "side": "buy",
                "contracts": 1,
                "leverage": 3,
                "marginMode": "CROSS",
                "positionMode": "HEDGE",
            }))
        self.assertTrue(result["ok"])
        self.assertEqual(result.get("status"), "tested")
        self.assertIn("test_order", result)

    def test_futures_test_order_failed(self):
        class _FailTestNative(_FakeNativeClient):
            async def futures_order_test(self, *args, **kwargs):
                return {"code": "400100", "msg": "invalid permission"}

        fake_exchange = _FakeExchange(price=100, contract_size=1, free_usdt=0)
        with self._install_quant_modules(exchange=fake_exchange, native_cls=_FailTestNative):
            result = asyncio.run(ltr._run_futures_order_test({
                "symbol": "BTC/USDT:USDT",
                "side": "buy",
                "contracts": 1,
                "leverage": 3,
                "marginMode": "CROSS",
                "positionMode": "HEDGE",
            }))
        self.assertFalse(result["ok"])
        self.assertEqual(result.get("status"), "test_failed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
