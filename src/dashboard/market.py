from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

from dashboard.http_client import http_get
from dashboard.kline_curve import candles_to_curve

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
        # Field count is too short to represent a complete candle.
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
    except IndexError:
        # Upstream row shape changed after the length check.
        return None
    except (ValueError, TypeError):
        # Timestamp or numeric OHLCV fields cannot be interpreted.
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


_NUMERIC_TICKER_KEYS = (
    "last",
    "buy",
    "sell",
    "changeRate",
    "changePrice",
    "high",
    "low",
    "vol",
    "volValue",
    "averagePrice",
    "takerFeeRate",
    "makerFeeRate",
    "takerCoefficient",
    "makerCoefficient",
)


def _normalize_ticker_row(item: dict[str, Any]) -> dict[str, Any]:
    row = dict(item)
    for key in _NUMERIC_TICKER_KEYS:
        if key in row and row[key] not in (None, ""):
            try:
                row[key] = float(row[key])
            except (TypeError, ValueError):
                pass
    return row


def fetch_kucoin_markets() -> dict[str, Any]:
    """web3交易所 交易对元数据（全量 markets 列表）。"""
    refresh_bases()
    data = http_get(f"{KUCOIN_API_BASE}/api/v1/markets", timeout=15)
    if data.get("code") not in (None, "200000"):
        raise RuntimeError(data.get("msg", "web3交易所 markets error"))
    markets = data.get("data") or []
    if not isinstance(markets, list):
        markets = []
    return {
        "ok": True,
        "source": "live",
        "full": True,
        "count": len(markets),
        "markets": markets,
    }


def fetch_ticker_stats(symbol: str = "BTC-USDT") -> dict[str, Any]:
    """Fetch a single web3交易所 spot ticker (stats) for major pairs."""
    refresh_bases()
    pair = symbol.strip().upper()
    if "-" not in pair:
        pair = f"{pair}-USDT"
    data = http_get(f"{KUCOIN_API_BASE}/api/v1/market/stats?symbol={quote(pair)}", timeout=10)
    if data.get("code") not in (None, "200000"):
        raise RuntimeError(data.get("msg", "web3交易所 stats error"))
    raw = data.get("data") or {}
    if not isinstance(raw, dict):
        raise RuntimeError("web3交易所 stats payload invalid")
    row = _normalize_ticker_row({**raw, "symbol": pair})
    return {
        "ok": True,
        "source": "live",
        "symbol": pair,
        "ticker": row,
    }


def fetch_market_tickers(*, quote: str = "USDT", limit: int | None = None) -> dict[str, Any]:
    """Fetch web3交易所 tickers. ``limit=None`` keeps every pair for the quote (full dataset)."""
    refresh_bases()
    data = http_get(f"{KUCOIN_API_BASE}/api/v1/market/allTickers", timeout=15)
    if data.get("code") not in (None, "200000"):
        raise RuntimeError(data.get("msg", "web3交易所 API error"))
    raw = ((data.get("data") or {}).get("ticker") or [])
    quote_upper = quote.upper()
    tickers = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol", ""))
        if not symbol.endswith(f"-{quote_upper}"):
            continue
        tickers.append(_normalize_ticker_row(item))
        if limit is not None and len(tickers) >= limit:
            break
    body: dict[str, Any] = {
        "ok": True,
        "source": "live",
        "quote": quote_upper,
        "count": len(tickers),
        "tickers": tickers,
    }
    if limit is None:
        body["full"] = True
    return body


def fetch_candles(
    symbol: str = "BTC-USDT",
    *,
    kline_type: str = "1day",
    limit: int | None = 120,
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
        raise RuntimeError(data.get("msg", "web3交易所 candles error"))
    raw = data.get("data") or []
    candles = [item for row in raw if (item := normalize_candle(row))]
    candles.sort(key=lambda item: item["tsSec"])
    if limit is not None and limit > 0:
        candles = candles[-limit:]
    body: dict[str, Any] = {
        "ok": True,
        "source": "live",
        "symbol": pair,
        "type": kline_type,
        "candles": candles,
    }
    if limit is None:
        body["full"] = True
    return body

