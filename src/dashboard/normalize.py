from __future__ import annotations

from typing import Any


def _to_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _find_trade_row(rows: Any, time_range: str) -> dict[str, Any]:
    target = time_range.lower()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("timeRange", "")).lower() == target:
            return row
    return {}


def normalize_pick_item(item: dict[str, Any], channel: str) -> dict[str, Any]:
    out = dict(item)
    symbol = str(item.get("symbol") or "?")
    score = _to_float(item.get("score"))
    pct24 = _to_float(item.get("percentChange24h"))

    if not out.get("title"):
        if score is not None:
            out["title"] = f"评分 {score:.0f}"
        else:
            out["title"] = {
                "chance": "AI 机会",
                "funds": "资金异动",
                "risk": "风险回避",
            }.get(channel, "信号")

    if not out.get("summary"):
        parts: list[str] = []
        if pct24 is not None:
            parts.append(f"24h {pct24:+.1f}%")
        if score is not None:
            parts.append(f"评分 {score:.0f}")
        rank = item.get("marketCapRanking")
        if rank not in (None, ""):
            parts.append(f"市值 #{rank}")
        gains = _to_float(item.get("gains"))
        if gains is not None and channel == "chance":
            parts.append(f"涨幅 {gains:.1f}%")
        out["summary"] = " · ".join(parts) if parts else str(item.get("name") or "ValueScan 条目")

    if score is not None and out.get("score") is None:
        out["score"] = score
    out.setdefault("symbol", symbol)
    return out


def normalize_ai_picks(payload: dict[str, Any]) -> dict[str, Any]:
    body = dict(payload)
    for key, channel in (("chance", "chance"), ("funds", "funds"), ("risk", "risk")):
        items = body.get(key)
        if isinstance(items, list):
            body[key] = [normalize_pick_item(item, channel) for item in items if isinstance(item, dict)]
    return body


def normalize_token_fund(payload: dict[str, Any]) -> dict[str, Any]:
    body = dict(payload)
    fund = dict(body.get("fund") or {})
    ratio_src = dict(body.get("fundMarketCapRatio") or {})
    sentiment_src = dict(body.get("sentiment") or {})

    row24 = _find_trade_row(fund.get("spotGoodsList"), "24h")
    if not row24:
        row24 = _find_trade_row(fund.get("contractList"), "24h")

    display_fund = dict(fund)
    inflow24 = _to_float(row24.get("tradeInflow"))
    trade_in24 = _to_float(row24.get("tradeIn"))
    if inflow24 is not None:
        display_fund.setdefault("netInflow24h", inflow24)
    if trade_in24 is not None:
        display_fund.setdefault("tradeInflow24h", trade_in24)
    if display_fund.get("netInflow24h") is None:
        total = _to_float(ratio_src.get("totalTradeInflow"))
        if total is not None:
            display_fund["netInflow24h"] = total

    display_sentiment = dict(sentiment_src)
    if display_sentiment.get("score") is None:
        bullish = _to_float(sentiment_src.get("bullishRatio"))
        if bullish is not None:
            display_sentiment["score"] = round(bullish * 100, 1)
            display_sentiment["label"] = "看多占比"

    display_ratio = dict(ratio_src)
    if display_ratio.get("ratio") is None:
        for key in ("totalMarketCapRatio", "spotMarketCapRatio", "contractMarketCapRatio"):
            value = ratio_src.get(key)
            if value is not None:
                display_ratio["ratio"] = value
                break

    body["fund"] = display_fund
    body["sentiment"] = display_sentiment
    body["fundMarketCapRatio"] = display_ratio
    return body
