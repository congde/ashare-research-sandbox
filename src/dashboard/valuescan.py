from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any

from dashboard.http_client import http_post

VS_API_KEY = ""
VS_SECRET_KEY = ""
VS_BASE_URL = "https://api.valuescan.io/api/open/v1"


def refresh_config() -> None:
    global VS_API_KEY, VS_SECRET_KEY, VS_BASE_URL
    VS_API_KEY = os.environ.get("VS_OPEN_API_KEY", "")
    VS_SECRET_KEY = os.environ.get("VS_OPEN_SECRET_KEY", "")
    VS_BASE_URL = os.environ.get(
        "VS_OPEN_API_BASE_URL",
        "https://api.valuescan.io/api/open/v1",
    ).rstrip("/")


def configured() -> bool:
    refresh_config()
    return bool(VS_API_KEY and VS_SECRET_KEY)


def _sign(timestamp: str, body: str) -> str:
    return hmac.new(
        VS_SECRET_KEY.encode("utf-8"),
        (timestamp + body).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def vs_post(path: str, body_dict: dict | None = None) -> dict[str, Any]:
    refresh_config()
    if not configured():
        return {"code": -1, "message": "ValueScan credentials not configured"}

    timestamp = str(int(time.time() * 1000))
    raw_body = body_dict or {}
    body_str = json.dumps(raw_body, separators=(",", ":"))
    signature = _sign(timestamp, body_str)
    url = f"{VS_BASE_URL}{path}"
    headers = {
        "Content-Type": "application/json",
        "X-API-KEY": VS_API_KEY,
        "X-TIMESTAMP": timestamp,
        "X-SIGN": signature,
    }
    try:
        data = http_post(url, body_str, headers=headers)
    except RuntimeError as exc:
        return {"code": -1, "message": str(exc)}
    return data if isinstance(data, dict) else {}


def search_token(symbol: str) -> dict | None:
    sym_upper = symbol.strip().upper()
    resp = vs_post("/vs-token/list", {"search": sym_upper})
    items = resp.get("data") or []
    if not items:
        return None
    for item in items:
        if str(item.get("symbol", "")).upper() == sym_upper:
            return item
    return items[0]


def get_vs_token_id(symbol: str) -> int | None:
    token = search_token(symbol)
    if not token:
        return None
    token_id = token.get("id")
    return int(token_id) if token_id is not None else None


def get_ai_picks() -> dict[str, Any]:
    chance = vs_post("/ai/getChanceCoinList", {}).get("data") or []
    risk = vs_post("/ai/getRiskCoinList", {}).get("data") or []
    funds = vs_post("/ai/getFundsCoinList", {}).get("data") or []
    return {
        "ok": True,
        "source": "live",
        "chance": chance,
        "risk": risk,
        "funds": funds,
    }


def get_sector_fund(trade_type: int = 1) -> dict[str, Any]:
    sectors = vs_post("/trade/categories/getTradeList", {"tradeType": trade_type}).get("data") or []
    return {"ok": True, "source": "live", "tradeType": trade_type, "sectors": sectors}


def get_token_fund(symbol: str) -> dict[str, Any]:
    vs_id = get_vs_token_id(symbol)
    if not vs_id:
        return {"ok": False, "message": f"Token {symbol} not found in ValueScan"}
    fund = vs_post("/trade/getCoinTrade", {"vsTokenId": vs_id}).get("data") or {}
    ratio = vs_post("/trade/getCoinTradeInflowMarketCapRatio", {"vsTokenId": vs_id}).get("data") or {}
    sentiment = vs_post("/social-sentiment/getCoinSocialSentiment", {"vsTokenId": vs_id}).get("data") or {}
    now_ms = int(time.time() * 1000)
    support = vs_post(
        "/indicator/getDenseAreaList",
        {"vsTokenId": vs_id, "startTime": now_ms - 7 * 86_400_000, "endTime": now_ms},
    ).get("data") or []
    return {
        "ok": True,
        "source": "live",
        "symbol": symbol.strip().upper(),
        "vsTokenId": vs_id,
        "fund": fund,
        "fundMarketCapRatio": ratio,
        "sentiment": sentiment,
        "supportResistance": support,
    }
