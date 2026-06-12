# -*- coding: utf-8 -*-
"""
Dashboard data-fetching service layer.

Centralizes all external data access (MCP tools, KuCoin API, fallback sources)
so that API handlers stay thin and logic is never duplicated.
"""

import asyncio
import json
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from html import unescape
from typing import Any, Dict, List, Optional, Tuple

from libs import http
from quant.market_analysis import analyze_candles, merge_live_price_into_candles, normalize_candle

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# External service URLs (configurable via env)
# ---------------------------------------------------------------------------
KUCOIN_API_BASE = os.environ.get("KUCOIN_PUBLIC_API_BASE", "https://api.kucoin.com")
KUCOIN_FUTURES_API_BASE = os.environ.get("KUCOIN_FUTURES_API_BASE", "https://api-futures.kucoin.com")
COINGECKO_NEWS_URL = os.environ.get("COINGECKO_NEWS_URL", "https://api.coingecko.com/api/v3/news")
CRYPTO_NEWS_FALLBACK_URL = os.environ.get("CRYPTO_NEWS_FALLBACK_URL", "https://cryptocurrency.cv/api/news")
POLYMARKET_API = os.environ.get("POLYMARKET_API", "https://gamma-api.polymarket.com")
BLOCKCHAIN_INFO_API = os.environ.get("BLOCKCHAIN_INFO_API", "https://api.blockchain.info")
MEMPOOL_SPACE_API = os.environ.get("MEMPOOL_SPACE_API", "https://mempool.space/api")
FEAR_GREED_API = os.environ.get("FEAR_GREED_API", "https://api.alternative.me/fng/")
TAVILY_SEARCH_API_URL = os.environ.get("TAVILY_SEARCH_API_URL", "https://api.tavily.com/search")


_NEWS_FALLBACKS: List[Tuple[str, str]] = [
    ("coingecko", COINGECKO_NEWS_URL + ("&" if "?" in COINGECKO_NEWS_URL else "?") + "page=1"),
    ("cryptocurrency.cv", CRYPTO_NEWS_FALLBACK_URL),
]

# 本地/无 MCP 时免费新闻源：KuCoin 公告 + 行业 RSS（无需 API Key）
KUCOIN_ANNOUNCEMENTS_URL = os.environ.get(
    "KUCOIN_ANNOUNCEMENTS_URL",
    f"{KUCOIN_API_BASE.rstrip('/')}/api/v3/announcements",
)
_NEWS_RSS_FEEDS: Tuple[Tuple[str, str], ...] = (
    ("coindesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("cointelegraph", "https://cointelegraph.com/rss"),
    ("decrypt", "https://decrypt.co/feed"),
)

_SYMBOL_NEWS_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "BTC": ("btc", "bitcoin"),
    "ETH": ("eth", "ethereum"),
    "SOL": ("sol", "solana"),
    "BNB": ("bnb", "binance"),
    "XRP": ("xrp", "ripple"),
    "DOGE": ("doge", "dogecoin"),
    "ADA": ("ada", "cardano"),
    "DOT": ("dot", "polkadot"),
    "AVAX": ("avax", "avalanche"),
    "LINK": ("link", "chainlink"),
    "MATIC": ("matic", "polygon"),
    "POL": ("pol", "polygon"),
    "LTC": ("ltc", "litecoin"),
    "BCH": ("bch", "bitcoin cash"),
}

# 综合信号 / LLM 信号：与 KuCoin /api/v1/market/candles 的 type 参数一致
KLINE_TIMEFRAMES_SIGNAL_FULL: Tuple[str, ...] = ("15min", "1hour", "4hour", "1day")

# 综合信号用新闻：与 LLM 信号任务一致，尽量多源覆盖
SIGNAL_NEWS_HOURS: int = 72
SIGNAL_NEWS_LIMIT: int = 50


def _dashboard_mcp_enabled() -> bool:
    raw = os.environ.get("DASHBOARD_MCP_ENABLED")
    if raw is not None:
        return raw.lower() in ("1", "true", "yes", "y")
    try:
        from web.config import config as web_config
        mcp_securekey = getattr(web_config, "mcp_client_securekey", "") if web_config else ""
    except Exception:
        mcp_securekey = os.environ.get("MCP_CLIENT_SECUREKEY", "")
    return not (os.environ.get("serverEnv") == "local" and not mcp_securekey)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def utc_range(hours: int = 24) -> Tuple[str, str]:
    """Return (start, end) UTC strings for the last *hours*."""
    now = datetime.now(timezone.utc)
    fmt = "%Y-%m-%d %H:%M:%S"
    return (now - timedelta(hours=hours)).strftime(fmt), now.strftime(fmt)


# ---------------------------------------------------------------------------
# KuCoin public API
# ---------------------------------------------------------------------------
def _kucoin_build_url(path: str, *, base: str = "spot", params: Optional[Dict] = None) -> str:
    base_url = KUCOIN_FUTURES_API_BASE if base == "futures" else KUCOIN_API_BASE
    url = f"{base_url.rstrip('/')}{path}"
    if params:
        from urllib.parse import urlencode
        url = f"{url}?{urlencode(params)}"
    return url


async def kucoin_request(path: str, *, base: str = "spot", params: Optional[Dict] = None) -> Dict[str, Any]:
    """Raw KuCoin JSON body (includes business error codes)."""
    data = await http.get(_kucoin_build_url(path, base=base, params=params), timeout=15)
    return data if isinstance(data, dict) else {"code": "unknown", "msg": str(data)}


async def kucoin_get(path: str, *, base: str = "spot", params: Optional[Dict] = None) -> Any:
    data = await kucoin_request(path, base=base, params=params)
    if data.get("code") not in (None, "200000"):
        raise ValueError(data.get("msg", "KuCoin API error"))
    return data


# ---------------------------------------------------------------------------
# Skills modules (KuCoin public APIs for dashboard /skills/modules)
# ---------------------------------------------------------------------------
_CONVERT_UNSUPPORTED_CODES = frozenset({"102431", "102423", "102424"})
_CONVERT_AGREEMENT_CODE = "102441"


def _skill_module(
    name: str,
    *,
    status: str,
    latency_ms: int,
    data: Any = None,
    error: Optional[str] = None,
    note: Optional[str] = None,
    code: Optional[str] = None,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {"name": name, "status": status, "latencyMs": latency_ms}
    if data is not None:
        out["data"] = data
    if error:
        out["error"] = error
    if note:
        out["note"] = note
    if code:
        out["code"] = code
    return out


async def fetch_convert_skills_data(base: str, quote: str) -> Dict[str, Any]:
    """Convert 闪兑：currencies + symbol（官方要求 orderType=MARKET）。"""
    base = (base or "BTC").strip().upper()
    quote = (quote or "USDT").strip().upper()
    payload: Dict[str, Any] = {
        "fromCurrency": base,
        "toCurrency": quote,
        "orderType": "MARKET",
        "flashSwapSupported": False,
    }

    curr_resp = await kucoin_request("/api/v1/convert/currencies")
    if curr_resp.get("code") == "200000":
        currencies = (curr_resp.get("data") or {}).get("currencies") or []
        listed = {
            str(c.get("currency") or "").upper()
            for c in currencies
            if isinstance(c, dict) and c.get("currency")
        }
        payload["baseInConvertList"] = base in listed
        payload["quoteInConvertList"] = quote in listed
        payload["convertCurrencyCount"] = len(listed)
    else:
        payload["currenciesError"] = curr_resp.get("msg") or curr_resp.get("code")

    sym_resp = await kucoin_request(
        f"/api/v1/convert/symbol?fromCurrency={base}&toCurrency={quote}&orderType=MARKET"
    )
    code = str(sym_resp.get("code") or "")
    payload["kucoinCode"] = code
    if code == "200000":
        payload["flashSwapSupported"] = True
        payload["limits"] = sym_resp.get("data")
        return payload

    payload["message"] = sym_resp.get("msg") or "Convert unavailable"
    return payload


async def fetch_margin_mark_for_symbol(symbol: str) -> Dict[str, Any]:
    """杠杆标记价格：仅返回与当前 base 相关的交易对，避免整表刷屏。"""
    base = symbol.split("-")[0].upper() if "-" in symbol else (symbol or "BTC").upper()
    quote = symbol.split("-")[1].upper() if "-" in symbol else "USDT"
    data = await kucoin_get("/api/v3/mark-price/all-symbols")
    rows = data.get("data") or []
    if not isinstance(rows, list):
        return {"symbol": symbol, "relatedPairs": []}
    related = [
        r for r in rows
        if isinstance(r, dict) and (
            str(r.get("symbol") or "").startswith(f"{base}-")
            or str(r.get("symbol") or "").endswith(f"-{base}")
            or str(r.get("symbol") or "") == f"{base}-{quote}"
        )
    ][:20]
    direct = next(
        (r for r in rows if isinstance(r, dict) and str(r.get("symbol") or "") == f"{base}-{quote}"),
        None,
    )
    return {
        "symbol": f"{base}-{quote}",
        "directMark": direct,
        "relatedPairs": related,
        "relatedCount": len(related),
    }


async def fetch_symbol_info(pair: str) -> Dict[str, Any]:
    data = await kucoin_get(f"/api/v2/symbols/{pair}")
    info = data.get("data") or {}
    if not isinstance(info, dict):
        return {}
    keys = (
        "symbol", "baseCurrency", "quoteCurrency", "enableTrading", "isMarginEnabled",
        "baseMinSize", "quoteMinSize", "priceIncrement", "minFunds",
        "makerFeeCoefficient", "takerFeeCoefficient",
    )
    return {k: info.get(k) for k in keys if k in info}


async def fetch_orderbook_level1(pair: str) -> Dict[str, Any]:
    data = await kucoin_get(f"/api/v1/market/orderbook/level1?symbol={pair}")
    d = data.get("data") or {}
    best_bid = float(d.get("bestBid") or 0)
    best_ask = float(d.get("bestAsk") or 0)
    mid = (best_bid + best_ask) / 2 if best_bid and best_ask else 0.0
    spread = best_ask - best_bid if best_bid and best_ask else 0.0
    return {
        "price": d.get("price"),
        "bestBid": d.get("bestBid"),
        "bestAsk": d.get("bestAsk"),
        "bestBidSize": d.get("bestBidSize"),
        "bestAskSize": d.get("bestAskSize"),
        "spread": spread,
        "spreadPct": (spread / mid * 100) if mid else 0.0,
    }


async def fetch_realtime_snapshot(pair: str) -> Dict[str, Any]:
    """REST snapshot: spot L1 book + futures mark price + futures ticker (sub-minute refresh)."""
    futures_symbol = to_contract_symbol(pair)
    level1_task = fetch_orderbook_level1(pair)
    mark_task = (
        fetch_futures_mark_price(futures_symbol)
        if futures_symbol
        else asyncio.sleep(0, result={})
    )
    ticker_task = (
        kucoin_get(f"/api/v1/ticker?symbol={futures_symbol}", base="futures")
        if futures_symbol
        else asyncio.sleep(0, result={})
    )

    level1, mark, ticker_resp = await asyncio.gather(
        level1_task,
        mark_task,
        ticker_task,
        return_exceptions=True,
    )

    if isinstance(level1, Exception):
        logger.warning("realtime level1 error for %s: %s", pair, level1)
        level1 = {}
    if isinstance(mark, Exception):
        logger.warning("realtime mark price error for %s: %s", pair, mark)
        mark = {}
    if isinstance(ticker_resp, Exception):
        logger.warning("realtime futures ticker error for %s: %s", pair, ticker_resp)
        ticker_data: Dict[str, Any] = {}
    else:
        ticker_data = (ticker_resp.get("data") or {}) if isinstance(ticker_resp, dict) else {}

    def _num(val: Any) -> Optional[float]:
        try:
            if val is None or val == "":
                return None
            return float(val)
        except (TypeError, ValueError):
            return None

    futures_ticker = {
        "symbol": futures_symbol,
        "last": _num(ticker_data.get("price") or ticker_data.get("lastTradePrice")),
        "bestBid": _num(ticker_data.get("bestBidPrice")),
        "bestAsk": _num(ticker_data.get("bestAskPrice")),
    }
    mark_price = _num((mark or {}).get("value") or (mark or {}).get("markPrice"))

    return {
        "available": bool(level1 or mark or futures_ticker.get("last")),
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "pair": pair,
        "futuresSymbol": futures_symbol,
        "level1": level1 if isinstance(level1, dict) else {},
        "futuresMarkPrice": mark if isinstance(mark, dict) else {},
        "futuresTicker": futures_ticker,
        "markPrice": mark_price,
        "spotLast": _num((level1 or {}).get("price")),
    }


def _parse_kucoin_candle_rows(rows: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        try:
            out.append({
                "time": int(row[0]),
                "open": float(row[1]),
                "close": float(row[2]),
                "high": float(row[3]),
                "low": float(row[4]),
                "volume": float(row[5]),
                "turnover": float(row[6]) if len(row) > 6 else 0.0,
            })
        except (TypeError, ValueError, IndexError):
            continue
    return out


def _summarize_kline_history(candles: List[Dict[str, Any]], timeframe: str) -> Dict[str, Any]:
    if not candles:
        return {"timeframe": timeframe, "count": 0}
    candles = sorted(candles, key=lambda c: c["time"])
    closes = [c["close"] for c in candles]
    first, last = candles[0], candles[-1]
    start_ts = datetime.fromtimestamp(first["time"], tz=timezone.utc).isoformat()
    end_ts = datetime.fromtimestamp(last["time"], tz=timezone.utc).isoformat()
    base_close = closes[0] or 0.0
    return {
        "timeframe": timeframe,
        "count": len(candles),
        "from": start_ts,
        "to": end_ts,
        "open": first["open"],
        "close": last["close"],
        "high": max(c["high"] for c in candles),
        "low": min(c["low"] for c in candles),
        "changePct": ((closes[-1] - base_close) / base_close * 100) if base_close else 0.0,
        "avgVolume": sum(c["volume"] for c in candles) / len(candles),
        "totalTurnover": sum(c.get("turnover") or 0 for c in candles),
        "recentCloses": closes[-12:],
    }


async def fetch_skills_klines(
    pair: str,
    *,
    candle_type: str,
    limit: int,
    base: str = "spot",
) -> Dict[str, Any]:
    limit = max(10, min(200, int(limit or 60)))
    if base == "futures":
        end_at = int(datetime.now(timezone.utc).timestamp() * 1000)
        gran_map = {"1hour": 60, "4hour": 240, "1day": 1440, "15min": 15}
        gran = gran_map.get(candle_type, 60)
        start_at = end_at - limit * gran * 60 * 1000
        resp = await kucoin_get(
            "/api/v1/kline/query",
            base="futures",
            params={"symbol": pair, "granularity": gran, "from": start_at, "to": end_at},
        )
    else:
        resp = await kucoin_get(f"/api/v1/market/candles?symbol={pair}&type={candle_type}")
    rows = _parse_kucoin_candle_rows(resp.get("data") if isinstance(resp, dict) else [])
    if rows:
        rows = sorted(rows, key=lambda c: c["time"])[-limit:]
    summary = _summarize_kline_history(rows, candle_type)
    summary["symbol"] = pair
    summary["market"] = base
    return summary


async def fetch_currency_meta(currency: str) -> Dict[str, Any]:
    cur = (currency or "BTC").strip().upper()
    resp = await kucoin_get(f"/api/v3/currencies/{cur}")
    info = resp.get("data") if isinstance(resp.get("data"), dict) else {}
    keys = (
        "currency", "name", "fullName", "precision", "confirms", "isMarginEnabled",
        "isDebitEnabled", "chains",
    )
    out = {k: info.get(k) for k in keys if k in info}
    chains = info.get("chains")
    if isinstance(chains, list):
        out["chains"] = [
            {kk: ch.get(kk) for kk in ("chainName", "withdrawalMinSize", "depositMinSize", "isWithdrawEnabled", "isDepositEnabled")}
            for ch in chains[:5]
            if isinstance(ch, dict)
        ]
    return out


async def fetch_fiat_reference_price(currency: str) -> Dict[str, Any]:
    cur = (currency or "BTC").strip().upper()
    resp = await kucoin_get(f"/api/v1/prices?base=USD&currencies={cur}")
    prices = resp.get("data") if isinstance(resp.get("data"), dict) else {}
    return {"base": "USD", "currency": cur, "priceUsd": prices.get(cur)}


async def fetch_quote_market_tickers(quote: str, *, search: str = "", limit: int = 15) -> Dict[str, Any]:
    resp = await kucoin_get("/api/v1/market/allTickers")
    tickers = (resp.get("data") or {}).get("ticker") if isinstance(resp.get("data"), dict) else []
    if not isinstance(tickers, list):
        tickers = []
    q = (quote or "USDT").upper()
    s = (search or "").upper()
    filtered = [
        t for t in tickers
        if isinstance(t, dict) and str(t.get("symbol") or "").endswith(f"-{q}")
        and (not s or s in str(t.get("symbol") or "").upper())
    ]
    filtered.sort(key=lambda t: float(t.get("volValue") or 0), reverse=True)
    slim = [
        {
            "symbol": t.get("symbol"),
            "last": t.get("last"),
            "changeRate": t.get("changeRate"),
            "volValue": t.get("volValue"),
            "high": t.get("high"),
            "low": t.get("low"),
        }
        for t in filtered[:limit]
    ]
    return {"quote": q, "search": s or None, "count": len(slim), "topByVolume": slim}


def _kucoin_list_payload(data: Any) -> List[Any]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return items
    return []


async def fetch_margin_cross_for_symbol(symbol: str) -> Dict[str, Any]:
    resp = await kucoin_get("/api/v3/margin/symbols")
    rows = _kucoin_list_payload(resp.get("data"))
    hit = next((r for r in rows if isinstance(r, dict) and r.get("symbol") == symbol), None)
    return {
        "symbol": symbol,
        "crossMargin": hit,
        "enabled": bool(hit and hit.get("enableTrading")),
        "listedCount": len(rows),
    }


async def fetch_margin_isolated_for_symbol(symbol: str) -> Dict[str, Any]:
    resp = await kucoin_get("/api/v1/isolated/symbols")
    rows = _kucoin_list_payload(resp.get("data"))
    hit = next((r for r in rows if isinstance(r, dict) and r.get("symbol") == symbol), None)
    enabled = False
    if hit:
        enabled = bool(hit.get("tradeEnable", hit.get("enableTrading")))
    return {"symbol": symbol, "isolatedMargin": hit, "enabled": enabled, "listedCount": len(rows)}


async def fetch_margin_config_snapshot(base: str) -> Dict[str, Any]:
    resp = await kucoin_get("/api/v1/margin/config")
    data = resp.get("data") if isinstance(resp.get("data"), dict) else {}
    currencies = data.get("currencyList") or []
    base = (base or "").upper()
    return {
        "currencyCount": len(currencies) if isinstance(currencies, list) else 0,
        "baseSupported": base in currencies if isinstance(currencies, list) else False,
        "maxLeverage": data.get("maxLeverage"),
        "warningDebtRatio": data.get("warningDebtRatio"),
        "liqDebtRatio": data.get("liqDebtRatio"),
    }


async def fetch_margin_collateral_for_currency(currency: str) -> Dict[str, Any]:
    cur = (currency or "BTC").upper()
    resp = await kucoin_get("/api/v3/margin/collateralRatio")
    tiers = resp.get("data") if isinstance(resp.get("data"), list) else []
    matched = None
    for tier in tiers:
        if not isinstance(tier, dict):
            continue
        clist = tier.get("currencyList") or []
        if cur in clist:
            matched = {
                "tier": tier.get("tier"),
                "collateralRatio": tier.get("collateralRatio"),
                "currenciesInTier": len(clist),
            }
            break
    return {"currency": cur, "tier": matched, "totalTiers": len(tiers)}


from web.api.futures_symbols import spot_pair_to_native_futures_symbol


async def fetch_futures_contract_meta(futures_symbol: str) -> Dict[str, Any]:
    native = futures_symbol.upper()
    if not native.endswith("M"):
        native = spot_pair_to_native_futures_symbol(futures_symbol)
    resp = await kucoin_get(f"/api/v1/contracts/{native}", base="futures")
    info = resp.get("data") if isinstance(resp.get("data"), dict) else {}
    keys = (
        "symbol", "rootSymbol", "type", "baseCurrency", "quoteCurrency", "settleCurrency",
        "maxOrderQty", "maxPrice", "lotSize", "tickSize", "indexPriceTickSize",
        "multiplier", "initialMargin", "maintainMargin", "maxRiskLimit", "status",
        "fundingFeeRate", "predictedFundingFeeRate", "fundingRateGranularity",
        "openInterest", "turnoverOf24h", "volumeOf24h", "markPrice", "indexPrice",
    )
    return {k: info.get(k) for k in keys if k in info}


async def fetch_futures_funding_history_summary(futures_symbol: str, *, days: int = 30) -> Dict[str, Any]:
    days = max(7, min(90, int(days or 30)))
    end_at = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_at = end_at - days * 86_400_000
    resp = await kucoin_get(
        "/api/v1/contract/funding-rates",
        base="futures",
        params={"symbol": futures_symbol, "from": start_at, "to": end_at},
    )
    rows = resp.get("data") if isinstance(resp.get("data"), list) else []
    rates: List[float] = []
    points: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            rate = float(row.get("fundingRate") or 0)
            rates.append(rate)
            points.append({
                "time": row.get("timePoint") or row.get("fundingTime"),
                "fundingRate": rate,
            })
        except (TypeError, ValueError):
            continue
    if not rates:
        return {"symbol": futures_symbol, "days": days, "count": 0}
    return {
        "symbol": futures_symbol,
        "days": days,
        "count": len(rates),
        "avgFundingRate": sum(rates) / len(rates),
        "maxFundingRate": max(rates),
        "minFundingRate": min(rates),
        "latest": points[-1] if points else None,
        "recent": points[-10:],
    }


async def fetch_futures_mark_price(futures_symbol: str) -> Dict[str, Any]:
    native = futures_symbol.upper()
    if not native.endswith("M"):
        native = spot_pair_to_native_futures_symbol(futures_symbol)
    try:
        resp = await kucoin_get(f"/api/v1/mark-price/{native}/current", base="futures")
        return resp.get("data") if isinstance(resp.get("data"), dict) else {}
    except ValueError as exc:
        logger.warning("futures mark price failed for %s (%s): %s", futures_symbol, native, exc)
        return {}


async def fetch_futures_trades_snapshot(futures_symbol: str, *, limit: int = 20) -> Dict[str, Any]:
    resp = await kucoin_get(f"/api/v1/trade/history?symbol={futures_symbol}", base="futures")
    rows = resp.get("data") if isinstance(resp.get("data"), list) else []
    trades = []
    buy_vol = sell_vol = 0.0
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        side = str(row.get("side") or "").lower()
        try:
            size = float(row.get("size") or 0)
        except (TypeError, ValueError):
            size = 0.0
        if side == "buy":
            buy_vol += size
        elif side == "sell":
            sell_vol += size
        trades.append({
            "side": side,
            "price": row.get("price"),
            "size": row.get("size"),
            "ts": row.get("ts"),
        })
    total = buy_vol + sell_vol
    return {
        "symbol": futures_symbol,
        "count": len(trades),
        "buyVolume": buy_vol,
        "sellVolume": sell_vol,
        "buyRatio": buy_vol / total if total else 0.0,
        "recent": trades[:10],
    }


async def fetch_fear_greed_extended(*, limit: int = 14) -> Dict[str, Any]:
    limit = max(2, min(30, int(limit or 14)))
    try:
        data = await http.get(f"{FEAR_GREED_API}?limit={limit}&format=json", timeout=10)
    except Exception as exc:
        logger.warning("fear_greed extended error: %s", exc)
        return {}
    if not isinstance(data, dict):
        return {}
    items = data.get("data") or []
    series = [
        {
            "value": int(it.get("value", 0)),
            "label": it.get("value_classification"),
            "timestamp": it.get("timestamp"),
        }
        for it in items
        if isinstance(it, dict)
    ]
    if not series:
        return {}
    today = series[0]
    week_ago = series[6] if len(series) > 6 else series[-1]
    return {
        "value": today["value"],
        "label": today.get("label"),
        "change7d": today["value"] - week_ago["value"],
        "historyDays": len(series),
        "history": series,
    }


async def fetch_polymarket_crypto_brief(*, limit: int = 5) -> Dict[str, Any]:
    markets = await _fetch_polymarket(limit)
    return {"count": len(markets), "markets": markets}


async def fetch_btc_network_skills_snapshot() -> Dict[str, Any]:
    stats, mempool, valuation = await asyncio.gather(
        fetch_blockchain_stats(),
        fetch_mempool_stats(),
        fetch_valuation_metrics("BTC"),
        return_exceptions=True,
    )
    out: Dict[str, Any] = {}
    if isinstance(stats, dict):
        out["blockchainStats"] = stats
    if isinstance(mempool, dict):
        out["mempool"] = mempool
    if isinstance(valuation, dict):
        out["valuation"] = valuation
    return out


async def fetch_markets_overview() -> Dict[str, Any]:
    resp = await kucoin_get("/api/v1/markets")
    data = resp.get("data") if isinstance(resp.get("data"), list) else []
    return {"marketCount": len(data), "sample": data[:8] if isinstance(data, list) else []}


async def fetch_etf_info_brief() -> Dict[str, Any]:
    resp = await kucoin_get("/api/v3/etf/info")
    rows = resp.get("data") if isinstance(resp.get("data"), list) else []
    return {"etfCount": len(rows), "sample": rows[:6]}


async def fetch_announcements_snapshot(base: str, *, limit: int = 10) -> Dict[str, Any]:
    raw = await kucoin_get("/api/v3/announcements?currentPage=1&pageSize=50")
    block = raw.get("data") or {}
    items = block.get("items") if isinstance(block, dict) else []
    if not isinstance(items, list):
        items = []
    kw = (base or "").strip().lower()
    matched = [
        it for it in items
        if isinstance(it, dict) and kw and (
            kw in str(it.get("annTitle") or "").lower()
            or kw in str(it.get("annDesc") or "").lower()
        )
    ]
    pick = matched[:limit] if matched else items[:limit]

    def _row(it: Dict) -> Dict[str, Any]:
        ctime = it.get("cTime")
        published = ""
        if ctime is not None:
            try:
                published = datetime.fromtimestamp(int(ctime) / 1000, tz=timezone.utc).isoformat()
            except (TypeError, ValueError, OSError):
                published = str(ctime)
        return {
            "title": str(it.get("annTitle") or "").strip(),
            "url": str(it.get("annUrl") or ""),
            "publishedAt": published,
            "types": it.get("annType") or [],
        }

    return {
        "total": block.get("totalNum") if isinstance(block, dict) else len(items),
        "matchedBySymbol": len(matched),
        "items": [_row(it) for it in pick if isinstance(it, dict)],
    }


async def _skill_task(name: str, coro) -> Dict[str, Any]:
    t0 = time.perf_counter()
    try:
        result = await coro
        if isinstance(result, dict) and result.get("status") in (
            "ok", "error", "unavailable", "auth_required",
        ):
            result.setdefault("name", name)
            result["latencyMs"] = int((time.perf_counter() - t0) * 1000)
            return result
        return _skill_module(name, status="ok", latency_ms=int((time.perf_counter() - t0) * 1000), data=result)
    except Exception as exc:
        return _skill_module(
            name,
            status="error",
            latency_ms=int((time.perf_counter() - t0) * 1000),
            error=str(exc),
        )


async def _skill_convert_task(base: str, quote: str) -> Dict[str, Any]:
    t0 = time.perf_counter()
    try:
        data = await fetch_convert_skills_data(base, quote)
        latency = int((time.perf_counter() - t0) * 1000)
        code = str(data.get("kucoinCode") or "")
        if data.get("flashSwapSupported"):
            return _skill_module("convert", status="ok", latency_ms=latency, data=data)
        if code in _CONVERT_UNSUPPORTED_CODES:
            return _skill_module(
                "convert",
                status="unavailable",
                latency_ms=latency,
                data=data,
                note=f"闪兑不支持 {base}→{quote}（与现货交易无关，可用 spot 模块）",
                code=code,
            )
        if code == _CONVERT_AGREEMENT_CODE:
            return _skill_module(
                "convert",
                status="auth_required",
                latency_ms=latency,
                data=data,
                note="需在 KuCoin App/Web 主账号签署闪兑协议后使用",
                code=code,
            )
        return _skill_module(
            "convert",
            status="error",
            latency_ms=latency,
            data=data,
            error=str(data.get("message") or "Convert 查询失败"),
            code=code or None,
        )
    except Exception as exc:
        return _skill_module(
            "convert",
            status="error",
            latency_ms=int((time.perf_counter() - t0) * 1000),
            error=str(exc),
        )


_SKILLS_MODULE_ORDER: Tuple[str, ...] = (
    "spot",
    "symbol-info",
    "currency-info",
    "fiat-price",
    "orderbook",
    "orderbook-l2",
    "recent-trades",
    "klines-15m",
    "klines-1h",
    "klines-4h",
    "klines-1d",
    "quote-rank",
    "markets",
    "fear-greed",
    "polymarket",
    "futures-ticker",
    "futures-contract",
    "futures-derivatives",
    "futures-funding-30d",
    "futures-mark-price",
    "futures-trades",
    "futures-klines-1h",
    "futures-klines-1d",
    "margin-trading",
    "margin-cross",
    "margin-isolated",
    "margin-config",
    "margin-collateral",
    "etf-info",
    "convert",
    "announcements",
    "btc-network",
)


async def build_skills_modules(symbol: str) -> List[Dict[str, Any]]:
    """并行拉取仪表盘技能模块 — 尽可能多的公开/免费数据源。"""
    symbol = (symbol or "BTC-USDT").strip().upper()
    base = symbol.split("-")[0] if "-" in symbol else "BTC"
    quote = symbol.split("-")[1] if "-" in symbol else "USDT"
    futures_symbol = to_contract_symbol(symbol)

    async def _spot_stats() -> Dict[str, Any]:
        resp = await kucoin_get(f"/api/v1/market/stats?symbol={symbol}")
        return resp.get("data") if isinstance(resp.get("data"), dict) else resp

    async def _futures_ticker() -> Dict[str, Any]:
        resp = await kucoin_get(f"/api/v1/ticker?symbol={futures_symbol}", base="futures")
        return resp.get("data") if isinstance(resp.get("data"), dict) else resp

    tasks: List[Any] = [
        _skill_task("spot", _spot_stats()),
        _skill_task("symbol-info", fetch_symbol_info(symbol)),
        _skill_task("currency-info", fetch_currency_meta(base)),
        _skill_task("fiat-price", fetch_fiat_reference_price(base)),
        _skill_task("orderbook", fetch_orderbook_level1(symbol)),
        _skill_task("orderbook-l2", fetch_orderbook_snapshot(symbol, size=20)),
        _skill_task("recent-trades", fetch_recent_trades(symbol, limit=50)),
        _skill_task("klines-15m", fetch_skills_klines(symbol, candle_type="15min", limit=96, base="spot")),
        _skill_task("klines-1h", fetch_skills_klines(symbol, candle_type="1hour", limit=168, base="spot")),
        _skill_task("klines-4h", fetch_skills_klines(symbol, candle_type="4hour", limit=120, base="spot")),
        _skill_task("klines-1d", fetch_skills_klines(symbol, candle_type="1day", limit=90, base="spot")),
        _skill_task("quote-rank", fetch_quote_market_tickers(quote, search=base, limit=12)),
        _skill_task("markets", fetch_markets_overview()),
        _skill_task("fear-greed", fetch_fear_greed_extended(limit=14)),
        _skill_task("polymarket", fetch_polymarket_crypto_brief(limit=5)),
        _skill_task("margin-trading", fetch_margin_mark_for_symbol(symbol)),
        _skill_task("margin-cross", fetch_margin_cross_for_symbol(symbol)),
        _skill_task("margin-isolated", fetch_margin_isolated_for_symbol(symbol)),
        _skill_task("margin-config", fetch_margin_config_snapshot(base)),
        _skill_task("margin-collateral", fetch_margin_collateral_for_currency(base)),
        _skill_task("etf-info", fetch_etf_info_brief()),
        _skill_task("announcements", fetch_announcements_snapshot(base, limit=10)),
        _skill_convert_task(base, quote),
    ]

    if futures_symbol:
        tasks.extend([
            _skill_task("futures-ticker", _futures_ticker()),
            _skill_task("futures-contract", fetch_futures_contract_meta(futures_symbol)),
            _skill_task("futures-derivatives", fetch_derivatives_snapshot(symbol)),
            _skill_task("futures-funding-30d", fetch_futures_funding_history_summary(futures_symbol, days=30)),
            _skill_task("futures-mark-price", fetch_futures_mark_price(futures_symbol)),
            _skill_task("futures-trades", fetch_futures_trades_snapshot(futures_symbol, limit=30)),
            _skill_task(
                "futures-klines-1h",
                fetch_skills_klines(futures_symbol, candle_type="1hour", limit=168, base="futures"),
            ),
            _skill_task(
                "futures-klines-1d",
                fetch_skills_klines(futures_symbol, candle_type="1day", limit=90, base="futures"),
            ),
        ])

    if base == "BTC":
        tasks.append(_skill_task("btc-network", fetch_btc_network_skills_snapshot()))

    modules = await asyncio.gather(*tasks)
    rank = {name: i for i, name in enumerate(_SKILLS_MODULE_ORDER)}
    return sorted(modules, key=lambda m: rank.get(m.get("name", ""), 999))


# ---------------------------------------------------------------------------
# MCP tool caller (lazy import to avoid circular deps at module load)
# ---------------------------------------------------------------------------
async def _call_mcp_tool(name: str, arguments: Dict) -> Any:
    from mcp.mcp_http_client import mcp_client
    from mcp.types import CallToolRequestParams
    return await mcp_client.call_tool(CallToolRequestParams(name=name, arguments=arguments))


def _extract_json_from_mcp(result) -> List[Dict]:
    if not result or not getattr(result, "content", None):
        return []
    out: List[Dict] = []
    for block in result.content:
        text = getattr(block, "text", None)
        if not text:
            continue
        if isinstance(text, dict):
            out.append(text)
        else:
            try:
                out.append(json.loads(text))
            except (json.JSONDecodeError, TypeError):
                pass
    return out


# ---------------------------------------------------------------------------
# News fetching (web_search + coins_news + HTTP fallbacks)
# ---------------------------------------------------------------------------
def _normalize_news_item(item: Dict, idx: int) -> Dict:
    return {
        "id": str(item.get("id") or item.get("news_id") or idx),
        "title": str(item.get("title") or item.get("name") or "").strip() or "无标题",
        "url": str(item.get("url") or item.get("news_url") or item.get("link") or ""),
        "source": str(item.get("source") or item.get("news_site") or item.get("sourceKey") or item.get("provider") or "—"),
        "publishedAt": str(
            item.get("published_at") or item.get("publishedAt") or item.get("pubDate")
            or item.get("time") or item.get("date") or ""
        ),
        "body": str(item.get("body") or item.get("description") or item.get("content") or "")[:200],
    }


def _normalize_mcp_news(result, limit: int) -> List[Dict]:
    out: List[Dict] = []
    for node in _extract_json_from_mcp(result):
        if not isinstance(node, dict):
            continue
        items = node.get("data") or node.get("list") or (node if isinstance(node.get("items"), list) else [])
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    out.append(_normalize_news_item(item, len(out)))
        if len(out) >= limit:
            break
    return out[:limit]


def _normalize_web_search_results(result, limit: int) -> List[Dict]:
    """Extract news items from web_search MCP tool results."""
    out: List[Dict] = []
    if not result or not getattr(result, "content", None):
        return out
    for block in result.content:
        text = getattr(block, "text", None)
        if not text:
            continue
        try:
            data = json.loads(text) if isinstance(text, str) else text
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        items = data.get("results") or data.get("data") or []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            out.append({
                "id": str(len(out)),
                "title": title,
                "url": str(item.get("url") or item.get("link") or ""),
                "source": "web_search",
                "publishedAt": str(item.get("publishedAt") or item.get("date") or ""),
                "body": str(
                    item.get("snippet") or item.get("content")
                    or item.get("description") or item.get("body") or ""
                )[:200],
            })
            if len(out) >= limit:
                return out
    return out


async def _fetch_news_via_web_search(symbol: str, limit: int) -> List[Dict]:
    """Use web_search MCP tool to fetch latest crypto news."""
    queries = [
        f"{symbol} crypto news today breaking",
        f"{symbol} price analysis market update {datetime.utcnow().strftime('%Y-%m')}",
        f"{symbol} cryptocurrency whale on-chain analysis latest",
    ]
    all_items: List[Dict] = []
    seen_titles: set = set()

    for query in queries:
        if len(all_items) >= limit:
            break
        try:
            result = await _call_mcp_tool("web_search", {"query": query})
            items = _normalize_web_search_results(result, limit - len(all_items))
            for item in items:
                dedup_key = item["title"].lower()[:60]
                if dedup_key not in seen_titles:
                    seen_titles.add(dedup_key)
                    all_items.append(item)
        except Exception as exc:
            logger.warning("web_search news (%s) error: %s", query, exc)

    return all_items[:limit]


async def _fetch_news_via_local_search(symbol: str, limit: int) -> List[Dict]:
    """Use local Tavily search API as fallback when MCP is unavailable."""
    api_key = (os.environ.get("TAVILY_API_KEY") or "").strip()
    if not api_key:
        return []

    queries = [
        f"{symbol} crypto news today",
        f"{symbol} token market update",
    ]
    all_items: List[Dict] = []
    seen_titles: set = set()

    for query in queries:
        if len(all_items) >= limit:
            break
        try:
            payload = {
                "api_key": api_key,
                "query": query,
                "search_depth": "advanced",
                "max_results": min(8, max(1, limit - len(all_items))),
                "include_answer": False,
                "include_raw_content": False,
                "topic": "news",
            }
            result = await http.post(TAVILY_SEARCH_API_URL, json=payload, timeout=15)
            if not isinstance(result, dict):
                continue
            items = result.get("results") or []
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or "").strip()
                if not title:
                    continue
                dedup_key = title.lower()[:60]
                if dedup_key in seen_titles:
                    continue
                seen_titles.add(dedup_key)
                all_items.append({
                    "id": str(len(all_items)),
                    "title": title,
                    "url": str(item.get("url") or item.get("link") or ""),
                    "source": "local_web_search",
                    "publishedAt": str(item.get("published_date") or item.get("publishedAt") or ""),
                    "body": str(item.get("content") or item.get("snippet") or item.get("description") or "")[:200],
                })
                if len(all_items) >= limit:
                    break
        except Exception as exc:
            logger.warning("local_web_search news (%s) error: %s", query, exc)

    return all_items[:limit]


async def _fetch_news_http(url: str, limit: int) -> List[Dict]:
    raw = await http.get(url, timeout=12)
    items: List[Dict] = []
    if isinstance(raw, dict):
        candidates = raw.get("data") or raw.get("articles") or raw.get("news") or raw.get("items") or []
        items = candidates[:limit] if isinstance(candidates, list) else []
    elif isinstance(raw, list):
        items = raw[:limit]
    return [_normalize_news_item(it, i) for i, it in enumerate(items) if isinstance(it, dict)]


def _symbol_news_keywords(symbol: str) -> Tuple[str, ...]:
    sym = (symbol or "BTC").strip().upper()
    if sym in _SYMBOL_NEWS_KEYWORDS:
        return _SYMBOL_NEWS_KEYWORDS[sym]
    return (sym.lower(),)


def _news_text_matches_symbol(text: str, keywords: Tuple[str, ...]) -> bool:
    lower = (text or "").lower()
    return any(kw in lower for kw in keywords)


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", unescape(text or "")).strip()


def _rss_child_text(parent: ET.Element, name: str) -> str:
    for child in parent:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if tag == name:
            return (child.text or "").strip()
    return ""


def _parse_rss_feed(xml_text: str, source: str, limit: int) -> List[Dict]:
    if not (xml_text or "").strip():
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("rss parse error (%s): %s", source, exc)
        return []
    out: List[Dict] = []
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag != "item":
            continue
        title = _rss_child_text(elem, "title")
        if not title:
            continue
        link = _rss_child_text(elem, "link")
        desc = _strip_html(_rss_child_text(elem, "description"))
        pub = _rss_child_text(elem, "pubDate") or _rss_child_text(elem, "published")
        out.append({
            "id": str(len(out)),
            "title": title,
            "url": link,
            "source": source,
            "publishedAt": pub,
            "body": desc[:200],
        })
        if len(out) >= limit:
            break
    return out


async def _fetch_news_rss(symbol: str, limit: int) -> List[Dict]:
    """Industry RSS feeds; prefer headlines mentioning the symbol."""
    keywords = _symbol_news_keywords(symbol)
    matched: List[Dict] = []
    general: List[Dict] = []
    per_feed = max(8, limit)

    async def _one(name: str, url: str) -> List[Dict]:
        try:
            raw = await http.get(url, timeout=12)
            if not isinstance(raw, str):
                return []
            return _parse_rss_feed(raw, name, per_feed)
        except Exception as exc:
            logger.warning("rss news (%s) error: %s", name, exc)
            return []

    batches = await asyncio.gather(*[_one(name, url) for name, url in _NEWS_RSS_FEEDS])
    for items in batches:
        for item in items:
            blob = f"{item.get('title', '')} {item.get('body', '')}"
            if _news_text_matches_symbol(blob, keywords):
                matched.append(item)
            else:
                general.append(item)

    out = _dedup_news(matched, general, limit)
    if len(out) < limit:
        out = _dedup_news(out, general, limit)
    return out[:limit]


async def _fetch_news_kucoin_announcements(symbol: str, limit: int) -> List[Dict]:
    """KuCoin public announcements API (no auth)."""
    keywords = _symbol_news_keywords(symbol)
    page_size = min(50, max(limit * 4, 20))
    url = f"{KUCOIN_ANNOUNCEMENTS_URL}?currentPage=1&pageSize={page_size}"
    try:
        raw = await http.get(url, timeout=12)
    except Exception as exc:
        logger.warning("kucoin announcements error: %s", exc)
        return []
    if not isinstance(raw, dict) or raw.get("code") != "200000":
        return []
    data = raw.get("data") or {}
    items = data.get("items") if isinstance(data, dict) else []
    if not isinstance(items, list):
        return []

    matched: List[Dict] = []
    general: List[Dict] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        title = str(row.get("annTitle") or "").strip()
        if not title:
            continue
        ctime = row.get("cTime")
        published = ""
        if ctime is not None:
            try:
                published = datetime.fromtimestamp(int(ctime) / 1000, tz=timezone.utc).isoformat()
            except (TypeError, ValueError, OSError):
                published = str(ctime)
        item = {
            "id": str(row.get("annId") or len(matched) + len(general)),
            "title": title,
            "url": str(row.get("annUrl") or ""),
            "source": "kucoin",
            "publishedAt": published,
            "body": str(row.get("annDesc") or "")[:200],
        }
        blob = f"{title} {item['body']}"
        if _news_text_matches_symbol(blob, keywords):
            matched.append(item)
        else:
            general.append(item)

    out = _dedup_news(matched, general, limit)
    if len(out) < limit:
        out = _dedup_news(out, general, limit)
    return out[:limit]


async def _fetch_news_free_sources(symbol: str, limit: int) -> Tuple[List[Dict], List[str]]:
    """KuCoin announcements + RSS — no API keys required."""
    if limit <= 0:
        return [], []
    kucoin_task = _fetch_news_kucoin_announcements(symbol, limit)
    rss_task = _fetch_news_rss(symbol, limit)
    kucoin_res, rss_res = await asyncio.gather(kucoin_task, rss_task, return_exceptions=True)

    merged: List[Dict] = []
    sources: List[str] = []
    if isinstance(kucoin_res, list) and kucoin_res:
        merged = list(kucoin_res)
        sources.append("kucoin")
    elif isinstance(kucoin_res, Exception):
        logger.warning("kucoin announcements gather error: %s", kucoin_res)

    if isinstance(rss_res, list) and rss_res:
        merged = _dedup_news(merged, rss_res, limit)
        sources.append("rss")
    elif isinstance(rss_res, Exception):
        logger.warning("rss news gather error: %s", rss_res)

    return merged[:limit], sources


def _is_known_news_fallback_error(name: str, exc: Exception) -> bool:
    payload = getattr(exc, "payload", {})
    status = payload.get("status") if isinstance(payload, dict) else None
    return name == "cryptocurrency.cv" and status == 402


def _dedup_news(primary: List[Dict], extra: List[Dict], limit: int) -> List[Dict]:
    """Merge two news lists, dedup by title similarity, cap at limit."""
    seen = {item["title"].lower()[:60] for item in primary}
    merged = list(primary)
    for item in extra:
        if len(merged) >= limit:
            break
        key = item["title"].lower()[:60]
        if key not in seen:
            seen.add(key)
            merged.append(item)
    return merged[:limit]


async def fetch_news(symbol: str = "BTC", *, limit: int = 30, hours: int = 48) -> Tuple[List[Dict], str]:
    """
    Fetch news with web_search as primary + coins_news + HTTP fallback chain.
    web_search provides real-time results; coins_news supplements with crypto-specific news.
    Returns (news_list, source_tag).
    """
    sym = (symbol or "BTC").strip().upper()
    all_news: List[Dict] = []
    sources: List[str] = []

    mcp_enabled = _dashboard_mcp_enabled()

    # 1) web_search — real-time web results (primary source)
    if mcp_enabled:
        try:
            ws_news = await _fetch_news_via_web_search(sym, limit)
            if ws_news:
                all_news.extend(ws_news)
                sources.append("web_search")
                logger.info("web_search news ok, %d items for %s", len(ws_news), sym)
        except Exception as exc:
            logger.warning("web_search news error: %s", exc)

    # 2) coins_news MCP — crypto-specific news to supplement
    if mcp_enabled and len(all_news) < limit:
        try:
            start, end = utc_range(hours)
            result = await _call_mcp_tool("coins_news", {"symbol": sym, "startTime": start, "endTime": end})
            cn_news = _normalize_mcp_news(result, limit)
            if cn_news:
                all_news = _dedup_news(all_news, cn_news, limit)
                sources.append("coins_news")
        except Exception as exc:
            logger.warning("coins_news MCP error: %s", exc)

    # 2.5) free sources — KuCoin announcements + industry RSS (no API key)
    if len(all_news) < limit:
        try:
            free_news, free_sources = await _fetch_news_free_sources(sym, limit - len(all_news))
            if free_news:
                all_news = _dedup_news(all_news, free_news, limit)
                sources.extend(free_sources)
                logger.info("free news ok (%s), %d items for %s", "+".join(free_sources), len(free_news), sym)
        except Exception as exc:
            logger.warning("free news sources error: %s", exc)

    # 2.55) Medium / Reddit / CryptoCompare / CoinGecko Pro / LunarCrush (see news_sources_extended)
    if len(all_news) < limit:
        try:
            from web.api.news_sources_extended import fetch_extended_news_sources

            ext_news, ext_sources = await fetch_extended_news_sources(sym, limit - len(all_news))
            if ext_news:
                all_news = _dedup_news(all_news, ext_news, limit)
                sources.extend(ext_sources)
                logger.info(
                    "extended news ok (%s), %d items for %s",
                    "+".join(ext_sources),
                    len(ext_news),
                    sym,
                )
        except Exception as exc:
            logger.warning("extended news sources error: %s", exc)

    # 2.6) Tavily — only when TAVILY_API_KEY is explicitly configured
    if len(all_news) < limit and (os.environ.get("TAVILY_API_KEY") or "").strip():
        try:
            local_news = await _fetch_news_via_local_search(sym, limit - len(all_news))
            if local_news:
                all_news = _dedup_news(all_news, local_news, limit)
                sources.append("local_web_search")
                logger.info("local_web_search news ok, %d items for %s", len(local_news), sym)
        except Exception as exc:
            logger.warning("local_web_search news error: %s", exc)

    if all_news:
        return all_news, "+".join(sources)

    # 3) HTTP fallbacks (CoinGecko, cryptocurrency.cv)
    for fb_name, fb_url in _NEWS_FALLBACKS:
        try:
            news = await _fetch_news_http(fb_url, limit)
            if news:
                logger.info("news fallback (%s) ok, %d items", fb_name, len(news))
                return news, f"{fb_name}_fallback"
        except Exception as exc:
            if _is_known_news_fallback_error(fb_name, exc):
                logger.info("news fallback (%s) skipped due to provider billing requirement", fb_name)
                continue
            logger.warning("news fallback (%s) error: %s", fb_name, exc)

    return [], "none"


# ---------------------------------------------------------------------------
# On-chain / sentiment (MCP → Polymarket)
# ---------------------------------------------------------------------------
def _normalize_sentiment(result) -> Dict[str, Any]:
    summaries: List[str] = []
    extra: Dict[str, Any] = {}
    for node in _extract_json_from_mcp(result):
        if not isinstance(node, dict):
            continue
        data = node.get("data") or node.get("result") or node
        if isinstance(data, str):
            summaries.append(data)
            continue
        if not isinstance(data, dict):
            continue
        if data.get("summary"):
            summaries.append(str(data["summary"]))
        for key in ("sentiment", "fund_flows", "whale_activity", "market_sentiment", "fear_greed"):
            if data.get(key) is not None:
                extra[key] = data[key]
        # fearGreedIndex nested structure
        fgi = data.get("fearGreedIndex")
        if isinstance(fgi, dict) and "fear_greed" not in extra:
            today_val = (fgi.get("today") or {}).get("value") or {}
            if isinstance(today_val, dict) and today_val.get("score") is not None:
                extra["fear_greed"] = {
                    "value": today_val["score"],
                    "status": today_val.get("status", ""),
                    "btcPrice": today_val.get("btc"),
                }
                summaries.append(f"恐惧贪婪指数: {today_val['score']} ({today_val.get('status', '')})")
            for period, key in [("yesterday", "fear_greed_yesterday"), ("aweekAgo", "fear_greed_week_ago")]:
                pval = (fgi.get(period) or {}).get("value") or {}
                if isinstance(pval, dict) and pval.get("score") is not None:
                    extra[key] = pval["score"]
        etf = data.get("cmcEtfInflow")
        if isinstance(etf, list) and etf and "etf_inflow" not in extra:
            extra["etf_inflow"] = etf

    return {"summary": "\n".join(summaries).strip(), "extra": extra}


async def _fetch_polymarket(limit: int) -> List[Dict]:
    url = f"{POLYMARKET_API}/markets?active=true&closed=false&tag=crypto&order=volume24hr&ascending=false&limit={limit}"
    raw = await http.get(url, timeout=12)
    if not isinstance(raw, list):
        return []
    markets: List[Dict] = []
    for m in raw:
        if not isinstance(m, dict):
            continue
        try:
            prices = json.loads(m.get("outcomePrices") or "[]")
            yes_pct = round(float(prices[0]) * 100, 1) if prices else None
            no_pct = round(float(prices[1]) * 100, 1) if len(prices) > 1 else None
        except (json.JSONDecodeError, ValueError, IndexError, TypeError):
            yes_pct = no_pct = None
        markets.append({
            "question": m.get("question") or m.get("title") or "",
            "slug": m.get("slug") or "",
            "yesPct": yes_pct, "noPct": no_pct,
            "volume24hr": round(float(m.get("volume24hr") or 0)),
            "liquidity": round(float(m.get("liquidity") or 0)),
            "image": m.get("image") or "",
            "url": f"https://polymarket.com/event/{m.get('slug', '')}",
        })
    return markets


async def fetch_onchain(symbol: str = "BTC", *, limit: int = 10) -> Dict[str, Any]:
    """
    Fetch on-chain / sentiment data.
    Returns dict with keys: summary, extra, markets, source.
    """
    sym = (symbol or "BTC").strip().upper()
    summary, extra, markets = "", {}, []
    source = "market_sentiment_and_fund_flows"

    if _dashboard_mcp_enabled():
        try:
            start, end = utc_range(24)
            result = await _call_mcp_tool("market_sentiment_and_fund_flows", {"symbol": sym, "startTime": start, "endTime": end})
            parsed = _normalize_sentiment(result)
            summary, extra = parsed["summary"], parsed["extra"]
        except Exception as exc:
            logger.warning("onchain MCP error: %s", exc)
    else:
        source = "mcp_disabled_local"

    if not summary and not extra:
        try:
            markets = await _fetch_polymarket(limit)
            source = "polymarket"
        except Exception as exc:
            logger.warning("onchain Polymarket error: %s", exc)
            summary = "Web3 链上数据暂时不可用。请稍后重试。"

    return {"symbol": sym, "source": source, "summary": summary, "extra": extra, "markets": markets}


# K-line analysis is implemented in quant.market_analysis.


def _kline_analysis_from_candles(candles: List[Dict[str, Any]], *, live_merged: bool = False) -> Optional[Dict[str, Any]]:
    analysis = analyze_candles(candles)
    if not analysis:
        return None
    recent = candles[-20:] if len(candles) >= 20 else candles
    analysis["recentCandles"] = [
        {
            "o": round(c["open"], 6),
            "h": round(c["high"], 6),
            "l": round(c["low"], 6),
            "c": round(c["close"], 6),
            "v": round(c["volume"], 2),
        }
        for c in recent
    ]
    if live_merged:
        analysis["liveMerged"] = True
        analysis["liveClose"] = round(float(candles[-1]["close"]), 6)
    return analysis


async def fetch_kline_signals(
    pair: str,
    timeframes: Tuple[str, ...] = KLINE_TIMEFRAMES_SIGNAL_FULL,
    *,
    live_price: Optional[float] = None,
    merge_timeframes: Optional[Tuple[str, ...]] = None,
) -> Dict[str, Dict]:
    """Fetch and analyze K-lines for multiple timeframes. Returns {timeframe: {analysis + recent candles}}."""
    merge_set = set(merge_timeframes or ())
    signals: Dict[str, Dict] = {}
    for tf in timeframes:
        try:
            data = await kucoin_get(f"/api/v1/market/candles?symbol={pair}&type={tf}")
            raw = (data.get("data") or [])[:120]
            candles = sorted(
                [c for c in (normalize_candle(r) for r in raw) if c],
                key=lambda x: x["tsSec"],
            )
            live_merged = False
            if live_price and live_price > 0 and tf in merge_set:
                live_merged = merge_live_price_into_candles(candles, float(live_price))
            analysis = _kline_analysis_from_candles(candles, live_merged=live_merged)
            if analysis:
                signals[tf] = analysis
        except Exception as exc:
            logger.warning("kline %s/%s error: %s", pair, tf, exc)
    return signals


async def fetch_market_stats(pair: str) -> Dict[str, Any]:
    """Fetch 24h market stats from KuCoin."""
    data = await kucoin_get(f"/api/v1/market/stats?symbol={pair}")
    stats = data.get("data") or {}
    return {k: float(stats.get(k) or 0) for k in ("last", "changeRate", "changePrice", "high", "low", "vol", "volValue", "buy", "sell")}


async def fetch_derivatives_snapshot(pair: str) -> Dict[str, Any]:
    """Fetch basic futures derivatives snapshot (funding/OI/ticker) for a spot pair."""
    futures_symbol = to_contract_symbol(pair)
    if not futures_symbol:
        return {}

    funding_task = kucoin_get(f"/api/v1/funding-rate/{futures_symbol}/current", base="futures")
    oi_task = kucoin_get("/api/v1/interest/query", base="futures", params={"symbol": futures_symbol})
    ticker_task = kucoin_get(f"/api/v1/ticker?symbol={futures_symbol}", base="futures")

    funding_resp, oi_resp, ticker_resp = await asyncio.gather(
        funding_task,
        oi_task,
        ticker_task,
        return_exceptions=True,
    )

    def _to_float(val: Any) -> Optional[float]:
        try:
            if val is None or val == "":
                return None
            return float(val)
        except (TypeError, ValueError):
            return None

    funding_data = (funding_resp.get("data") or {}) if isinstance(funding_resp, dict) else {}
    oi_data = (oi_resp.get("data") or {}) if isinstance(oi_resp, dict) else {}
    ticker_data = (ticker_resp.get("data") or {}) if isinstance(ticker_resp, dict) else {}

    return {
        "symbol": pair,
        "futuresSymbol": futures_symbol,
        "fundingRate": _to_float(funding_data.get("value") or funding_data.get("fundingRate")),
        "predictedFundingRate": _to_float(
            funding_data.get("predictedValue") or funding_data.get("predictedFundingRate")
        ),
        "fundingTime": funding_data.get("timePoint") or funding_data.get("fundingTime") or "",
        "openInterest": _to_float(oi_data.get("value") or oi_data.get("openInterest")),
        "futuresLast": _to_float(ticker_data.get("price") or ticker_data.get("lastTradePrice")),
        "bestBid": _to_float(ticker_data.get("bestBidPrice")),
        "bestAsk": _to_float(ticker_data.get("bestAskPrice")),
    }


async def fetch_orderbook_snapshot(pair: str, size: int = 20) -> Dict[str, Any]:
    """Fetch public KuCoin orderbook snapshot and summarize depth/imbalance."""
    size = 100 if int(size or 20) > 20 else 20
    data = await kucoin_get(f"/api/v1/market/orderbook/level2_{size}?symbol={pair}")
    payload = data.get("data") or {}
    bids = payload.get("bids") or []
    asks = payload.get("asks") or []

    def _levels(rows: List) -> List[Dict[str, float]]:
        out: List[Dict[str, float]] = []
        for row in rows[:size]:
            try:
                price = float(row[0])
                amount = float(row[1])
                out.append({"price": price, "amount": amount, "notional": price * amount})
            except (IndexError, TypeError, ValueError):
                continue
        return out

    bid_levels = _levels(bids)
    ask_levels = _levels(asks)
    bid_notional = sum(item["notional"] for item in bid_levels)
    ask_notional = sum(item["notional"] for item in ask_levels)
    total_depth = bid_notional + ask_notional
    imbalance = (bid_notional - ask_notional) / total_depth if total_depth else 0.0
    best_bid = bid_levels[0]["price"] if bid_levels else 0.0
    best_ask = ask_levels[0]["price"] if ask_levels else 0.0
    spread = best_ask - best_bid if best_bid and best_ask else 0.0
    mid = (best_bid + best_ask) / 2 if best_bid and best_ask else 0.0

    return {
        "sequence": payload.get("sequence"),
        "bestBid": best_bid,
        "bestAsk": best_ask,
        "spread": spread,
        "spreadPct": (spread / mid * 100) if mid else 0.0,
        "bidNotional": bid_notional,
        "askNotional": ask_notional,
        "imbalance": imbalance,
        "topBids": bid_levels[:5],
        "topAsks": ask_levels[:5],
    }


async def fetch_recent_trades(pair: str, limit: int = 50) -> Dict[str, Any]:
    """Fetch public recent trades and summarize taker buy/sell pressure."""
    data = await kucoin_get(f"/api/v1/market/histories?symbol={pair}")
    rows = (data.get("data") or [])[: max(1, int(limit or 50))]
    trades: List[Dict[str, Any]] = []
    buy_notional = 0.0
    sell_notional = 0.0
    for row in rows:
        try:
            price = float(row.get("price") or 0)
            size_value = float(row.get("size") or 0)
            side = str(row.get("side") or "").lower()
            notional = price * size_value
            if side == "buy":
                buy_notional += notional
            elif side == "sell":
                sell_notional += notional
            trades.append({
                "time": row.get("time"),
                "side": side,
                "price": price,
                "size": size_value,
                "notional": notional,
            })
        except (TypeError, ValueError):
            continue
    total = buy_notional + sell_notional
    return {
        "count": len(trades),
        "buyNotional": buy_notional,
        "sellNotional": sell_notional,
        "buyRatio": buy_notional / total if total else 0.0,
        "recent": trades[:10],
    }


# ---------------------------------------------------------------------------
# Ticker helpers (used by market/tickers endpoint)
# ---------------------------------------------------------------------------
def normalize_tickers(raw_tickers: List, quote: str, search: str = "", limit: int = 300) -> List[Dict]:
    q = (quote or "USDT").upper()
    s = (search or "").strip().upper()
    out = []
    for item in raw_tickers or []:
        if not isinstance(item, dict) or not item.get("symbol", "").endswith(f"-{q}"):
            continue
        if s and s not in (item.get("symbol") or "").upper():
            continue
        out.append({k: float(item.get(k) or 0) for k in ("last", "changeRate", "changePrice", "high", "low", "vol", "volValue")} | {"symbol": item.get("symbol", "")})
    out.sort(key=lambda x: x["volValue"], reverse=True)
    return out[:limit]


def to_contract_symbol(spot_symbol: str) -> str:
    s = (spot_symbol or "").strip().upper()
    if "-" not in s:
        return ""
    base, quote = s.split("-", 1)
    return f"{'XBT' if base == 'BTC' else base}{quote}M"


# ---------------------------------------------------------------------------
# On-chain metrics (BTC-focused, free APIs, no auth required)
# ---------------------------------------------------------------------------
async def fetch_blockchain_stats() -> Dict[str, Any]:
    """Fetch BTC network stats from blockchain.info/stats."""
    try:
        data = await http.get(f"{BLOCKCHAIN_INFO_API}/stats", timeout=10)
        if not isinstance(data, dict):
            return {}
        return {
            "hashRate": data.get("hash_rate", 0),
            "difficulty": data.get("difficulty", 0),
            "blockHeight": data.get("n_blocks_total", 0),
            "totalBtcSent": data.get("total_btc_sent", 0),
            "estimatedBtcSent": data.get("estimated_btc_sent", 0),
            "nTx": data.get("n_tx", 0),
            "nBlocks": data.get("n_blocks_mined", 0),
            "minutesBetweenBlocks": data.get("minutes_between_blocks", 0),
            "marketPriceUsd": data.get("market_price_usd", 0),
            "totalFeesBtc": data.get("total_fees_btc", 0),
            "minerRevenueBtc": data.get("miners_revenue_btc", 0),
            "tradeVolumeUsd": data.get("trade_volume_usd", 0),
        }
    except Exception as exc:
        logger.warning("blockchain.info stats error: %s", exc)
        return {}


async def fetch_mempool_stats() -> Dict[str, Any]:
    """Fetch mempool info and fee rates from mempool.space."""
    result: Dict[str, Any] = {}
    default_timeout = 2 if os.environ.get("serverEnv") == "local" else 8
    timeout = float(os.environ.get("DASHBOARD_MEMPOOL_TIMEOUT_SECONDS", default_timeout))

    async def _get(path: str) -> Any:
        return await http.get(f"{MEMPOOL_SPACE_API}{path}", timeout=timeout, retries=0)

    fees, mempool, diff = await asyncio.gather(
        _get("/v1/fees/recommended"),
        _get("/mempool"),
        _get("/v1/difficulty-adjustment"),
        return_exceptions=True,
    )

    if isinstance(fees, Exception):
        logger.warning("mempool.space fees error: %s", fees)
        fees = None
    if isinstance(mempool, Exception):
        logger.warning("mempool.space mempool error: %s", mempool)
        mempool = None
    if isinstance(diff, Exception):
        logger.warning("mempool.space difficulty error: %s", diff)
        diff = None

    if isinstance(fees, dict):
        result["fees"] = {
            "fastest": fees.get("fastestFee", 0),
            "halfHour": fees.get("halfHourFee", 0),
            "hour": fees.get("hourFee", 0),
            "economy": fees.get("economyFee", 0),
            "minimum": fees.get("minimumFee", 0),
        }
    if isinstance(mempool, dict):
        result["mempool"] = {
            "count": mempool.get("count", 0),
            "vsize": mempool.get("vsize", 0),
            "totalFee": mempool.get("total_fee", 0),
        }
    if isinstance(diff, dict):
        result["difficulty"] = {
            "progressPercent": diff.get("progressPercent", 0),
            "difficultyChange": diff.get("difficultyChange", 0),
            "estimatedRetargetDate": diff.get("estimatedRetargetDate", 0),
            "remainingBlocks": diff.get("remainingBlocks", 0),
            "remainingTime": diff.get("remainingTime", 0),
        }

    return result


async def fetch_fear_greed_index() -> Dict[str, Any]:
    """Fetch Fear & Greed Index from alternative.me (today + yesterday)."""
    try:
        data = await http.get(f"{FEAR_GREED_API}?limit=2&format=json", timeout=8)
        if not isinstance(data, dict):
            return {}
        items = data.get("data") or []
        if not items:
            return {}
        today = items[0] if len(items) >= 1 else {}
        yesterday = items[1] if len(items) >= 2 else {}
        value = int(today.get("value", 50))
        label = today.get("value_classification", "")
        yesterday_val = int(yesterday.get("value", 0)) if yesterday else None
        return {
            "value": value,
            "label": label,
            "yesterday": yesterday_val,
            "change": value - yesterday_val if yesterday_val is not None else None,
            "timestamp": today.get("timestamp"),
        }
    except Exception as exc:
        logger.warning("fear_greed API error: %s", exc)
        return {}


async def _fetch_bc_chart_latest(chart_name: str, timespan: str = "1days") -> Optional[float]:
    """Fetch the latest value from a blockchain.info chart endpoint."""
    try:
        data = await http.get(
            f"{BLOCKCHAIN_INFO_API}/charts/{chart_name}?timespan={timespan}&format=json",
            timeout=10,
        )
        if isinstance(data, dict):
            values = data.get("values") or []
            if values:
                return float(values[-1].get("y", 0))
    except Exception as exc:
        logger.debug("blockchain chart %s error: %s", chart_name, exc)
    return None


COINGECKO_API = os.environ.get("COINGECKO_API", "https://api.coingecko.com/api/v3")


async def fetch_valuation_metrics(symbol: str = "BTC") -> Dict[str, Any]:
    """
    Fetch on-chain valuation metrics from free APIs (blockchain.info + CoinGecko).
    Replaces Messari (now requires auth) with equivalent free data sources.
    """
    if symbol.upper() not in ("BTC", "BITCOIN"):
        return {}

    result: Dict[str, Any] = {}

    async def _get_chart(name: str, ts: str = "1days"):
        return await _fetch_bc_chart_latest(name, ts)

    try:
        active_addr, tx_vol, market_cap, miners_rev = await asyncio.gather(
            _get_chart("n-unique-addresses"),
            _get_chart("estimated-transaction-volume-usd"),
            _get_chart("market-cap"),
            _get_chart("miners-revenue"),
            return_exceptions=True,
        )

        if isinstance(active_addr, (int, float)) and active_addr > 0:
            result["activeAddresses"] = int(active_addr)
        if isinstance(tx_vol, (int, float)) and tx_vol > 0:
            result["txVolume24h"] = float(tx_vol)
        if isinstance(market_cap, (int, float)) and market_cap > 0:
            result["marketCap"] = float(market_cap)
            if isinstance(tx_vol, (int, float)) and tx_vol > 0:
                result["nvt"] = round(float(market_cap) / float(tx_vol), 2)
        if isinstance(miners_rev, (int, float)) and miners_rev > 0:
            result["miningRevenueUsd"] = float(miners_rev)
    except Exception as exc:
        logger.warning("blockchain.info charts error: %s", exc)

    try:
        cg_data = await http.get(
            f"{COINGECKO_API}/coins/bitcoin"
            "?localization=false&tickers=false&community_data=false"
            "&developer_data=false&sparkline=false",
            timeout=10,
        )
        if isinstance(cg_data, dict):
            md = cg_data.get("market_data") or {}
            if md.get("circulating_supply"):
                result["circulatingSupply"] = float(md["circulating_supply"])
            if md.get("total_supply"):
                result["totalSupply"] = float(md["total_supply"])
            mcap = (md.get("market_cap") or {}).get("usd")
            if mcap and not result.get("marketCap"):
                result["marketCap"] = float(mcap)
    except Exception as exc:
        logger.warning("coingecko coin data error: %s", exc)

    return result


async def fetch_blockchain_chart(chart_name: str, timespan: str = "30days") -> List[Dict]:
    """
    Fetch a specific chart from blockchain.info (e.g. n-unique-addresses, hash-rate).
    Returns list of {x: timestamp, y: value}.
    """
    try:
        url = f"{BLOCKCHAIN_INFO_API}/charts/{chart_name}?timespan={timespan}&format=json"
        data = await http.get(url, timeout=10)
        if not isinstance(data, dict):
            return []
        values = data.get("values") or []
        return [{"x": v.get("x", 0), "y": v.get("y", 0)} for v in values if isinstance(v, dict)]
    except Exception as exc:
        logger.warning("blockchain.info chart %s error: %s", chart_name, exc)
        return []


async def fetch_onchain_metrics(symbol: str = "BTC") -> Dict[str, Any]:
    """
    Aggregate on-chain metrics from multiple free APIs.
    BTC gets full coverage from blockchain.info + CoinGecko + mempool.space.
    """
    sym = (symbol or "BTC").strip().upper()
    metrics: Dict[str, Any] = {"symbol": sym}

    fear_greed = await fetch_fear_greed_index()
    if fear_greed:
        metrics["fearGreed"] = fear_greed

    valuation = await fetch_valuation_metrics(sym)
    if valuation:
        metrics["messari"] = valuation

    if sym == "BTC":
        blockchain = await fetch_blockchain_stats()
        if blockchain:
            metrics["network"] = blockchain

        mempool = await fetch_mempool_stats()
        if mempool.get("fees"):
            metrics["fees"] = mempool["fees"]
        if mempool.get("mempool"):
            metrics["mempool"] = mempool["mempool"]
        if mempool.get("difficulty"):
            metrics["difficultyAdj"] = mempool["difficulty"]

        active_addr_chart = await fetch_blockchain_chart("n-unique-addresses", "30days")
        if active_addr_chart:
            metrics["activeAddrTrend"] = active_addr_chart[-7:]

    return metrics


# ---------------------------------------------------------------------------
# ValueScan data for signal analysis (consolidated fetch)
# ---------------------------------------------------------------------------
async def fetch_valuescan_signal_data(symbol: str = "BTC") -> Dict[str, Any]:
    """
    为「综合 / LLM 信号」拉取 ValueScan 全量数据（REST + 可选 SSE 短读）。
    实现见 ``valuescan_service.fetch_full_token_data``；下游对文本做截断。
    """
    from web.api import valuescan_service as vs

    try:
        return await vs.fetch_full_token_data(symbol)
    except Exception as exc:
        logger.warning("VS full fetch error for %s: %s", symbol, exc)
        return {"symbol": (symbol or "BTC").strip().upper()}
