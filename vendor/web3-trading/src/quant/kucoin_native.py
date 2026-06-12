# -*- coding: utf-8 -*-
"""KuCoin 原生 REST API 最小客户端。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from quant.exchange import _credential_value


class KuCoinNativeClient:
    """直接调用 KuCoin REST，不经过 CCXT。"""

    def __init__(self, market: str = "spot", account_id: str = "default") -> None:
        self.market = market.lower()
        self.account_id = account_id or "default"
        self.base_url = "https://api-futures.kucoin.com" if self.market in {"future", "futures"} else "https://api.kucoin.com"
        self.api_key = _credential_value(self.account_id, ("API_KEY", "KEY"), ("KUCOIN_API_KEY", "CCXT_API_KEY"))
        self.api_secret = _credential_value(self.account_id, ("API_SECRET", "SECRET"), ("KUCOIN_API_SECRET", "CCXT_API_SECRET"))
        self.api_passphrase = _credential_value(self.account_id, ("API_PASSPHRASE", "PASSPHRASE", "PASSWORD"), ("KUCOIN_API_PASSPHRASE", "CCXT_API_PASSWORD"))

    @property
    def api_key_tail(self) -> str:
        return self.api_key[-4:] if self.api_key else ""

    @staticmethod
    def _body_text(body: Optional[dict[str, Any]]) -> str:
        return json.dumps(body or {}, separators=(",", ":")) if body else ""

    def _require_credentials(self) -> None:
        if not self.api_key or not self.api_secret or not self.api_passphrase:
            raise RuntimeError("KUCOIN_API_KEY/KUCOIN_API_SECRET/KUCOIN_API_PASSPHRASE not configured")

    @staticmethod
    def _client_oid(prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex[:24]}"

    def _sign(self, method: str, endpoint: str, body: str) -> dict[str, str]:
        self._require_credentials()
        timestamp = str(int(time.time() * 1000))
        payload = f"{timestamp}{method.upper()}{endpoint}{body}"
        signature = base64.b64encode(
            hmac.new(self.api_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
        ).decode("utf-8")
        passphrase = base64.b64encode(
            hmac.new(self.api_secret.encode("utf-8"), self.api_passphrase.encode("utf-8"), hashlib.sha256).digest()
        ).decode("utf-8")
        return {
            "KC-API-KEY": self.api_key,
            "KC-API-SIGN": signature,
            "KC-API-TIMESTAMP": timestamp,
            "KC-API-PASSPHRASE": passphrase,
            "KC-API-KEY-VERSION": "2",
            "Content-Type": "application/json",
        }

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        body: Optional[dict[str, Any]] = None,
        auth: bool = True,
        timeout: float = 20,
    ) -> dict[str, Any]:
        query = f"?{urlencode(params)}" if params else ""
        endpoint = f"{path}{query}"
        body_text = self._body_text(body)
        headers = self._sign(method, endpoint, body_text) if auth else {"Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
            response = await client.request(
                method.upper(),
                f"{self.base_url}{endpoint}",
                content=body_text if body_text else None,
                headers=headers,
            )
            try:
                data = response.json()
            except Exception:
                data = {"raw": response.text}
            if response.status_code >= 400:
                return {"code": str(response.status_code), "message": response.reason_phrase, "data": data}
            return data if isinstance(data, dict) else {"data": data}

    async def inner_transfer(self, currency: str, amount: str, from_account: str = "main", to_account: str = "trade") -> dict[str, Any]:
        """账户间资金划转（main ↔ trade）。"""
        body = {
            "clientOid": self._client_oid("transfer"),
            "currency": currency.upper(),
            "from": from_account,
            "to": to_account,
            "amount": amount,
        }
        return await self.request("POST", "/api/v2/accounts/inner-transfer", body=body)

    async def spot_order_test(self, symbol: str, side: str, *, funds: Optional[str] = None, size: Optional[str] = None) -> dict[str, Any]:
        return await self.spot_order(symbol, side, funds=funds, size=size, test=True, remark="native-test")

    async def spot_order(
        self,
        symbol: str,
        side: str,
        *,
        order_type: str = "market",
        funds: Optional[str] = None,
        size: Optional[str] = None,
        price: Optional[str] = None,
        client_oid: Optional[str] = None,
        remark: str = "native-rest",
        high_frequency: bool = True,
        test: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "clientOid": client_oid or self._client_oid("native-spot"),
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "remark": remark,
        }
        if funds is not None:
            body["funds"] = funds
        if size is not None:
            body["size"] = size
        if price is not None:
            body["price"] = price
        path = "/api/v1/hf/orders" if high_frequency else "/api/v1/orders"
        if test:
            path = f"{path}/test"
        return await self.request("POST", path, body=body)

    async def spot_order_detail(self, order_id: str, *, symbol: Optional[str] = None, high_frequency: bool = True) -> dict[str, Any]:
        if high_frequency and symbol:
            response = await self.request("GET", f"/api/v1/hf/orders/{order_id}", params={"symbol": symbol}, auth=True)
            if str(response.get("code")) == "200000":
                return response
        return await self.request("GET", f"/api/v1/orders/{order_id}", auth=True)

    async def cancel_spot_order(self, order_id: str, *, symbol: Optional[str] = None, high_frequency: bool = True) -> dict[str, Any]:
        if high_frequency and symbol:
            response = await self.request("DELETE", f"/api/v1/hf/orders/{order_id}", params={"symbol": symbol}, auth=True)
            if str(response.get("code")) == "200000":
                return response
        return await self.request("DELETE", f"/api/v1/orders/{order_id}", auth=True)

    async def spot_accounts(self, *, account_type: Optional[str] = None, currency: Optional[str] = None) -> dict[str, Any]:
        params = {key: value for key, value in {"type": account_type, "currency": currency}.items() if value}
        return await self.request("GET", "/api/v1/accounts", params=params or None, auth=True)

    async def futures_order_test(
        self,
        symbol: str,
        side: str,
        *,
        size: int = 1,
        leverage: int = 1,
        margin_mode: str = "CROSS",
        position_side: str = "BOTH",
    ) -> dict[str, Any]:
        return await self.futures_order(
            symbol,
            side,
            size=size,
            leverage=leverage,
            margin_mode=margin_mode,
            position_side=position_side,
            test=True,
            remark="native-test",
        )

    async def futures_order(
        self,
        symbol: str,
        side: str,
        *,
        size: int = 1,
        leverage: int = 1,
        order_type: str = "market",
        price: Optional[str] = None,
        margin_mode: str = "CROSS",
        position_side: Optional[str] = None,
        reduce_only: bool = False,
        client_oid: Optional[str] = None,
        remark: str = "native-rest",
        test: bool = False,
    ) -> dict[str, Any]:
        body = {
            "clientOid": client_oid or self._client_oid("native-futures"),
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "size": int(size),
            "leverage": int(leverage),
            "marginMode": margin_mode,
            "reduceOnly": bool(reduce_only),
            "remark": remark,
        }
        if position_side:
            body["positionSide"] = position_side
        if price is not None:
            body["price"] = price
        path = "/api/v1/orders/test" if test else "/api/v1/orders"
        return await self.request("POST", path, body=body)

    async def futures_order_detail(self, order_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/api/v1/orders/{order_id}", auth=True)

    async def cancel_futures_order(self, order_id: str) -> dict[str, Any]:
        return await self.request("DELETE", f"/api/v1/orders/{order_id}", auth=True)

    async def futures_account_overview(self, currency: str = "USDT") -> dict[str, Any]:
        return await self.request("GET", "/api/v1/account-overview", params={"currency": currency}, auth=True)

    async def futures_positions(self, currency: str = "USDT") -> dict[str, Any]:
        return await self.request("GET", "/api/v1/positions", params={"currency": currency}, auth=True)

    async def futures_contract(self, symbol: str) -> dict[str, Any]:
        return await self.request("GET", f"/api/v1/contracts/{symbol}", auth=False)