from __future__ import annotations

from typing import Any, Callable

from dashboard import market

_PINNED_TICKER_BASES = ("BTC", "ETH")


def _ticker_base(symbol: str) -> str:
    upper = str(symbol or "").upper()
    return upper.split("-")[0] if "-" in upper else upper


def _pin_major_tickers(tickers: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    if limit <= 0 or not tickers:
        return tickers
    pinned: list[dict[str, Any]] = []
    pinned_bases: set[str] = set()
    rest: list[dict[str, Any]] = []
    for item in tickers:
        base = _ticker_base(str(item.get("symbol", "")))
        if base in _PINNED_TICKER_BASES and base not in pinned_bases:
            pinned.append(item)
            pinned_bases.add(base)
        else:
            rest.append(item)
    ordered = pinned + rest
    if len(ordered) <= limit:
        return ordered
    head = ordered[:limit]
    head_bases = {_ticker_base(str(item.get("symbol", ""))) for item in head}
    for item in pinned:
        base = _ticker_base(str(item.get("symbol", "")))
        if base not in head_bases:
            head = [item] + head[: max(0, limit - 1)]
            head_bases.add(base)
    return head


def trim_market_tickers(payload: dict[str, Any], *, quote: str, limit: int) -> dict[str, Any]:
    trimmed = dict(payload)
    tickers = list(trimmed.get("tickers") or [])
    if limit > 0:
        tickers = _pin_major_tickers(tickers, limit=limit)
    trimmed["tickers"] = tickers
    trimmed["count"] = len(tickers)
    trimmed["quote"] = quote.upper()
    trimmed["view"] = {"limit": limit, "quote": quote.upper()}
    return trimmed


def trim_dex_trending(payload: dict[str, Any], *, limit: int) -> dict[str, Any]:
    trimmed = dict(payload)
    tokens = list(trimmed.get("tokens") or [])
    if limit > 0:
        tokens = tokens[:limit]
    trimmed["tokens"] = tokens
    trimmed["view"] = {"limit": limit}
    return trimmed


def trim_opportunity_scan(
    payload: dict[str, Any],
    *,
    top_k: int,
    max_symbols: int | None = None,
) -> dict[str, Any]:
    trimmed = dict(payload)
    opportunities = list(trimmed.get("opportunities") or [])
    if max_symbols is not None and max_symbols > 0:
        opportunities = opportunities[:max_symbols]
    if top_k > 0:
        opportunities = opportunities[:top_k]
    trimmed["opportunities"] = [{**item, "rank": index + 1} for index, item in enumerate(opportunities)]
    trimmed["topK"] = top_k
    trimmed["view"] = {"topK": top_k, "maxSymbols": max_symbols}
    trimmed["marketOverview"] = _market_overview(trimmed["opportunities"], trimmed.get("totalScanned") or 0)
    return trimmed


def trim_market_candles(
    payload: dict[str, Any],
    *,
    limit: int,
    short: int = 3,
    long: int = 7,
) -> dict[str, Any]:
    trimmed = dict(payload)
    candles = list(trimmed.get("candles") or [])
    if limit > 0 and candles:
        candles = candles[-limit:]
    curve = market.candles_to_curve(candles, short=short, long=long) if candles else list(trimmed.get("curve") or [])
    trimmed["candles"] = candles
    trimmed["curve"] = curve
    trimmed["view"] = {"limit": limit, "short": short, "long": long}
    return trimmed


def _market_overview(items: list[dict[str, Any]], total_scanned: int) -> str:
    if not items:
        return "暂无足够数据生成市场概览。"
    buy_count = sum(1 for item in items if item.get("signal") in ("BUY", "WEAK_BUY"))
    sell_count = sum(1 for item in items if item.get("signal") in ("SELL", "WEAK_SELL"))
    neutral_count = sum(1 for item in items if item.get("signal") == "NEUTRAL")
    if buy_count > sell_count * 2:
        sentiment = "整体偏多"
    elif sell_count > buy_count * 2:
        sentiment = "整体偏空"
    else:
        sentiment = "方向分化"
    top_desc = "、".join(f"{item['symbol']}({item['label']})" for item in items[:3])
    return (
        f"扫描 {total_scanned} 个币种，市场{sentiment}。"
        f"多头 {buy_count}、空头 {sell_count}、中性 {neutral_count}。"
        f"综合靠前：{top_desc}。"
    )


def apply_view(
    payload: dict[str, Any],
    view_fn: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    return view_fn(payload)
