from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

from dashboard.http_client import http_get

FEAR_GREED_API = os.environ.get(
    "FEAR_GREED_API",
    "https://api.alternative.me/fng/",
)
KUCOIN_API_BASE = os.environ.get("KUCOIN_PUBLIC_API_BASE", "https://api.kucoin.com").rstrip("/")


def refresh_bases() -> None:
    global FEAR_GREED_API, KUCOIN_API_BASE
    FEAR_GREED_API = os.environ.get("FEAR_GREED_API", "https://api.alternative.me/fng/")
    KUCOIN_API_BASE = os.environ.get("KUCOIN_PUBLIC_API_BASE", "https://api.kucoin.com").rstrip("/")


def normalize_candle(row: list[Any]) -> dict[str, Any] | None:
    if not row or len(row) < 6:
        return None
    try:
        ts_sec = int(float(row[0]))
        return {
            "tsSec": ts_sec,
            "date": _ts_to_date(ts_sec),
            "open": float(row[1]),
            "close": float(row[2]),
            "high": float(row[3]),
            "low": float(row[4]),
            "volume": float(row[5]),
        }
    except (IndexError, ValueError, TypeError):
        return None


def _ts_to_date(ts_sec: int) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(ts_sec, tz=timezone.utc).strftime("%Y-%m-%d")


def fetch_fear_greed_index() -> dict[str, Any]:
    refresh_bases()
    try:
        data = http_get(f"{FEAR_GREED_API}?limit=2&format=json", timeout=8)
        items = (data or {}).get("data") or []
        if not items:
            return {}
        today = items[0]
        yesterday = items[1] if len(items) > 1 else {}
        value = int(today.get("value", 50))
        yesterday_val = int(yesterday.get("value", 0)) if yesterday else None
        return {
            "value": value,
            "label": today.get("value_classification", ""),
            "yesterday": yesterday_val,
            "change": value - yesterday_val if yesterday_val is not None else None,
            "timestamp": today.get("timestamp"),
        }
    except RuntimeError:
        return {}


def fetch_onchain(symbol: str = "BTC", *, limit: int = 1) -> dict[str, Any]:
    refresh_bases()
    _ = limit
    fear = fetch_fear_greed_index()
    return {
        "ok": True,
        "source": "live",
        "symbol": (symbol or "BTC").strip().upper(),
        "marketSentiment": {"fearGreed": fear},
        "valuescanChain": {},
    }


def fetch_market_tickers(*, quote: str = "USDT", limit: int = 300) -> dict[str, Any]:
    refresh_bases()
    data = http_get(f"{KUCOIN_API_BASE}/api/v1/market/allTickers", timeout=15)
    if data.get("code") not in (None, "200000"):
        raise RuntimeError(data.get("msg", "KuCoin API error"))
    raw = ((data.get("data") or {}).get("ticker") or [])
    quote_upper = quote.upper()
    tickers = []
    for item in raw:
        symbol = str(item.get("symbol", ""))
        if not symbol.endswith(f"-{quote_upper}"):
            continue
        tickers.append(
            {
                "symbol": symbol,
                "last": float(item.get("last") or 0),
                "changeRate": float(item.get("changeRate") or 0),
                "volValue": float(item.get("volValue") or 0),
            }
        )
        if len(tickers) >= limit:
            break
    return {
        "ok": True,
        "source": "live",
        "quote": quote_upper,
        "count": len(tickers),
        "tickers": tickers,
    }


def fetch_candles(
    symbol: str = "BTC-USDT",
    *,
    kline_type: str = "1day",
    limit: int = 120,
) -> dict[str, Any]:
    refresh_bases()
    pair = symbol.strip().upper()
    if "-" not in pair:
        pair = f"{pair}-USDT"
    url = (
        f"{KUCOIN_API_BASE}/api/v1/market/candles?"
        f"symbol={quote(pair)}&type={quote(kline_type)}"
    )
    data = http_get(url, timeout=15)
    if data.get("code") not in (None, "200000"):
        raise RuntimeError(data.get("msg", "KuCoin candles error"))
    raw = data.get("data") or []
    candles = [item for row in raw if (item := normalize_candle(row))]
    candles.sort(key=lambda item: item["tsSec"])
    if limit > 0:
        candles = candles[-limit:]
    return {
        "ok": True,
        "source": "live",
        "symbol": pair,
        "type": kline_type,
        "candles": candles,
    }


def candles_to_curve(candles: list[dict[str, Any]], *, short: int = 3, long: int = 7) -> list[dict[str, Any]]:
    closes = [float(item["close"]) for item in candles]
    curve: list[dict[str, Any]] = []
    for index, candle in enumerate(candles):
        short_ma = _sma(closes, index, short)
        long_ma = _sma(closes, index, long)
        curve.append(
            {
                "date": candle["date"],
                "close": candle["close"],
                "equity": candle["close"],
                "short_ma": short_ma,
                "long_ma": long_ma,
            }
        )
    return curve


def _sma(values: list[float], index: int, window: int) -> float | None:
    if window <= 0 or index + 1 < window:
        return None
    sample = values[index + 1 - window : index + 1]
    return sum(sample) / len(sample)
