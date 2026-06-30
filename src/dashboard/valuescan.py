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


_MS_PER_DAY = 86_400_000


def _now_ms() -> int:
    return int(time.time() * 1000)


def get_token_detail(vs_token_id: int) -> dict[str, Any]:
    resp = vs_post("/vs-token/detail", {"vsTokenId": vs_token_id})
    data = resp.get("data")
    return data if isinstance(data, dict) else {}


def get_coin_key(vs_token_id: int) -> str:
    detail = get_token_detail(vs_token_id)
    chains = detail.get("chainAddresses") or []
    if not chains or not isinstance(chains[0], dict):
        return ""
    return str(chains[0].get("coinKey") or "")


_AI_MSG_PATHS = {
    "chance": "/ai/getChanceCoinMessageList",
    "risk": "/ai/getRiskCoinMessageList",
    "funds": "/ai/getFundsCoinMessageList",
}


def get_ai_messages(vs_token_id: int, msg_type: str = "chance") -> list[Any]:
    path = _AI_MSG_PATHS.get(msg_type, _AI_MSG_PATHS["chance"])
    resp = vs_post(path, {"vsTokenId": vs_token_id})
    data = resp.get("data")
    return data if isinstance(data, list) else []


def get_realtime_fund(vs_token_id: int) -> dict[str, Any]:
    resp = vs_post("/trade/getCoinTrade", {"vsTokenId": vs_token_id})
    data = resp.get("data")
    return data if isinstance(data, dict) else {}


def get_fund_snapshot(vs_token_id: int, date_ms: int | None = None) -> dict[str, Any]:
    resp = vs_post(
        "/trade/getCoinTradeSnapshot",
        {"vsTokenId": vs_token_id, "date": date_ms or _now_ms()},
    )
    data = resp.get("data")
    return data if isinstance(data, dict) else {}


def get_fund_market_cap_ratio(vs_token_id: int) -> dict[str, Any]:
    resp = vs_post("/trade/getCoinTradeInflowMarketCapRatio", {"vsTokenId": vs_token_id})
    data = resp.get("data")
    return data if isinstance(data, dict) else {}


def get_social_sentiment(vs_token_id: int) -> dict[str, Any]:
    resp = vs_post("/social-sentiment/getCoinSocialSentiment", {"vsTokenId": vs_token_id})
    data = resp.get("data")
    return data if isinstance(data, dict) else {}


def get_sector_coin_trade_list(tag: str, trade_type: int = 1) -> list[Any]:
    resp = vs_post("/trade/categories/CoinTradeList", {"tag": tag, "tradeType": trade_type})
    data = resp.get("data")
    return data if isinstance(data, list) else []


def get_trade_kline(vs_token_id: int, bucket_type: str = "1h", days: int = 7) -> list[Any]:
    now = _now_ms()
    resp = vs_post(
        "/trade/kline/getTradeKLineList",
        {
            "vsTokenId": vs_token_id,
            "bucketType": bucket_type,
            "startTime": now - days * _MS_PER_DAY,
            "endTime": now,
        },
    )
    data = resp.get("data")
    return data if isinstance(data, list) else []


def get_token_flow(vs_token_id: int) -> dict[str, Any]:
    resp = vs_post("/trade/getCoinTradeFlow", {"vsTokenId": vs_token_id})
    data = resp.get("data")
    return data if isinstance(data, dict) else {}


def get_whale_cost(vs_token_id: int, days: int = 90) -> list[Any]:
    now = _now_ms()
    resp = vs_post(
        "/trade/getCoinTradeCost",
        {
            "vsTokenId": vs_token_id,
            "startTime": now - days * _MS_PER_DAY,
            "endTime": now,
        },
    )
    data = resp.get("data")
    return data if isinstance(data, list) else []


def get_large_transactions(vs_token_id: int, page: int = 1, page_size: int = 50) -> list[Any]:
    coin_key = get_coin_key(vs_token_id)
    if not coin_key:
        return []
    resp = vs_post(
        "/chain/trade/large",
        {
            "vsTokenId": vs_token_id,
            "coinKey": coin_key,
            "page": page,
            "pageSize": page_size,
        },
    )
    data = resp.get("data")
    return data if isinstance(data, list) else []


def get_holder_list(vs_token_id: int, page: int = 1, page_size: int = 50) -> list[Any]:
    coin_key = get_coin_key(vs_token_id)
    if not coin_key:
        return []
    resp = vs_post(
        "/chain/trade/token/holdPage",
        {
            "vsTokenId": vs_token_id,
            "coinKey": coin_key,
            "page": page,
            "pageSize": page_size,
        },
    )
    data = resp.get("data")
    return data if isinstance(data, list) else []


def _address_trend(vs_token_id: int, address: str, endpoint: str, days: int = 30) -> list[Any]:
    coin_key = get_coin_key(vs_token_id)
    if not coin_key:
        return []
    now = _now_ms()
    resp = vs_post(
        endpoint,
        {
            "vsTokenId": vs_token_id,
            "coinKey": coin_key,
            "address": address,
            "startTime": now - days * _MS_PER_DAY,
            "endTime": now,
        },
    )
    data = resp.get("data")
    return data if isinstance(data, list) else []


def get_support_resistance(vs_token_id: int, days: int = 30) -> list[Any]:
    now = _now_ms()
    resp = vs_post(
        "/indicator/getDenseAreaList",
        {
            "vsTokenId": vs_token_id,
            "startTime": now - days * _MS_PER_DAY,
            "endTime": now,
        },
    )
    data = resp.get("data")
    return data if isinstance(data, list) else []


def get_price_indicators(vs_token_id: int, days: int = 90) -> list[Any]:
    now = _now_ms()
    resp = vs_post(
        "/indicator/getPriceMarketList",
        {
            "vsTokenId": vs_token_id,
            "startTime": now - days * _MS_PER_DAY,
            "endTime": now,
        },
    )
    data = resp.get("data")
    return data if isinstance(data, list) else []


def get_ai_market_analyse_history(page: int = 1, page_size: int = 30) -> list[Any]:
    resp = vs_post(
        "/ai/getAiTokenAnalyseResultList",
        {"page": page, "pageSize": min(page_size, 100)},
    )
    data = resp.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return list(data.get("list") or data.get("records") or [])
    return []


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
    return {
        "ok": True,
        "source": "live",
        "symbol": symbol.strip().upper(),
        "vsTokenId": vs_id,
        "fund": get_realtime_fund(vs_id),
        "fundMarketCapRatio": get_fund_market_cap_ratio(vs_id),
        "sentiment": get_social_sentiment(vs_id),
        "supportResistance": get_support_resistance(vs_id, days=7),
    }
