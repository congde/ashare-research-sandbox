from __future__ import annotations

import email.utils
import os
import re
from datetime import datetime, timezone
from html import unescape
from typing import Any
from urllib.parse import quote_plus
from xml.etree import ElementTree

from dashboard.http_client import http_get, http_get_text

WEB3_RSS_FEEDS: tuple[dict[str, str], ...] = (
    {"id": "cointelegraph", "name": "Cointelegraph", "url": "https://cointelegraph.com/rss", "category": "news"},
    {"id": "theblock", "name": "The Block", "url": "https://www.theblock.co/rss.xml", "category": "news"},
    {"id": "decrypt", "name": "Decrypt", "url": "https://decrypt.co/feed", "category": "news"},
    {"id": "cryptoslate", "name": "CryptoSlate", "url": "https://cryptoslate.com/feed/", "category": "news"},
    {"id": "cryptopolitan", "name": "Cryptopolitan", "url": "https://www.cryptopolitan.com/feed/", "category": "news"},
    {"id": "bitcoinmagazine", "name": "Bitcoin Magazine", "url": "https://bitcoinmagazine.com/feed", "category": "news"},
    {"id": "beincrypto", "name": "BeInCrypto", "url": "https://beincrypto.com/feed/", "category": "news"},
    {
        "id": "ethereum-foundation",
        "name": "Ethereum Foundation",
        "url": "https://blog.ethereum.org/feed.xml",
        "category": "protocol",
    },
)
GDELT_DOC_API = os.environ.get("GDELT_DOC_API", "https://api.gdeltproject.org/api/v2/doc/doc")

ASSET_KEYWORDS = {
    "BTC": ("bitcoin", "btc", "spot bitcoin", "bitcoin etf"),
    "ETH": ("ethereum", "eth", "ether", "staking"),
    "SOL": ("solana", "sol"),
    "BNB": ("bnb", "binance"),
    "XRP": ("xrp", "ripple"),
    "USDT": ("tether", "usdt"),
    "USDC": ("usdc", "circle"),
}
TOPIC_KEYWORDS = {
    "ETF": ("etf",),
    "DeFi": ("defi", "dex", "liquidity pool", "lending protocol"),
    "Stablecoin": ("stablecoin", "usdt", "usdc", "tether", "circle"),
    "Security": ("hack", "exploit", "breach", "stolen", "vulnerability", "rug pull"),
    "Regulation": ("sec", "cftc", "lawsuit", "regulation", "regulator", "compliance"),
    "Airdrop": ("airdrop", "points program", "token launch"),
    "Layer2": ("layer 2", "l2", "rollup", "optimism", "arbitrum", "base"),
    "NFT": ("nft", "ordinals"),
}
POSITIVE_TERMS = (
    "approval",
    "approve",
    "surge",
    "rally",
    "record",
    "inflow",
    "partnership",
    "launch",
    "growth",
    "adoption",
    "upgrade",
)
NEGATIVE_TERMS = (
    "hack",
    "exploit",
    "lawsuit",
    "probe",
    "ban",
    "delist",
    "stolen",
    "outflow",
    "crash",
    "insolvency",
    "breach",
)


def refresh_bases() -> None:
    global GDELT_DOC_API
    GDELT_DOC_API = os.environ.get("GDELT_DOC_API", "https://api.gdeltproject.org/api/v2/doc/doc")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", unescape(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def _parse_time(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    except (TypeError, ValueError):
        return value


def _node_text(node: ElementTree.Element, name: str) -> str:
    found = node.find(name)
    return found.text.strip() if found is not None and found.text else ""


def parse_rss_feed(xml_text: str, *, source_id: str, source_name: str, limit: int = 20) -> list[dict[str, Any]]:
    root = ElementTree.fromstring(xml_text)
    rows: list[dict[str, Any]] = []
    for item in root.findall("./channel/item")[:limit]:
        title = _strip_html(_node_text(item, "title"))
        if not title:
            continue
        rows.append(
                {
                    "source": source_name,
                    "source_id": source_id,
                "title": title,
                "url": _node_text(item, "link"),
                "published_at": _parse_time(_node_text(item, "pubDate")),
                    "summary": _strip_html(_node_text(item, "description"))[:320],
                }
            )
    for item in root.findall("{http://www.w3.org/2005/Atom}entry")[:limit]:
        title = _strip_html(_node_text(item, "{http://www.w3.org/2005/Atom}title"))
        if not title:
            continue
        link_node = item.find("{http://www.w3.org/2005/Atom}link")
        rows.append(
                {
                    "source": source_name,
                    "source_id": source_id,
                "title": title,
                "url": link_node.attrib.get("href", "") if link_node is not None else "",
                "published_at": _parse_time(_node_text(item, "{http://www.w3.org/2005/Atom}updated")),
                "summary": _strip_html(_node_text(item, "{http://www.w3.org/2005/Atom}summary"))[:320],
            }
        )
    return rows


def _score_item(item: dict[str, Any], watch_symbols: list[str]) -> dict[str, Any]:
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    assets = [
        symbol
        for symbol, terms in ASSET_KEYWORDS.items()
        if (not watch_symbols or symbol in watch_symbols) and any(term in text for term in terms)
    ]
    topics = [topic for topic, terms in TOPIC_KEYWORDS.items() if any(term in text for term in terms)]
    positive = sum(1 for term in POSITIVE_TERMS if term in text)
    negative = sum(1 for term in NEGATIVE_TERMS if term in text)
    enriched = dict(item)
    enriched["assets"] = assets
    enriched["topics"] = topics
    enriched["sentiment"] = max(-3, min(3, positive - negative))
    enriched["risk_event"] = bool({"Security", "Regulation"} & set(topics)) or negative >= 2
    return enriched


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        key = str(item.get("url") or item.get("title") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def fetch_rss_news(*, per_source: int = 12) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    headers = {"User-Agent": "web3-quant-sandbox/1.0"}
    for feed in WEB3_RSS_FEEDS:
        try:
            parsed = parse_rss_feed(
                http_get_text(feed["url"], headers=headers, timeout=12),
                source_id=feed["id"],
                source_name=feed["name"],
                limit=per_source,
            )
            for row in parsed:
                row["source_category"] = feed.get("category", "news")
            rows.extend(parsed)
            sources.append({**feed, "ok": True, "count": len(parsed)})
        except Exception as exc:
            sources.append({**feed, "ok": False, "error": str(exc)})
    return rows, sources


def fetch_gdelt_news(*, query: str, limit: int = 20) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    refresh_bases()
    params = (
        f"query={quote_plus(query)}&mode=artlist&format=json&maxrecords={max(1, min(50, limit))}"
        "&sort=hybridrel"
    )
    url = f"{GDELT_DOC_API}?{params}"
    data = http_get(url, headers={"User-Agent": "web3-quant-sandbox/1.0"}, timeout=15)
    rows: list[dict[str, Any]] = []
    articles = data.get("articles") if isinstance(data, dict) else []
    if isinstance(articles, list):
        for item in articles[:limit]:
            if not isinstance(item, dict):
                continue
            title = _strip_html(str(item.get("title") or ""))
            if title:
                rows.append(
                    {
                        "source": "GDELT",
                        "source_id": "gdelt",
                        "title": title,
                        "url": str(item.get("url") or ""),
                        "published_at": _parse_time(str(item.get("seendate") or "")),
                        "summary": _strip_html(str(item.get("domain") or "")),
                    }
                )
    return rows, {"id": "gdelt", "name": "GDELT", "url": url, "ok": True, "count": len(rows)}


def build_web3_news_signal(
    items: list[dict[str, Any]],
    *,
    watch_symbols: list[str] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    symbols = [item.strip().upper().replace("-USDT", "") for item in (watch_symbols or []) if item.strip()]
    enriched = [_score_item(item, symbols) for item in _dedupe(items)]
    enriched.sort(key=lambda item: str(item.get("published_at") or ""), reverse=True)
    clipped = enriched[: max(1, limit)]
    topic_counts: dict[str, int] = {}
    asset_counts: dict[str, int] = {}
    for item in clipped:
        for topic in item.get("topics") or []:
            topic_counts[topic] = topic_counts.get(topic, 0) + 1
        for asset in item.get("assets") or []:
            asset_counts[asset] = asset_counts.get(asset, 0) + 1
    total = len(clipped)
    positive = sum(1 for item in clipped if item.get("sentiment", 0) > 0)
    negative = sum(1 for item in clipped if item.get("sentiment", 0) < 0)
    risk_count = sum(1 for item in clipped if item.get("risk_event"))
    sentiment_score = sum(float(item.get("sentiment") or 0) for item in clipped) / total if total else 0.0
    source_breadth = len({str(item.get("source_id") or item.get("source") or "") for item in clipped})
    return {
        "items": clipped,
        "metrics": {
            "article_count": total,
            "positive_count": positive,
            "negative_count": negative,
            "risk_event_count": risk_count,
            "positive_ratio": round(positive / total, 4) if total else 0.0,
            "sentiment_score": round(sentiment_score, 4),
            "top_topics": sorted(topic_counts.items(), key=lambda pair: pair[1], reverse=True)[:8],
            "top_assets": sorted(asset_counts.items(), key=lambda pair: pair[1], reverse=True)[:8],
            "source_breadth": source_breadth,
        },
        "factor_signals": {
            "news_heat_24h": total,
            "risk_event_count_24h": risk_count,
            "positive_news_ratio_24h": round(positive / total, 4) if total else 0.0,
            "asset_mention_count_24h": asset_counts,
            "source_breadth_24h": source_breadth,
        },
    }


def fetch_web3_news(
    *,
    watch_symbols: list[str] | None = None,
    limit: int = 50,
    include_gdelt: bool = True,
) -> dict[str, Any]:
    rss_rows, sources = fetch_rss_news()
    gdelt_rows: list[dict[str, Any]] = []
    if include_gdelt:
        try:
            gdelt_rows, gdelt_source = fetch_gdelt_news(
                query="(bitcoin OR ethereum OR solana OR defi OR web3 OR stablecoin OR crypto hack)",
                limit=20,
            )
            sources.append(gdelt_source)
        except Exception as exc:
            sources.append({"id": "gdelt", "name": "GDELT", "ok": False, "error": str(exc)})
    signal = build_web3_news_signal([*rss_rows, *gdelt_rows], watch_symbols=watch_symbols, limit=limit)
    return {
        "ok": True,
        "source": "live",
        "updated_at": _now_iso(),
        "sources": sources,
        **signal,
    }
