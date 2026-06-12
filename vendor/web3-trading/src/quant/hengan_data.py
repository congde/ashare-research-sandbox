# -*- coding: utf-8 -*-
"""恒安/ValueScan/DexScan 数据源封装。

`/Users/gavinxie/Downloads/api.md` 中描述的数据可分为：
- CEX 资金与 AI 追踪：当前 `web.api.valuescan_service` 已覆盖大部分；
- DEXScan：链上 DEX 行情、流动性、风险标签、Top 持仓；
- Hyper Liquid：资产/合约/订单/成交/账本/爆仓；
- 社交热度：KOL、热度、AI 推文总结。
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional

from libs import http

logger = logging.getLogger(__name__)

DEXSCAN_BASE_URL = os.getenv("DEXSCAN_API_BASE_URL", "https://kcapi.dexscan.trade")
HENGAN_SOCIAL_BASE_URL = os.getenv("HENGAN_SOCIAL_BASE_URL", DEXSCAN_BASE_URL)
HENGAN_API_KEY = os.getenv("HENGAN_API_KEY", "")


def _sanitize_error(value: Any) -> str:
    text = str(value)
    replacements = (
        (r"('Authorization'\s*:\s*)'[^']*'", r"\1'***'"),
        (r"(Authorization\s*[:=]\s*)[^,}\s]+", r"\1***"),
    )
    for pattern, repl in replacements:
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
    if len(text) > 2000:
        return text[:2000].rstrip() + f"... [truncated {len(text) - 2000} chars]"
    return text


def _headers() -> dict:
    headers = {"Content-Type": "application/json"}
    dex_api_key = os.getenv("DEX_API_KEY", "")
    if dex_api_key:
        headers["API-KEY"] = dex_api_key
    if HENGAN_API_KEY:
        headers["Authorization"] = f"Bearer {HENGAN_API_KEY}"
    return headers


async def dex_post(path: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = f"{DEXSCAN_BASE_URL.rstrip('/')}{path}"
    try:
        data = await http.post(url, json=body or {}, headers=_headers(), timeout=20)
        return data if isinstance(data, dict) else {"data": data}
    except Exception as exc:
        message = _sanitize_error(exc)
        logger.warning("DexScan API %s error: %s", path, message)
        return {"code": -1, "message": message}


async def hengan_get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from urllib.parse import urlencode

    url = f"{DEXSCAN_BASE_URL.rstrip('/')}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    try:
        data = await http.get(url, headers=_headers(), timeout=20)
        return data if isinstance(data, dict) else {"data": data}
    except Exception as exc:
        message = _sanitize_error(exc)
        logger.warning("HengAn API %s error: %s", path, message)
        return {"code": -1, "message": message}


async def get_dex_kline_history(chain_name: str, token_contract_address: str, **kwargs) -> Dict[str, Any]:
    return await dex_post("/v3/dex/market/kline-history", {
        "chainName": chain_name,
        "tokenContractAddress": token_contract_address,
        **kwargs,
    })


async def get_dex_current_price(chain_name: str, token_contract_address: str) -> Dict[str, Any]:
    return await dex_post("/v3/dex/market/current-price", {
        "chainName": chain_name,
        "tokenContractAddress": token_contract_address,
    })


async def get_dex_market_stats(tokens: List[Dict[str, str]]) -> Dict[str, Any]:
    return await dex_post("/v3/dex/market/stats", {"tokens": tokens})


async def get_dex_liquidity(chain_name: str, token_contract_address: str) -> Dict[str, Any]:
    return await dex_post("/v3/dex/market/coin-liquid", {
        "chainName": chain_name,
        "tokenContractAddress": token_contract_address,
    })


async def get_dex_market_cap(chain_name: str, token_contract_address: str) -> Dict[str, Any]:
    return await dex_post("/v3/dex/market/coin-market-cap", {
        "chainName": chain_name,
        "tokenContractAddress": token_contract_address,
    })


async def get_dex_price_info(chain_name: str, token_contract_address: str) -> Dict[str, Any]:
    return await dex_post("/v3/dex/market/price-info", {
        "chainName": chain_name,
        "tokenContractAddress": token_contract_address,
    })


async def get_dex_trade_scroll(chain_name: str, token_contract_address: str, **kwargs) -> Dict[str, Any]:
    return await dex_post("/v3/dex/market/trade-scroll", {
        "chainName": chain_name,
        "tokenContractAddress": token_contract_address,
        **kwargs,
    })


async def get_dex_top_holders(chain_name: str, token_contract_address: str) -> Dict[str, Any]:
    return await dex_post("/v3/dex/market/coin-balance-top", {
        "chainName": chain_name,
        "tokenContractAddress": token_contract_address,
    })


async def get_dex_top_pools(chain_name: str, token_contract_address: str) -> Dict[str, Any]:
    return await dex_post("/v3/dex/market/liquid-pool-top", {
        "chainName": chain_name,
        "tokenContractAddress": token_contract_address,
    })


async def get_dex_risk_labels(chain_name: str, token_contract_address: str) -> Dict[str, Any]:
    return await dex_post("/v3/dex/market/coin-risk-labels", {
        "chainName": chain_name,
        "tokenContractAddress": token_contract_address,
    })


async def get_hyper_asset() -> Dict[str, Any]:
    return await hengan_get("/v3/hyper/asset")


async def get_hyper_contract() -> Dict[str, Any]:
    return await hengan_get("/v3/hyper/contract")


async def query_hyper_orders(body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return await dex_post("/v3/order/query", body or {})


async def query_hyper_trades(body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return await dex_post("/v3/trade/query", body or {})


async def get_social_heat(body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = body or {}
    tokens = payload.get("tokens") if isinstance(payload, dict) else None
    if isinstance(tokens, list) and tokens:
        request_body = [
            {
                "chainName": item.get("chainName") or item.get("chain") or item.get("chainType"),
                "tokenContractAddress": item.get("tokenContractAddress") or item.get("address") or item.get("token"),
            }
            for item in tokens
            if isinstance(item, dict) and (item.get("tokenContractAddress") or item.get("address") or item.get("token"))
        ]
        if not request_body:
            return {}
        url = f"{HENGAN_SOCIAL_BASE_URL.rstrip('/')}/v3/dex/social/heatList"
    else:
        request_body = payload
        url = f"{HENGAN_SOCIAL_BASE_URL.rstrip('/')}/heat/heatList"
    try:
        data = await http.post(url, json=request_body, headers=_headers(), timeout=20)
        return data if isinstance(data, dict) else {"data": data}
    except Exception as exc:
        message = _sanitize_error(exc)
        logger.warning("social heat error: %s", message)
        return {"code": -1, "message": message}
