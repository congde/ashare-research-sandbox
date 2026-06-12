# -*- coding: utf-8 -*-
"""
Extended crypto news / social sources (optional API keys).

Free (no key): Medium tag RSS, Reddit JSON (may be blocked on some networks).
Keyed: CryptoCompare news, CoinGecko Pro news, LunarCrush topic news/posts (X-like social).
Direct X/Twitter API is not integrated — use LunarCrush posts or Tavily/MCP web_search.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import xml.etree.ElementTree as ET
from html import unescape
from typing import Any, Dict, List, Tuple

from libs import http

logger = logging.getLogger(__name__)

_REDDIT_UA = os.environ.get(
    "REDDIT_USER_AGENT",
    "ai-web3-trading-agent/1.0 (crypto news aggregator)",
)

CRYPTOCOMPARE_API_KEY = (os.environ.get("CRYPTOCOMPARE_API_KEY") or "").strip()
CRYPTOCOMPARE_NEWS_URL = os.environ.get(
    "CRYPTOCOMPARE_NEWS_URL",
    "https://min-api.cryptocompare.com/data/v2/news/",
)
COINGECKO_API_KEY = (os.environ.get("COINGECKO_API_KEY") or os.environ.get("COINGECKO_PRO_API_KEY") or "").strip()
COINGECKO_NEWS_URL = os.environ.get("COINGECKO_NEWS_URL", "https://api.coingecko.com/api/v3/news")
LUNARCRUSH_API_KEY = (os.environ.get("LUNARCRUSH_API_KEY") or "").strip()
LUNARCRUSH_API_BASE = os.environ.get("LUNARCRUSH_API_BASE", "https://lunarcrush.com/api4").rstrip("/")

_REDDIT_SUBS: Tuple[str, ...] = ("CryptoCurrency", "Bitcoin", "Ethereum")
_MEDIUM_TAG_BY_SYMBOL: Dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binance-coin",
    "XRP": "ripple",
    "DOGE": "dogecoin",
    "ADA": "cardano",
    "DOT": "polkadot",
    "AVAX": "avalanche",
    "LINK": "chainlink",
    "MATIC": "polygon",
    "POL": "polygon",
    "LTC": "litecoin",
}
_LUNARCRUSH_TOPIC_BY_SYMBOL: Dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "bnb",
    "XRP": "xrp",
    "DOGE": "dogecoin",
    "ADA": "cardano",
    "DOT": "polkadot",
    "AVAX": "avalanche",
    "LINK": "chainlink",
    "MATIC": "polygon",
    "POL": "polygon",
    "LTC": "litecoin",
}


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", unescape(text or "")).strip()


def _rss_child_text(parent: ET.Element, name: str) -> str:
    for child in parent:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if tag == name:
            return (child.text or "").strip()
    return ""


def _parse_rss(xml_text: str, source: str, limit: int) -> List[Dict[str, Any]]:
    if not (xml_text or "").strip():
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("rss parse error (%s): %s", source, exc)
        return []
    out: List[Dict[str, Any]] = []
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag != "item":
            continue
        title = _rss_child_text(elem, "title")
        if not title:
            continue
        out.append({
            "id": str(len(out)),
            "title": title,
            "url": _rss_child_text(elem, "link"),
            "source": source,
            "publishedAt": _rss_child_text(elem, "pubDate") or _rss_child_text(elem, "published"),
            "body": _strip_html(_rss_child_text(elem, "description"))[:200],
        })
        if len(out) >= limit:
            break
    return out


def _normalize_row(
    *,
    title: str,
    url: str = "",
    source: str,
    published: str = "",
    body: str = "",
    item_id: str = "",
) -> Dict[str, Any]:
    return {
        "id": item_id or title[:40],
        "title": (title or "").strip() or "无标题",
        "url": url,
        "source": source,
        "publishedAt": published,
        "body": (body or "")[:200],
    }


def _dedup(primary: List[Dict], extra: List[Dict], limit: int) -> List[Dict]:
    seen = {str(item.get("title", "")).lower()[:60] for item in primary}
    merged = list(primary)
    for item in extra:
        if len(merged) >= limit:
            break
        key = str(item.get("title", "")).lower()[:60]
        if key and key not in seen:
            seen.add(key)
            merged.append(item)
    return merged[:limit]


def _lunarcrush_topic(symbol: str) -> str:
    sym = (symbol or "BTC").strip().upper()
    if sym in _LUNARCRUSH_TOPIC_BY_SYMBOL:
        return _LUNARCRUSH_TOPIC_BY_SYMBOL[sym]
    return sym.lower()


def _medium_tag(symbol: str) -> str:
    sym = (symbol or "BTC").strip().upper()
    if sym in _MEDIUM_TAG_BY_SYMBOL:
        return _MEDIUM_TAG_BY_SYMBOL[sym]
    return sym.lower()


async def _fetch_medium_rss(symbol: str, limit: int) -> List[Dict[str, Any]]:
    tag = _medium_tag(symbol)
    url = f"https://medium.com/feed/tag/{tag}"
    try:
        raw = await http.get(url, timeout=12)
        if not isinstance(raw, str):
            return []
        return _parse_rss(raw, "medium", limit)
    except Exception as exc:
        logger.warning("medium rss (%s) error: %s", tag, exc)
        return []


async def _fetch_reddit_sub(sub: str, limit: int) -> List[Dict[str, Any]]:
    url = f"https://www.reddit.com/r/{sub}/hot.json?limit={min(limit, 25)}"
    headers = {"User-Agent": _REDDIT_UA, "Accept": "application/json"}
    try:
        raw = await http.get(url, timeout=12, headers=headers)
    except Exception as exc:
        logger.warning("reddit r/%s error: %s", sub, exc)
        return []
    if not isinstance(raw, dict):
        return []
    children = ((raw.get("data") or {}).get("children")) or []
    out: List[Dict[str, Any]] = []
    for row in children:
        if not isinstance(row, dict):
            continue
        data = row.get("data") or {}
        if not isinstance(data, dict):
            continue
        title = str(data.get("title") or "").strip()
        if not title:
            continue
        permalink = str(data.get("permalink") or "")
        link = f"https://www.reddit.com{permalink}" if permalink.startswith("/") else permalink
        created = data.get("created_utc")
        published = ""
        if created is not None:
            try:
                from datetime import datetime, timezone
                published = datetime.fromtimestamp(float(created), tz=timezone.utc).isoformat()
            except (TypeError, ValueError, OSError):
                published = str(created)
        out.append(_normalize_row(
            title=title,
            url=link,
            source=f"reddit_{sub.lower()}",
            published=published,
            body=str(data.get("selftext") or "")[:200],
            item_id=str(data.get("id") or len(out)),
        ))
        if len(out) >= limit:
            break
    return out


async def fetch_reddit_news(symbol: str, limit: int) -> List[Dict[str, Any]]:
    per_sub = max(3, limit // len(_REDDIT_SUBS))
    batches = await asyncio.gather(
        *[_fetch_reddit_sub(sub, per_sub) for sub in _REDDIT_SUBS],
        return_exceptions=True,
    )
    merged: List[Dict[str, Any]] = []
    for batch in batches:
        if isinstance(batch, list):
            merged = _dedup(merged, batch, limit)
    return merged[:limit]


async def fetch_cryptocompare_news(symbol: str, limit: int) -> List[Dict[str, Any]]:
    if not CRYPTOCOMPARE_API_KEY:
        return []
    sym = (symbol or "BTC").strip().upper()
    url = (
        f"{CRYPTOCOMPARE_NEWS_URL.rstrip('/')}/"
        f"?lang=EN&categories={sym}&api_key={CRYPTOCOMPARE_API_KEY}"
    )
    try:
        raw = await http.get(url, timeout=12)
    except Exception as exc:
        logger.warning("cryptocompare news error: %s", exc)
        return []
    if not isinstance(raw, dict):
        return []
    data = raw.get("Data") or raw.get("data") or []
    if not isinstance(data, list):
        return []
    out: List[Dict[str, Any]] = []
    for row in data[:limit]:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        src = row.get("source_info") or {}
        source_name = "cryptocompare"
        if isinstance(src, dict):
            source_name = str(src.get("name") or source_name)
        out.append(_normalize_row(
            title=title,
            url=str(row.get("url") or row.get("guid") or ""),
            source=source_name,
            published=str(row.get("published_on") or row.get("published_at") or ""),
            body=str(row.get("body") or "")[:200],
            item_id=str(row.get("id") or len(out)),
        ))
    return out


async def fetch_coingecko_pro_news(limit: int) -> List[Dict[str, Any]]:
    if not COINGECKO_API_KEY:
        return []
    url = COINGECKO_NEWS_URL + ("&" if "?" in COINGECKO_NEWS_URL else "?") + "page=1"
    headers = {"x-cg-pro-api-key": COINGECKO_API_KEY, "accept": "application/json"}
    try:
        raw = await http.get(url, timeout=12, headers=headers)
    except Exception as exc:
        logger.warning("coingecko pro news error: %s", exc)
        return []
    items = []
    if isinstance(raw, dict):
        items = raw.get("data") or raw.get("articles") or raw.get("news") or []
    elif isinstance(raw, list):
        items = raw
    if not isinstance(items, list):
        return []
    out: List[Dict[str, Any]] = []
    for row in items[:limit]:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or row.get("name") or "").strip()
        if not title:
            continue
        out.append(_normalize_row(
            title=title,
            url=str(row.get("url") or row.get("news_url") or row.get("link") or ""),
            source=str(row.get("news_site") or row.get("source") or "coingecko"),
            published=str(row.get("updated_at") or row.get("published_at") or ""),
            body=str(row.get("description") or row.get("content") or "")[:200],
            item_id=str(row.get("id") or len(out)),
        ))
    return out


def _parse_lunarcrush_posts(payload: Any, source: str, limit: int) -> List[Dict[str, Any]]:
    rows = []
    if isinstance(payload, dict):
        rows = payload.get("data") or payload.get("posts") or []
    if not isinstance(rows, list):
        return []
    out: List[Dict[str, Any]] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        title = str(row.get("post_title") or row.get("title") or row.get("text") or "").strip()
        if not title:
            title = str(row.get("post_type") or "social post").strip()
        url = str(row.get("post_link") or row.get("url") or row.get("link") or "")
        network = str(row.get("network") or row.get("type") or "social")
        out.append(_normalize_row(
            title=title[:240],
            url=url,
            source=f"lunarcrush_{network.lower()}",
            published=str(row.get("post_created") or row.get("time") or ""),
            body=str(row.get("post_text") or row.get("text") or "")[:200],
            item_id=str(row.get("id") or len(out)),
        ))
        if len(out) >= limit:
            break
    return out


def _parse_lunarcrush_news(payload: Any, limit: int) -> List[Dict[str, Any]]:
    rows = []
    if isinstance(payload, dict):
        rows = payload.get("data") or payload.get("news") or []
    if not isinstance(rows, list):
        return []
    out: List[Dict[str, Any]] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or row.get("post_title") or "").strip()
        if not title:
            continue
        out.append(_normalize_row(
            title=title,
            url=str(row.get("url") or row.get("post_link") or ""),
            source="lunarcrush_news",
            published=str(row.get("time") or row.get("post_created") or ""),
            body=str(row.get("text") or row.get("post_text") or "")[:200],
            item_id=str(row.get("id") or len(out)),
        ))
    return out


async def _lunarcrush_get(path: str) -> Any:
    url = f"{LUNARCRUSH_API_BASE}{path}"
    headers = {"Authorization": f"Bearer {LUNARCRUSH_API_KEY}"}
    return await http.get(url, timeout=15, headers=headers)


async def fetch_lunarcrush_news(symbol: str, limit: int) -> List[Dict[str, Any]]:
    if not LUNARCRUSH_API_KEY:
        return []
    topic = _lunarcrush_topic(symbol)
    try:
        raw = await _lunarcrush_get(f"/public/topic/{topic}/news/v1")
        return _parse_lunarcrush_news(raw, limit)
    except Exception as exc:
        logger.warning("lunarcrush news (%s) error: %s", topic, exc)
        return []


async def fetch_lunarcrush_social(symbol: str, limit: int) -> List[Dict[str, Any]]:
    """Social posts (often includes X/Twitter) via LunarCrush."""
    if not LUNARCRUSH_API_KEY:
        return []
    topic = _lunarcrush_topic(symbol)
    try:
        raw = await _lunarcrush_get(f"/public/topic/{topic}/posts/v1")
        return _parse_lunarcrush_posts(raw, "lunarcrush", limit)
    except Exception as exc:
        logger.warning("lunarcrush posts (%s) error: %s", topic, exc)
        return []


async def fetch_extended_news_sources(
    symbol: str,
    limit: int,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Aggregate Medium, Reddit, and optional keyed APIs.
    Returns (items, source_tags).
    """
    if limit <= 0:
        return [], []

    tasks: List[Tuple[str, Any]] = [
        ("medium", _fetch_medium_rss(symbol, limit)),
        ("reddit", fetch_reddit_news(symbol, limit)),
    ]
    if CRYPTOCOMPARE_API_KEY:
        tasks.append(("cryptocompare", fetch_cryptocompare_news(symbol, limit)))
    if COINGECKO_API_KEY:
        tasks.append(("coingecko", fetch_coingecko_pro_news(limit)))
    if LUNARCRUSH_API_KEY:
        tasks.append(("lunarcrush_news", fetch_lunarcrush_news(symbol, limit)))
        tasks.append(("lunarcrush_social", fetch_lunarcrush_social(symbol, limit)))

    names = [t[0] for t in tasks]
    results = await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)

    merged: List[Dict[str, Any]] = []
    sources: List[str] = []
    for name, res in zip(names, results):
        if isinstance(res, Exception):
            logger.warning("extended news %s error: %s", name, res)
            continue
        if res:
            merged = _dedup(merged, res, limit)
            sources.append(name)

    return merged[:limit], sources
