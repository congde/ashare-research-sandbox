from __future__ import annotations

from typing import Any, Callable

from config.env import env_status, load_env
from config.web3_trading import (
    config_sources,
    get_dashboard_url,
    get_upstream_base_url,
    get_watch_symbols,
    primary_market_symbol,
)
from dashboard import dexscan, market, opportunity, valuescan
from dashboard.fixtures import load_offline
from dashboard.upstream import upstream_available, upstream_get


def _tag_upstream(payload: dict[str, Any]) -> dict[str, Any]:
    tagged = dict(payload)
    tagged["source"] = "web3-trading-upstream"
    tagged["upstream"] = get_upstream_base_url()
    return tagged


def _try_upstream(path: str, query: dict[str, str | int | float | bool] | None = None) -> dict[str, Any] | None:
    payload = upstream_get(path, query)
    if not payload or payload.get("ok") is False:
        return None
    return _tag_upstream(payload)


def _with_fallback(live_fn: Callable[[], dict[str, Any]], cache_name: str) -> dict[str, Any]:
    try:
        payload = live_fn()
        if payload.get("ok") is False and payload.get("message"):
            raise RuntimeError(str(payload["message"]))
        return payload
    except Exception:
        cached = load_offline(cache_name)
        cached["live_error"] = True
        return cached


def runtime_config() -> dict[str, Any]:
    load_env()
    base = get_upstream_base_url()
    dashboard_url = get_dashboard_url()
    return {
        "ok": True,
        "upstream": {
            "base_url": base,
            "dashboard_url": dashboard_url,
            "available": upstream_available() if base else False,
            "mode": __import__("os").environ.get("WEB3_TRADING_UPSTREAM", "auto"),
        },
        "symbols": {
            "watch": get_watch_symbols(),
            "primary_pair": primary_market_symbol(),
        },
        "env": env_status(),
        "config_sources": config_sources(),
    }


def ai_picks() -> dict[str, Any]:
    load_env()
    hit = _try_upstream("/api/dashboard/vs/ai-picks")
    if hit:
        return hit
    if valuescan.configured():
        return _with_fallback(valuescan.get_ai_picks, "ai_picks")
    return load_offline("ai_picks")


def sector_fund(trade_type: int = 1) -> dict[str, Any]:
    load_env()
    hit = _try_upstream("/api/dashboard/vs/sector-fund", {"trade_type": trade_type})
    if hit:
        return hit
    if valuescan.configured():
        return _with_fallback(lambda: valuescan.get_sector_fund(trade_type), "sector_fund")
    fixture = load_offline("sector_fund")
    fixture["tradeType"] = trade_type
    return fixture


def token_fund(symbol: str) -> dict[str, Any]:
    load_env()
    hit = _try_upstream("/api/dashboard/vs/token-fund", {"symbol": symbol.strip().upper()})
    if hit:
        return hit
    if valuescan.configured():
        return _with_fallback(lambda: valuescan.get_token_fund(symbol), "token_fund")
    fixture = load_offline("token_fund")
    fixture["symbol"] = symbol.strip().upper()
    return fixture


def onchain(symbol: str = "BTC", *, limit: int = 1) -> dict[str, Any]:
    load_env()
    hit = _try_upstream(
        "/api/dashboard/onchain",
        {"symbol": symbol.strip().upper(), "limit": max(1, min(20, limit))},
    )
    if hit:
        return hit
    live = market.fetch_onchain(symbol, limit=limit)
    if live.get("marketSentiment", {}).get("fearGreed"):
        return live
    cached = load_offline("onchain")
    cached["symbol"] = symbol.strip().upper()
    return cached


def dex_trending(*, chain: str = "solana", limit: int = 5) -> dict[str, Any]:
    load_env()
    hit = _try_upstream("/api/dashboard/dex/trending", {"chain": chain, "limit": limit})
    if hit:
        return hit
    if dexscan.configured():
        return _with_fallback(lambda: dexscan.get_dex_trending(chain=chain, limit=limit), "dex_trending")
    fixture = load_offline("dex_trending")
    fixture["chain"] = chain
    return fixture


def market_tickers(*, quote: str = "USDT", limit: int = 300) -> dict[str, Any]:
    load_env()
    hit = _try_upstream("/api/market/tickers", {"quote": quote.upper(), "limit": limit})
    if hit:
        return hit
    return _with_fallback(lambda: market.fetch_market_tickers(quote=quote, limit=limit), "market_tickers")


def opportunity_scan(
    *,
    top_k: int = 5,
    max_symbols: int = 30,
    min_volume_24h: float = 200000,
) -> dict[str, Any]:
    load_env()
    hit = _try_upstream(
        "/api/dashboard/opportunity-scan",
        {
            "topK": top_k,
            "maxSymbols": max_symbols,
            "minVolume24h": min_volume_24h,
            "useValueScan": "true",
        },
    )
    if hit:
        return hit
    try:
        return opportunity.scan_opportunities(
            top_k=top_k,
            max_symbols=max_symbols,
            min_volume_24h=min_volume_24h,
        )
    except Exception:
        cached = load_offline("opportunity_scan")
        cached["topK"] = top_k
        return cached


def market_candles(
    symbol: str | None = None,
    *,
    kline_type: str = "1day",
    limit: int = 120,
    short: int = 3,
    long: int = 7,
) -> dict[str, Any]:
    load_env()
    pair = (symbol or primary_market_symbol()).strip().upper()
    hit = _try_upstream(
        "/api/market/kline-analysis",
        {"symbol": pair, "type": kline_type, "limit": limit, "realtime": "false"},
    )
    if hit and hit.get("candles"):
        curve = _kline_payload_to_curve(hit.get("candles") or [], short=short, long=long)
        hit["curve"] = curve
        return hit

    hit = _try_upstream(
        "/api/market/candles",
        {"symbol": pair, "type": kline_type, "limit": limit},
    )
    if hit and hit.get("candles"):
        hit["curve"] = _kline_payload_to_curve(hit.get("candles") or [], short=short, long=long)
        return hit

    try:
        payload = market.fetch_candles(pair, kline_type=kline_type, limit=limit)
        payload["curve"] = market.candles_to_curve(payload["candles"], short=short, long=long)
        return payload
    except Exception:
        cached = load_offline("market_candles")
        cached["symbol"] = pair
        return cached


def _kline_payload_to_curve(candles: list[Any], *, short: int, long: int) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in candles:
        if isinstance(item, dict):
            close = float(item.get("close") or item.get("c") or 0)
            ts = item.get("date") or item.get("time")
            if isinstance(ts, (int, float)):
                from datetime import datetime, timezone

                ts = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
            normalized.append({"date": str(ts), "close": close, "equity": close})
    if not normalized:
        return []
    closes = [float(row["close"]) for row in normalized]
    curve: list[dict[str, Any]] = []
    for index, row in enumerate(normalized):
        curve.append(
            {
                **row,
                "short_ma": _sma(closes, index, short),
                "long_ma": _sma(closes, index, long),
            }
        )
    return curve


def _sma(values: list[float], index: int, window: int) -> float | None:
    if window <= 0 or index + 1 < window:
        return None
    sample = values[index + 1 - window : index + 1]
    return sum(sample) / len(sample)


def snapshots_status() -> dict[str, Any]:
    from dashboard.snapshot import list_snapshots

    items = list_snapshots()
    return {"ok": True, "count": len(items), "snapshots": items}


def sources_status() -> dict[str, Any]:
    load_env()
    cfg = runtime_config()
    env = {
        "valuescan": valuescan.configured(),
        "dexscan": dexscan.configured(),
        "kucoin_public": True,
        "fear_greed_public": True,
        "upstream": cfg["upstream"],
    }
    probes: list[dict[str, Any]] = []
    checks = [
        ("upstream", "web3-trading 上游", lambda: runtime_config()),
        ("kucoin", "KuCoin 行情", lambda: market_tickers(limit=5)),
        ("valuescan", "ValueScan", ai_picks),
        ("dexscan", "DexScan", lambda: dex_trending(limit=3)),
        ("feargreed", "恐贪指数", lambda: onchain("BTC")),
        ("radar", "机会雷达", lambda: opportunity_scan(top_k=1, max_symbols=5)),
    ]
    for source_id, name, fn in checks:
        try:
            data = fn()
            ok = bool(data.get("ok", True))
            if source_id == "upstream":
                ok = bool((data.get("upstream") or {}).get("available"))
            probes.append(
                {
                    "id": source_id,
                    "name": name,
                    "ok": ok,
                    "source": data.get("source") or ("live" if ok else "offline"),
                }
            )
        except Exception as exc:
            probes.append({"id": source_id, "name": name, "ok": False, "error": str(exc)})
    return {"ok": True, "env": env, "probes": probes, "dashboard_url": get_dashboard_url()}
