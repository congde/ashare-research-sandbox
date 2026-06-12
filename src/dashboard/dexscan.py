from __future__ import annotations

import json
import os
from typing import Any

from dashboard.http_client import http_post

DEX_BASE_URL = os.environ.get("DEX_BASE_URL", "https://kcapi.dexscan.trade").rstrip("/")
DEX_API_KEY = ""

_CHAIN_NAME_MAP = {
    "solana": "SOL",
    "sol": "SOL",
    "ethereum": "ETH",
    "eth": "ETH",
    "bsc": "BSC",
}


def refresh_config() -> None:
    global DEX_API_KEY, DEX_BASE_URL
    DEX_API_KEY = os.environ.get("DEX_API_KEY") or os.environ.get("DEXSCAN_API_KEY") or ""
    DEX_BASE_URL = os.environ.get("DEX_BASE_URL", "https://kcapi.dexscan.trade").rstrip("/")


def configured() -> bool:
    refresh_config()
    return bool(DEX_API_KEY)


def _normalize_chain(chain: str) -> str:
    return _CHAIN_NAME_MAP.get((chain or "").strip().lower(), (chain or "SOL").strip())


def dex_post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    refresh_config()
    url = f"{DEX_BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}
    if DEX_API_KEY:
        headers["API-KEY"] = DEX_API_KEY
    try:
        data = http_post(url, json.dumps(body), headers=headers)
    except RuntimeError as exc:
        return {"code": -1, "message": str(exc)}
    return data if isinstance(data, dict) else {}


def get_dex_trending(*, chain: str = "solana", limit: int = 20) -> dict[str, Any]:
    chain_name = _normalize_chain(chain)
    body = {
        "chainName": chain_name,
        "bar": "24h",
        "order": [{"column": "value", "asc": False}],
        "page": 1,
        "pageSize": max(1, min(50, limit)),
    }
    resp = dex_post("/v3/dex/market/coin-rank", body)
    data = resp.get("data") or {}
    tokens = data.get("list", []) if isinstance(data, dict) else []
    return {
        "ok": True,
        "source": "live",
        "chain": chain_name,
        "tokens": tokens,
        "total": data.get("total", len(tokens)) if isinstance(data, dict) else len(tokens),
    }
