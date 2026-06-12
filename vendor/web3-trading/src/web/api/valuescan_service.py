# -*- coding: utf-8 -*-
"""
ValueScan Open API service layer.

Handles HMAC-SHA256 signing, TTL caching, and async wrappers for all VS endpoints.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import httpx

from libs import http

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (prefer env vars; credentials must come from .env/Apollo)
# ---------------------------------------------------------------------------
VS_API_KEY = os.environ.get("VS_OPEN_API_KEY", "")
VS_SECRET_KEY = os.environ.get("VS_OPEN_SECRET_KEY", "")
VS_BASE_URL = os.environ.get("VS_OPEN_API_BASE_URL", "https://api.valuescan.io/api/open/v1")
VS_STREAM_BASE = os.environ.get("VS_STREAM_BASE_URL", "https://stream.valuescan.ai").rstrip("/")
VS_FETCH_SSE = os.environ.get("VS_FETCH_SSE", "1").strip().lower() in ("1", "true", "yes")

_MS_PER_DAY = 86_400_000
_H24_TIME_PARTICLE = 124


def _sanitize_error(value: Any) -> str:
    text = str(value)
    replacements = (
        (r"('X-API-KEY'\s*:\s*)'[^']*'", r"\1'***'"),
        (r"('X-SIGN'\s*:\s*)'[^']*'", r"\1'***'"),
        (r"('Authorization'\s*:\s*)'[^']*'", r"\1'***'"),
        (r"(X-API-KEY\s*[:=]\s*)[^,}\s]+", r"\1***"),
        (r"(X-SIGN\s*[:=]\s*)[^,}\s]+", r"\1***"),
    )
    for pattern, repl in replacements:
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
    if len(text) > 2000:
        return text[:2000].rstrip() + f"... [truncated {len(text) - 2000} chars]"
    return text


def _now_ms() -> int:
    return int(time.time() * 1000)


# ---------------------------------------------------------------------------
# TTL cache (in-memory, per-process)
# ---------------------------------------------------------------------------
class _TTLCache:
    """Simple in-memory cache with per-key TTL (seconds)."""

    def __init__(self, default_ttl: int = 300):
        self._store: Dict[str, Tuple[float, Any]] = {}
        self._default_ttl = default_ttl

    def get(self, key: str) -> Any:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.time() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        self._store[key] = (time.time() + (ttl or self._default_ttl), value)

    def clear(self) -> None:
        self._store.clear()


_cache = _TTLCache(default_ttl=300)


# ---------------------------------------------------------------------------
# HMAC-SHA256 signing & base request
# ---------------------------------------------------------------------------
def _sign(timestamp: str, body: str) -> str:
    return hmac.new(
        VS_SECRET_KEY.encode("utf-8"),
        (timestamp + body).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


async def vs_post(path: str, body_dict: Optional[Dict] = None) -> Dict[str, Any]:
    if not VS_API_KEY or not VS_SECRET_KEY:
        logger.warning("VS API %s skipped: missing VS_OPEN_API_KEY/VS_OPEN_SECRET_KEY", path)
        return {"code": -1, "message": "ValueScan credentials not configured"}

    timestamp = str(_now_ms())
    raw_body = body_dict or {}
    body_str = json.dumps(raw_body, separators=(",", ":"))
    signature = _sign(timestamp, body_str)
    url = f"{VS_BASE_URL.rstrip('/')}{path}"
    headers = {
        "Content-Type": "application/json",
        "X-API-KEY": VS_API_KEY,
        "X-TIMESTAMP": timestamp,
        "X-SIGN": signature,
    }
    try:
        data = await http.post(url, content=body_str, headers=headers, timeout=20)
    except Exception as exc:
        message = _sanitize_error(exc)
        logger.warning("VS API %s request error: %s", path, message)
        return {"code": -1, "message": message}
    if isinstance(data, dict) and data.get("code") != 200:
        logger.warning("VS API %s error: %s", path, data.get("message"))
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# Token resolution (cached)
# ---------------------------------------------------------------------------
async def search_token(symbol: str) -> Optional[Dict]:
    key = f"token:{symbol.strip().upper()}"
    cached = _cache.get(key)
    if cached is not None:
        return cached
    sym_upper = symbol.strip().upper()
    for attempt in range(3):
        resp = await vs_post("/vs-token/list", {"search": sym_upper})
        if resp.get("code") == 60001 and attempt < 2:
            await asyncio.sleep(1.5 * (2**attempt))
            continue
        items = resp.get("data") or []
        if not items:
            return None
        result = next(
            (i for i in items if str(i.get("symbol", "")).upper() == sym_upper),
            items[0],
        )
        _cache.set(key, result, ttl=600)
        return result
    return None


async def get_vs_token_id(symbol: str) -> Optional[int]:
    token = await search_token(symbol)
    return int(token["id"]) if token else None


async def get_token_detail(vs_token_id: int) -> Dict:
    key = f"detail:{vs_token_id}"
    cached = _cache.get(key)
    if cached is not None:
        return cached
    resp = await vs_post("/vs-token/detail", {"vsTokenId": vs_token_id})
    data = resp.get("data")
    if isinstance(data, dict):
        _cache.set(key, data, ttl=600)
        return data
    return {}


async def get_coin_key(vs_token_id: int) -> str:
    key = f"coinkey:{vs_token_id}"
    cached = _cache.get(key)
    if cached is not None:
        return cached
    detail = await get_token_detail(vs_token_id)
    chains = detail.get("chainAddresses") or []
    if not chains:
        return ""
    coin_key = chains[0].get("coinKey", "")
    if coin_key:
        _cache.set(key, coin_key, ttl=3600)
    return coin_key


async def resolve_symbol(symbol: str) -> Tuple[Optional[int], str]:
    """Resolve symbol → (vsTokenId, coinKey). Returns (None, '') if not found."""
    vs_id = await get_vs_token_id(symbol)
    if not vs_id:
        return None, ""
    coin_key = await get_coin_key(vs_id)
    return vs_id, coin_key


# ---------------------------------------------------------------------------
# AI Smart Picks & Signals
# ---------------------------------------------------------------------------
async def get_chance_coin_list() -> List[Dict]:
    resp = await vs_post("/ai/getChanceCoinList", {})
    return resp.get("data") or []


async def get_risk_coin_list() -> List[Dict]:
    resp = await vs_post("/ai/getRiskCoinList", {})
    return resp.get("data") or []


async def get_funds_coin_list() -> List[Dict]:
    resp = await vs_post("/ai/getFundsCoinList", {})
    return resp.get("data") or []


_AI_MSG_FNS = {
    "chance": "/ai/getChanceCoinMessageList",
    "risk": "/ai/getRiskCoinMessageList",
    "funds": "/ai/getFundsCoinMessageList",
}


async def get_ai_messages(vs_token_id: int, msg_type: str = "chance") -> List[Dict]:
    path = _AI_MSG_FNS.get(msg_type, _AI_MSG_FNS["chance"])
    resp = await vs_post(path, {"vsTokenId": vs_token_id})
    return resp.get("data") or []


# ---------------------------------------------------------------------------
# Exchange Fund Monitoring
# ---------------------------------------------------------------------------
async def get_realtime_fund(vs_token_id: int) -> Dict:
    resp = await vs_post("/trade/getCoinTrade", {"vsTokenId": vs_token_id})
    return resp.get("data") or {}


async def get_fund_snapshot(vs_token_id: int, date_ms: Optional[int] = None) -> Dict:
    resp = await vs_post("/trade/getCoinTradeSnapshot", {
        "vsTokenId": vs_token_id, "date": date_ms or _now_ms(),
    })
    return resp.get("data") or {}


async def get_fund_market_cap_ratio(vs_token_id: int) -> Dict:
    resp = await vs_post("/trade/getCoinTradeInflowMarketCapRatio", {"vsTokenId": vs_token_id})
    return resp.get("data") or {}


async def get_sector_fund_list(trade_type: int = 1) -> List[Dict]:
    resp = await vs_post("/trade/categories/getTradeList", {"tradeType": trade_type})
    return resp.get("data") or []


async def get_sector_coin_trade_list(tag: str, trade_type: int = 1) -> List[Dict]:
    resp = await vs_post("/trade/categories/CoinTradeList", {"tag": tag, "tradeType": trade_type})
    return resp.get("data") or []


async def get_kline(vs_token_id: int, bucket_type: str = "1h", days: int = 7) -> List[Dict]:
    now = _now_ms()
    resp = await vs_post("/trade/kline/getTradeKLineList", {
        "vsTokenId": vs_token_id, "bucketType": bucket_type,
        "startTime": now - days * _MS_PER_DAY, "endTime": now,
    })
    return resp.get("data") or []


# ---------------------------------------------------------------------------
# ValueScan doc §3 链上数据 — snapshot helpers for five-signal "onchain" dim
# ---------------------------------------------------------------------------
VS_CHAIN_FIELD_KEYS = (
    "tokenFlow",
    "whaleCost",
    "largeTransactions",
    "holderList",
    "topHolderAddressTrends",
)


def valuescan_chain_snapshot(vs: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Subset of fetch_full_token_data used for 筹码/资金（ValueScan）维度."""
    if not isinstance(vs, dict):
        return {}
    out: Dict[str, Any] = {}
    if vs.get("vsTokenId"):
        out["vsTokenId"] = vs["vsTokenId"]
    for key in VS_CHAIN_FIELD_KEYS:
        val = vs.get(key)
        if val is None or val == [] or val == {}:
            continue
        if key == "whaleCost" and isinstance(val, list):
            out[key] = val[-30:]
        elif key in ("largeTransactions", "holderList") and isinstance(val, list):
            out[key] = val[:15]
        else:
            out[key] = val
    return out


def valuescan_chain_coverage_status(vs: Optional[Dict[str, Any]]) -> str:
    """ok | partial | missing for dataQuality.sourceStatus.onchain."""
    if not isinstance(vs, dict) or not vs.get("vsTokenId"):
        return "missing"
    core = sum(1 for k in ("tokenFlow", "whaleCost", "largeTransactions", "holderList") if vs.get(k))
    if core >= 2:
        return "ok"
    if core >= 1:
        return "partial"
    return "missing"


# ---------------------------------------------------------------------------
# On-chain Data (exchange fund flow + whale cost)
# ---------------------------------------------------------------------------
async def get_token_flow(vs_token_id: int) -> Dict:
    resp = await vs_post("/trade/getCoinTradeFlow", {"vsTokenId": vs_token_id})
    return resp.get("data") or {}


async def get_whale_cost(vs_token_id: int, days: int = 30) -> List[Dict]:
    now = _now_ms()
    resp = await vs_post("/trade/getCoinTradeCost", {
        "vsTokenId": vs_token_id,
        "startTime": now - days * _MS_PER_DAY, "endTime": now,
    })
    return resp.get("data") or []


# ---------------------------------------------------------------------------
# On-chain Whale (require coinKey)
# ---------------------------------------------------------------------------
async def get_large_transactions(vs_token_id: int, page: int = 1, page_size: int = 20) -> List[Dict]:
    coin_key = await get_coin_key(vs_token_id)
    if not coin_key:
        return []
    resp = await vs_post("/chain/trade/large", {
        "vsTokenId": vs_token_id, "coinKey": coin_key,
        "page": page, "pageSize": page_size,
    })
    data = resp.get("data")
    return data if isinstance(data, list) else []


async def get_holder_list(vs_token_id: int, page: int = 1, page_size: int = 20) -> List[Dict]:
    coin_key = await get_coin_key(vs_token_id)
    if not coin_key:
        return []
    resp = await vs_post("/chain/trade/token/holdPage", {
        "vsTokenId": vs_token_id, "coinKey": coin_key,
        "page": page, "pageSize": page_size,
    })
    data = resp.get("data")
    return data if isinstance(data, list) else []


async def _address_trend(vs_token_id: int, address: str, endpoint: str, days: int = 30) -> List[Dict]:
    coin_key = await get_coin_key(vs_token_id)
    if not coin_key:
        return []
    now = _now_ms()
    resp = await vs_post(endpoint, {
        "vsTokenId": vs_token_id, "coinKey": coin_key, "address": address,
        "startTime": now - days * _MS_PER_DAY, "endTime": now,
    })
    data = resp.get("data")
    return data if isinstance(data, list) else []


async def get_address_balance_trend(vs_token_id: int, address: str) -> List[Dict]:
    return await _address_trend(vs_token_id, address, "/chain/trade/token/balanceTrend")


async def get_address_profit_loss_trend(vs_token_id: int, address: str) -> List[Dict]:
    return await _address_trend(vs_token_id, address, "/chain/trade/token/profitLossTrend")


async def get_address_hold_trend(vs_token_id: int, address: str) -> List[Dict]:
    return await _address_trend(vs_token_id, address, "/chain/trade/token/holdTrend")


async def get_address_trade_count_trend(vs_token_id: int, address: str) -> List[Dict]:
    return await _address_trend(vs_token_id, address, "/chain/trade/token/tradeCountTrend")


# ---------------------------------------------------------------------------
# Market Indicators
# ---------------------------------------------------------------------------
async def get_support_resistance(vs_token_id: int, days: int = 7) -> List[Dict]:
    now = _now_ms()
    resp = await vs_post("/indicator/getDenseAreaList", {
        "vsTokenId": vs_token_id,
        "startTime": now - days * _MS_PER_DAY, "endTime": now,
    })
    return resp.get("data") or []


async def get_social_sentiment(vs_token_id: int) -> Dict:
    resp = await vs_post("/social-sentiment/getCoinSocialSentiment", {"vsTokenId": vs_token_id})
    return resp.get("data") or {}


async def get_price_indicators(vs_token_id: int, days: int = 30) -> List[Dict]:
    now = _now_ms()
    resp = await vs_post("/indicator/getPriceMarketList", {
        "vsTokenId": vs_token_id,
        "startTime": now - days * _MS_PER_DAY, "endTime": now,
    })
    return resp.get("data") or []


async def get_ai_market_analyse_history(
    page: int = 1,
    page_size: int = 20,
    begin_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> List[Dict]:
    """大盘 AI 解析历史 — POST /ai/getAiTokenAnalyseResultList"""
    body: Dict[str, Any] = {"page": page, "pageSize": min(page_size, 100)}
    if begin_time:
        body["beginTime"] = str(begin_time)
    if end_time:
        body["endTime"] = str(end_time)
    resp = await vs_post("/ai/getAiTokenAnalyseResultList", body)
    data = resp.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("list") or data.get("records") or []
    return []


def _stream_sign(timestamp_ms: int, nonce: str) -> str:
    return hmac.new(
        VS_SECRET_KEY.encode("utf-8"),
        (str(timestamp_ms) + nonce).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _stream_query(extra: Optional[Dict[str, Any]] = None) -> str:
    ts = _now_ms()
    nonce = uuid.uuid4().hex
    params = {
        "apiKey": VS_API_KEY,
        "sign": _stream_sign(ts, nonce),
        "timestamp": ts,
        "nonce": nonce,
    }
    if extra:
        params.update(extra)
    return urlencode(params)


async def _read_sse_event(
    path: str,
    *,
    extra_params: Optional[Dict[str, Any]] = None,
    want_events: Tuple[str, ...] = ("market", "signal"),
    timeout_sec: float = 8.0,
    max_events: int = 5,
) -> List[Dict[str, Any]]:
    """短连接读取 SSE，收集指定 event 的 payload（超时无事件则返回空）。"""
    if not VS_API_KEY or not VS_SECRET_KEY or not VS_FETCH_SSE:
        return []
    url = f"{VS_STREAM_BASE}{path}?{_stream_query(extra_params)}"
    collected: List[Dict[str, Any]] = []
    event_name = ""
    data_lines: List[str] = []
    deadline = time.time() + timeout_sec

    def _flush() -> None:
        nonlocal event_name, data_lines
        if event_name in want_events and data_lines:
            raw = "\n".join(data_lines)
            try:
                collected.append(json.loads(raw))
            except json.JSONDecodeError:
                collected.append({"raw": raw, "event": event_name})
        event_name = ""
        data_lines = []

    try:
        async with httpx.AsyncClient(verify=False, timeout=httpx.Timeout(timeout_sec + 5.0)) as client:
            async with client.stream("GET", url, headers={"Accept": "text/event-stream"}) as resp:
                if resp.status_code != 200:
                    logger.warning("VS SSE %s status %s", path, resp.status_code)
                    return []
                async for line in resp.aiter_lines():
                    if time.time() > deadline:
                        break
                    if not line:
                        _flush()
                        continue
                    if line.startswith(":"):
                        continue
                    if line.startswith("event:"):
                        _flush()
                        event_name = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].strip())
                    if len(collected) >= max_events:
                        break
                _flush()
    except Exception as exc:
        logger.debug("VS SSE %s: %s", path, _sanitize_error(exc))
    return collected


async def fetch_sse_market_latest(timeout_sec: float = 8.0) -> List[Dict]:
    return await _read_sse_event(
        "/stream/market/subscribe",
        want_events=("market",),
        timeout_sec=timeout_sec,
        max_events=3,
    )


async def fetch_sse_signal_latest(vs_token_id: int, timeout_sec: float = 8.0) -> List[Dict]:
    return await _read_sse_event(
        "/stream/signal/subscribe",
        extra_params={"tokens": str(vs_token_id)},
        want_events=("signal",),
        timeout_sec=timeout_sec,
        max_events=5,
    )


def _sector_h24_inflow(sector: Dict) -> float:
    total = 0.0
    for rec in sector.get("categories_trade_data_list") or []:
        tpe = rec.get("timeParticleEnum") or rec.get("time_particle_enum") or 0
        if int(tpe) == _H24_TIME_PARTICLE:
            total += float(rec.get("tradeInflow") or rec.get("trade_inflow") or 0)
    if total == 0.0:
        for rec in sector.get("categories_trade_data_list") or []:
            total += float(rec.get("tradeInflow") or rec.get("trade_inflow") or 0)
    return total


def _top_sector_tags(sectors: List[Dict], limit: int = 3) -> List[str]:
    scored: List[Tuple[float, str]] = []
    for s in sectors:
        tag = (s.get("tag") or "").strip()
        if tag:
            scored.append((_sector_h24_inflow(s), tag))
    scored.sort(key=lambda x: x[0], reverse=True)
    seen: set[str] = set()
    tags: List[str] = []
    for _, tag in scored:
        if tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
        if len(tags) >= limit:
            break
    return tags


def _assign(result: Dict[str, Any], key: str, value: Any, expected: type) -> None:
    if isinstance(value, Exception):
        return
    if expected is list:
        if isinstance(value, list) and value:
            result[key] = value
    elif expected is dict:
        if isinstance(value, dict) and value:
            result[key] = value


async def fetch_full_token_data(symbol: str) -> Dict[str, Any]:
    """
    拉取单币在 ValueScan 上可用的**全部 REST + 可选 SSE** 数据。
    单路失败不阻断其它路；下游可对大字段做截断。
    """
    sym = (symbol or "BTC").strip().upper()
    result: Dict[str, Any] = {"symbol": sym, "fetchedAt": _now_ms()}

    vs_id = await get_vs_token_id(sym)
    if not vs_id:
        logger.info("VS token not found for %s", sym)
        return result
    result["vsTokenId"] = vs_id

    sem = asyncio.Semaphore(10)

    async def _g(coro):
        async with sem:
            return await coro

    # ── 核心 REST（单币）────────────────────────────────────────
    core = await asyncio.gather(
        _g(get_token_detail(vs_id)),
        _g(get_realtime_fund(vs_id)),
        _g(get_fund_market_cap_ratio(vs_id)),
        _g(get_token_flow(vs_id)),
        _g(get_social_sentiment(vs_id)),
        _g(get_support_resistance(vs_id, days=30)),
        _g(get_whale_cost(vs_id, days=90)),
        _g(get_price_indicators(vs_id, days=90)),
        _g(get_large_transactions(vs_id, 1, 50)),
        _g(get_holder_list(vs_id, 1, 50)),
        _g(get_fund_snapshot(vs_id, None)),
        _g(get_ai_messages(vs_id, "chance")),
        _g(get_ai_messages(vs_id, "risk")),
        _g(get_ai_messages(vs_id, "funds")),
        return_exceptions=True,
    )
    core_fields = (
        ("tokenDetail", dict), ("fund", dict), ("fundRatio", dict), ("tokenFlow", dict),
        ("sentiment", dict), ("supportResistance", list), ("whaleCost", list),
        ("priceIndicators", list), ("largeTransactions", list), ("holderList", list),
        ("fundSnapshot", dict),
    )
    for (key, typ), val in zip(core_fields, core[:11]):
        _assign(result, key, val, typ)
    if isinstance(core[11], list):
        result.setdefault("aiMessages", {})
        result["aiMessages"]["chance"] = core[11][:50]
    if isinstance(core[12], list):
        result.setdefault("aiMessages", {})
        result["aiMessages"]["risk"] = core[12][:50]
    if isinstance(core[13], list):
        result.setdefault("aiMessages", {})
        result["aiMessages"]["funds"] = core[13][:50]

    # ── 多周期 K 线 ─────────────────────────────────────────────
    kline_specs = (("15m", 7, "vsKline15m7d"), ("1h", 14, "vsKline1h14d"), ("4h", 30, "vsKline4h30d"), ("1d", 90, "vsKline1d90d"))
    kline_res = await asyncio.gather(
        *[_g(get_kline(vs_id, b, d)) for b, d, _ in kline_specs],
        return_exceptions=True,
    )
    for (_, _, out_key), kl in zip(kline_specs, kline_res):
        _assign(result, out_key, kl, list)

    # ── 板块 + 板块内代币 + AI 全局列表 + 大盘历史 ───────────────
    sector_spot, sector_fut, chance_all, risk_all, funds_all, mkt_hist = await asyncio.gather(
        _g(get_sector_fund_list(1)),
        _g(get_sector_fund_list(2)),
        _g(get_chance_coin_list()),
        _g(get_risk_coin_list()),
        _g(get_funds_coin_list()),
        _g(get_ai_market_analyse_history(page=1, page_size=30)),
        return_exceptions=True,
    )
    _assign(result, "sectorFundListSpot", sector_spot, list)
    _assign(result, "sectorFundListFutures", sector_fut, list)
    if isinstance(sector_spot, list) and sector_spot:
        result["sectorFundListSpot"] = sector_spot[:25]
    if isinstance(sector_fut, list) and sector_fut:
        result["sectorFundListFutures"] = sector_fut[:25]

    if isinstance(chance_all, list):
        result["aiChanceList"] = chance_all[:40]
    if isinstance(risk_all, list):
        result["aiRiskList"] = risk_all[:40]
    if isinstance(funds_all, list):
        result["aiFundsList"] = funds_all[:40]
    _assign(result, "aiMarketAnalyseHistory", mkt_hist, list)

    ai_signals: Dict[str, Any] = {}
    for label, data in (("chance", chance_all), ("risk", risk_all), ("funds", funds_all)):
        if not isinstance(data, list):
            continue
        matched = [
            item for item in data
            if str(item.get("symbol") or item.get("tokenSymbol") or "").upper() == sym
        ]
        if matched:
            ai_signals[label] = matched[0]
    if ai_signals:
        result["aiSignals"] = ai_signals

    # 板块内代币（现货/合约各取资金 Top3 板块）
    sector_coin_spot: Dict[str, List] = {}
    sector_coin_fut: Dict[str, List] = {}
    if isinstance(sector_spot, list):
        for tag in _top_sector_tags(sector_spot, 3):
            try:
                coins = await _g(get_sector_coin_trade_list(tag, 1))
                if isinstance(coins, list) and coins:
                    sector_coin_spot[tag] = coins[:30]
            except Exception as exc:
                logger.debug("VS sector coin spot %s: %s", tag, exc)
    if isinstance(sector_fut, list):
        for tag in _top_sector_tags(sector_fut, 3):
            try:
                coins = await _g(get_sector_coin_trade_list(tag, 2))
                if isinstance(coins, list) and coins:
                    sector_coin_fut[tag] = coins[:30]
            except Exception as exc:
                logger.debug("VS sector coin fut %s: %s", tag, exc)
    if sector_coin_spot:
        result["sectorCoinTradeSpot"] = sector_coin_spot
    if sector_coin_fut:
        result["sectorCoinTradeFutures"] = sector_coin_fut

    # ── Top 持仓地址四维趋势 ─────────────────────────────────────
    holders = result.get("holderList") or []
    top_addrs = [
        str(h.get("address") or "").strip()
        for h in holders[:3]
        if h.get("address")
    ]
    if top_addrs:
        addr_trends: List[Dict[str, Any]] = []
        for addr in top_addrs:
            bal, pnl, hold, tc = await asyncio.gather(
                _g(get_address_balance_trend(vs_id, addr)),
                _g(get_address_profit_loss_trend(vs_id, addr)),
                _g(get_address_hold_trend(vs_id, addr)),
                _g(get_address_trade_count_trend(vs_id, addr)),
                return_exceptions=True,
            )
            entry: Dict[str, Any] = {"address": addr}
            if isinstance(bal, list) and bal:
                entry["balanceTrend"] = bal
            if isinstance(pnl, list) and pnl:
                entry["profitLossTrend"] = pnl
            if isinstance(hold, list) and hold:
                entry["holdTrend"] = hold
            if isinstance(tc, list) and tc:
                entry["tradeCountTrend"] = tc
            if len(entry) > 1:
                addr_trends.append(entry)
        if addr_trends:
            result["topHolderAddressTrends"] = addr_trends

    # ── SSE：优先常驻 Worker 缓存，否则短连接采样 ─────────────────
    try:
        from web.api.valuescan_sse_worker import get_worker_snapshot, worker_enabled

        if worker_enabled():
            snap = get_worker_snapshot(vs_id, sym)
            if snap.get("market"):
                result["sseMarketEvents"] = snap["market"]
            if snap.get("signals"):
                result["sseSignalEvents"] = snap["signals"]
            result["sseWorker"] = snap.get("status")
        elif VS_FETCH_SSE:
            mkt_sse, sig_sse = await asyncio.gather(
                fetch_sse_market_latest(6.0),
                fetch_sse_signal_latest(vs_id, 6.0),
                return_exceptions=True,
            )
            if isinstance(mkt_sse, list) and mkt_sse:
                result["sseMarketEvents"] = mkt_sse
            if isinstance(sig_sse, list) and sig_sse:
                result["sseSignalEvents"] = sig_sse
    except Exception as exc:
        logger.debug("VS SSE bundle: %s", exc)

    return result
