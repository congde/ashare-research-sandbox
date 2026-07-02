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
from dashboard import dexscan, market, news, opportunity, valuescan
from dashboard.fixtures import load_offline
from dashboard.mode import dashboard_data_mode, prefer_offline, serve_offline_first, try_live_public
from dashboard.resolve import try_cached_first
from dashboard.normalize import normalize_ai_picks, normalize_token_fund
from dashboard.dataset_views import trim_dex_trending, trim_market_tickers
from dashboard.kline_curve import kline_payload_to_curve
from dashboard.persist import annotate_cached, maybe_persist
from dashboard.persist_hooks import (
    persist_kucoin_bundle,
    persist_valuescan_global,
    persist_valuescan_token_full,
)
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


def _with_fallback(
    live_fn: Callable[[], dict[str, Any]],
    cache_name: str,
    **cache_parts: str | int,
) -> dict[str, Any]:
    try:
        payload = live_fn()
        if payload.get("ok") is False and payload.get("message"):
            raise RuntimeError(str(payload["message"]))
        maybe_persist(cache_name, payload, **cache_parts)
        return payload
    except Exception:
        return annotate_cached(load_offline(cache_name, **cache_parts))


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
            "mode": __import__("os").environ.get("WEB3_TRADING_UPSTREAM", "never"),
        },
        "symbols": {
            "watch": get_watch_symbols(),
            "primary_pair": primary_market_symbol(),
        },
        "env": env_status(),
        "config_sources": config_sources(),
        "data_mode": dashboard_data_mode(),
    }


def ai_picks(*, refresh: bool = False) -> dict[str, Any]:
    load_env()

    def _refresh() -> None:
        ai_picks(refresh=True)

    cached = try_cached_first(
        "ai_picks",
        refresh=refresh,
        background_key="ai_picks",
        fetch_live=_refresh,
    )
    if cached is not None:
        return normalize_ai_picks(cached)

    hit = _try_upstream("/api/dashboard/vs/ai-picks")
    if hit:
        payload = normalize_ai_picks(hit)
        maybe_persist("ai_picks", payload)
        persist_valuescan_global()
        return payload
    if prefer_offline():
        return normalize_ai_picks(load_offline("ai_picks"))
    if valuescan.configured():
        payload = normalize_ai_picks(_with_fallback(valuescan.get_ai_picks, "ai_picks"))
        persist_valuescan_global()
        return payload
    return normalize_ai_picks(load_offline("ai_picks"))


def sector_fund(trade_type: int = 1, *, refresh: bool = False) -> dict[str, Any]:
    load_env()

    def _refresh() -> None:
        sector_fund(trade_type, refresh=True)

    cached = try_cached_first(
        "sector_fund",
        refresh=refresh,
        background_key=f"sector_fund:{trade_type}",
        fetch_live=_refresh,
        trade_type=trade_type,
    )
    if cached is not None:
        fixture = dict(cached)
        fixture["tradeType"] = trade_type
        return fixture

    hit = _try_upstream("/api/dashboard/vs/sector-fund", {"trade_type": trade_type})
    if hit:
        maybe_persist("sector_fund", hit, trade_type=trade_type)
        return hit
    if prefer_offline():
        fixture = load_offline("sector_fund", trade_type=trade_type)
        fixture["tradeType"] = trade_type
        return fixture
    if valuescan.configured():
        payload = _with_fallback(
            lambda: valuescan.get_sector_fund(trade_type),
            "sector_fund",
            trade_type=trade_type,
        )
        payload["tradeType"] = trade_type
        return payload
    fixture = load_offline("sector_fund", trade_type=trade_type)
    fixture["tradeType"] = trade_type
    return fixture


def token_fund(symbol: str, *, refresh: bool = False) -> dict[str, Any]:
    load_env()
    sym = symbol.strip().upper()

    def _refresh() -> None:
        token_fund(sym, refresh=True)

    cached = try_cached_first(
        "token_fund",
        refresh=refresh,
        background_key=f"token_fund:{sym}",
        fetch_live=_refresh,
        symbol=sym,
    )
    if cached is not None:
        fixture = dict(cached)
        fixture["symbol"] = sym
        return normalize_token_fund(fixture)

    hit = _try_upstream("/api/dashboard/vs/token-fund", {"symbol": sym})
    if hit:
        hit["symbol"] = sym
        payload = normalize_token_fund(hit)
        maybe_persist("token_fund", payload, symbol=sym)
        persist_valuescan_token_full(sym)
        return payload
    if prefer_offline():
        fixture = load_offline("token_fund", symbol=sym)
        fixture["symbol"] = sym
        return normalize_token_fund(fixture)
    if valuescan.configured():
        payload = _with_fallback(
            lambda: valuescan.get_token_fund(symbol),
            "token_fund",
            symbol=sym,
        )
        payload["symbol"] = sym
        normalized = normalize_token_fund(payload)
        persist_valuescan_token_full(sym)
        return normalized
    fixture = load_offline("token_fund", symbol=sym)
    fixture["symbol"] = sym
    return normalize_token_fund(fixture)


def onchain(symbol: str = "BTC", *, limit: int = 1, refresh: bool = False) -> dict[str, Any]:
    load_env()
    sym = symbol.strip().upper()

    def _refresh() -> None:
        onchain(sym, limit=limit, refresh=True)

    cached = try_cached_first(
        "onchain",
        refresh=refresh,
        background_key=f"onchain:{sym}",
        fetch_live=_refresh,
        symbol=sym,
    )
    if cached is not None:
        payload = dict(cached)
        payload["symbol"] = sym
        return payload

    hit = _try_upstream(
        "/api/dashboard/onchain",
        {"symbol": sym, "limit": max(1, min(20, limit))},
    )
    if hit:
        hit["symbol"] = sym
        maybe_persist("onchain", hit, symbol=sym)
        return hit
    if prefer_offline():
        cached = load_offline("onchain", symbol=sym)
        cached["symbol"] = sym
        return cached
    if try_live_public():
        try:
            live = market.fetch_onchain(symbol, limit=limit)
            if live.get("marketSentiment", {}).get("fearGreed"):
                live["symbol"] = sym
                maybe_persist("onchain", live, symbol=sym)
                return live
        except Exception:
            cached = annotate_cached(load_offline("onchain", symbol=sym))
            cached["symbol"] = sym
            return cached
    cached = load_offline("onchain", symbol=sym)
    cached["symbol"] = sym
    return cached


def dex_trending(*, chain: str = "solana", limit: int = 5, refresh: bool = False) -> dict[str, Any]:
    load_env()

    def _refresh() -> None:
        dex_trending(chain=chain, limit=limit, refresh=True)

    cached = try_cached_first(
        "dex_trending",
        refresh=refresh,
        background_key=f"dex_trending:{chain}",
        fetch_live=_refresh,
        chain=chain,
    )
    if cached is not None:
        fixture = dict(cached)
        fixture["chain"] = chain
        return trim_dex_trending(fixture, limit=limit)

    hit = _try_upstream("/api/dashboard/dex/trending", {"chain": chain, "limit": limit})
    if hit:
        hit["chain"] = chain
        maybe_persist("dex_trending", hit, chain=chain)
        return trim_dex_trending(hit, limit=limit)
    if prefer_offline():
        fixture = load_offline("dex_trending", chain=chain)
        fixture["chain"] = chain
        return fixture
    if dexscan.configured():
        try:
            full = dexscan.get_dex_trending(chain=chain, limit=None)
            if full.get("ok") is False and full.get("message"):
                raise RuntimeError(str(full["message"]))
            full["chain"] = chain
            maybe_persist("dex_trending", full, chain=chain)
            return trim_dex_trending(full, limit=limit)
        except Exception:
            payload = annotate_cached(load_offline("dex_trending", chain=chain))
            payload["chain"] = chain
            return trim_dex_trending(payload, limit=limit)
    fixture = load_offline("dex_trending", chain=chain)
    fixture["chain"] = chain
    return fixture


def market_tickers(*, quote: str = "USDT", limit: int = 300, refresh: bool = False) -> dict[str, Any]:
    load_env()

    def _refresh() -> None:
        market_tickers(quote=quote, limit=limit, refresh=True)

    cached = try_cached_first(
        "market_tickers",
        refresh=refresh,
        background_key="market_tickers",
        fetch_live=_refresh,
    )
    if cached is not None:
        return trim_market_tickers(cached, quote=quote, limit=limit)

    hit = _try_upstream("/api/market/tickers", {"quote": quote.upper(), "limit": limit})
    if hit:
        trimmed = trim_market_tickers(hit, quote=quote, limit=limit)
        maybe_persist("market_tickers", hit)
        return trimmed
    if prefer_offline():
        payload = load_offline("market_tickers")
        return trim_market_tickers(payload, quote=quote, limit=limit)
    if try_live_public():
        try:
            full = market.fetch_market_tickers(quote=quote, limit=None)
            maybe_persist("market_tickers", full)
            persist_kucoin_bundle(quote=quote)
            return trim_market_tickers(full, quote=quote, limit=limit)
        except Exception:
            cached = annotate_cached(load_offline("market_tickers"))
            return trim_market_tickers(cached, quote=quote, limit=limit)
    payload = load_offline("market_tickers")
    return trim_market_tickers(payload, quote=quote, limit=limit)


def web3_news(*, limit: int = 50, refresh: bool = False) -> dict[str, Any]:
    load_env()
    clipped_limit = max(1, min(100, limit))

    def _refresh() -> None:
        web3_news(limit=clipped_limit, refresh=True)

    cached = try_cached_first(
        "web3_news",
        refresh=refresh,
        background_key="web3_news",
        fetch_live=_refresh,
    )
    if cached is not None:
        payload = dict(cached)
        payload["items"] = (payload.get("items") or [])[:clipped_limit]
        return payload

    hit = _try_upstream("/api/dashboard/web3-news", {"limit": clipped_limit})
    if hit:
        maybe_persist("web3_news", hit)
        hit["items"] = (hit.get("items") or [])[:clipped_limit]
        return hit
    if prefer_offline():
        payload = load_offline("web3_news")
        payload["items"] = (payload.get("items") or [])[:clipped_limit]
        return payload
    if try_live_public():
        try:
            payload = news.fetch_web3_news(watch_symbols=get_watch_symbols(), limit=clipped_limit)
            maybe_persist("web3_news", payload)
            return payload
        except Exception:
            payload = annotate_cached(load_offline("web3_news"))
            payload["items"] = (payload.get("items") or [])[:clipped_limit]
            return payload
    payload = load_offline("web3_news")
    payload["items"] = (payload.get("items") or [])[:clipped_limit]
    return payload


def _offline_ticker_stats(symbol: str) -> dict[str, Any] | None:
    pair = symbol.strip().upper()
    if "-" not in pair:
        pair = f"{pair}-USDT"
    payload = load_offline("market_tickers")
    for item in payload.get("tickers") or []:
        if str(item.get("symbol", "")).upper() == pair:
            return {
                "ok": True,
                "source": payload.get("source", "offline"),
                "symbol": pair,
                "ticker": item,
            }
    return None


def ticker_stats(symbol: str = "BTC-USDT", *, refresh: bool = False) -> dict[str, Any]:
    load_env()
    pair = symbol.strip().upper()
    if "-" not in pair:
        pair = f"{pair}-USDT"

    if serve_offline_first(refresh=refresh):
        offline = _offline_ticker_stats(pair)
        if offline:
            return offline

    hit = _try_upstream("/api/market/ticker", {"symbol": pair})
    if hit and hit.get("ticker"):
        return hit
    if try_live_public():
        try:
            return market.fetch_ticker_stats(pair)
        except Exception:
            offline = _offline_ticker_stats(pair)
            if offline:
                return annotate_cached(offline)
            raise
    offline = _offline_ticker_stats(pair)
    if offline:
        return offline
    return {"ok": False, "message": f"missing ticker: {pair}", "symbol": pair}


def opportunity_scan(
    *,
    top_k: int = 5,
    max_symbols: int = 30,
    min_volume_24h: float = 200000,
    refresh: bool = False,
) -> dict[str, Any]:
    load_env()

    def _refresh() -> None:
        opportunity_scan(
            top_k=top_k,
            max_symbols=max_symbols,
            min_volume_24h=min_volume_24h,
            refresh=True,
        )

    cached = try_cached_first(
        "opportunity_scan",
        refresh=refresh,
        background_key="opportunity_scan",
        fetch_live=_refresh,
    )
    if cached is not None:
        payload = dict(cached)
        payload["topK"] = top_k
        return payload

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
        hit["topK"] = top_k
        maybe_persist("opportunity_scan", hit)
        return hit
    if prefer_offline():
        cached = load_offline("opportunity_scan")
        cached["topK"] = top_k
        return cached
    try:
        payload = opportunity.scan_opportunities(
            top_k=top_k,
            max_symbols=max_symbols,
            min_volume_24h=min_volume_24h,
        )
        maybe_persist("opportunity_scan", payload)
        return payload
    except Exception:
        cached = annotate_cached(load_offline("opportunity_scan"))
        cached["topK"] = top_k
        return cached


def market_candles(
    symbol: str | None = None,
    *,
    kline_type: str = "1day",
    limit: int = 120,
    short: int = 3,
    long: int = 7,
    refresh: bool = False,
) -> dict[str, Any]:
    load_env()
    pair = (symbol or primary_market_symbol()).strip().upper()

    def _refresh() -> None:
        market_candles(
            symbol=pair,
            kline_type=kline_type,
            limit=limit,
            short=short,
            long=long,
            refresh=True,
        )

    cached = try_cached_first(
        "market_candles",
        refresh=refresh,
        background_key="market_candles",
        fetch_live=_refresh,
    )
    if cached is not None:
        payload = dict(cached)
        payload["symbol"] = pair
        return payload

    hit = _try_upstream(
        "/api/market/kline-analysis",
        {"symbol": pair, "type": kline_type, "limit": limit, "realtime": "false"},
    )
    if hit and hit.get("candles"):
        hit["curve"] = kline_payload_to_curve(hit.get("candles") or [], short=short, long=long)
        hit["symbol"] = pair
        maybe_persist("market_candles", hit)
        return hit

    hit = _try_upstream(
        "/api/market/candles",
        {"symbol": pair, "type": kline_type, "limit": limit},
    )
    if hit and hit.get("candles"):
        hit["curve"] = kline_payload_to_curve(hit.get("candles") or [], short=short, long=long)
        hit["symbol"] = pair
        maybe_persist("market_candles", hit)
        return hit

    if prefer_offline():
        cached = load_offline("market_candles")
        cached["symbol"] = pair
        return cached
    try:
        payload = market.fetch_candles(pair, kline_type=kline_type, limit=limit)
        payload["curve"] = market.candles_to_curve(payload["candles"], short=short, long=long)
        payload["symbol"] = pair
        maybe_persist("market_candles", payload)
        return payload
    except Exception:
        cached = annotate_cached(load_offline("market_candles"))
        cached["symbol"] = pair
        return cached


def kline_analysis(
    symbol: str = "BTC-USDT",
    *,
    kline_type: str = "1hour",
    limit: int = 120,
) -> dict[str, Any]:
    from dashboard.kline_analysis import run_kline_analysis

    load_env()
    hit = _try_upstream(
        "/api/market/kline-analysis",
        {"symbol": symbol, "type": kline_type, "limit": limit, "realtime": 1},
    )
    if hit:
        return hit
    return run_kline_analysis(symbol, kline_type=kline_type, limit=limit)


def signal_analysis(symbol: str = "BTC") -> dict[str, Any]:
    from dashboard.signal_analysis import run_signal_analysis

    load_env()
    hit = _try_upstream("/api/dashboard/signal-analysis", {"symbol": symbol.strip().upper()})
    if hit:
        return hit
    return run_signal_analysis(symbol)


def llm_signal_analysis(symbol: str = "BTC", *, model: str | None = None) -> dict[str, Any]:
    from dashboard.llm_signal import llm_configured, resolve_model, run_llm_signal_analysis
    from dashboard.signal_tasks import submit_task

    load_env()
    sym = symbol.strip().upper()
    resolved = resolve_model(model)
    query: dict[str, str | int | float | bool] = {"symbol": sym, "model": resolved}
    hit = _try_upstream("/api/dashboard/llm-signal-analysis", query)
    if hit and hit.get("taskId"):
        return hit
    if hit and hit.get("data"):
        return hit["data"] if isinstance(hit["data"], dict) else hit
    if llm_configured():
        return submit_task(sym, resolved)
    return run_llm_signal_analysis(sym, model=resolved)


def llm_signal_poll(task_id: str) -> dict[str, Any]:
    from dashboard.signal_tasks import poll_task

    load_env()
    hit = _try_upstream("/api/dashboard/llm-signal-analysis/poll", {"taskId": task_id})
    if hit:
        return hit
    return poll_task(task_id.strip())


def snapshots_status() -> dict[str, Any]:
    from dashboard.catalog import offline_status
    from dashboard.snapshot import list_snapshots

    items = list_snapshots()
    status = offline_status()
    return {
        "ok": True,
        "count": len(items),
        "snapshots": items,
        "manifest": status.get("manifest"),
        "datasets": status.get("datasets"),
        "complete_count": status.get("complete_count"),
        "total_count": status.get("total_count"),
    }


def sources_status() -> dict[str, Any]:
    load_env()
    cfg = runtime_config()
    env = {
        "valuescan": valuescan.configured(),
        "dexscan": dexscan.configured(),
        "web3_exchange_public": True,
        "web3_news_public": True,
        "fear_greed_public": True,
        "data_mode": dashboard_data_mode(),
        "upstream": cfg["upstream"],
    }
    probes: list[dict[str, Any]] = []
    checks = [
        ("web3_news", "Web3 news", lambda: web3_news(limit=5)),
        ("web3_exchange", "web3交易所 行情", lambda: market_tickers(limit=5)),
        ("valuescan", "ValueScan", ai_picks),
        ("dexscan", "DexScan", lambda: dex_trending(limit=3)),
        ("feargreed", "恐贪指数", lambda: onchain("BTC")),
        ("radar", "机会雷达", lambda: opportunity_scan(top_k=1, max_symbols=5)),
    ]
    for source_id, name, fn in checks:
        try:
            data = fn()
            ok = bool(data.get("ok", True))
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
