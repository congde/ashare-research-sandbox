from __future__ import annotations

import time
from typing import Any

from dashboard import market


def _signal_from_ticker(ticker: dict[str, Any]) -> tuple[str, str, float, float, list[str]]:
    change = float(ticker.get("changeRate") or 0)
    vol = float(ticker.get("volValue") or 0)
    score = change * 100
    reasons: list[str] = []

    if change >= 0.05:
        signal, label = "BUY", "强势上涨"
        score += 15
        reasons.append(f"24h 涨幅 {change * 100:.1f}%")
    elif change >= 0.02:
        signal, label = "WEAK_BUY", "温和上涨"
        score += 8
        reasons.append(f"24h 涨幅 {change * 100:.1f}%")
    elif change <= -0.05:
        signal, label = "SELL", "明显回调"
        score -= 15
        reasons.append(f"24h 跌幅 {change * 100:.1f}%")
    elif change <= -0.02:
        signal, label = "WEAK_SELL", "温和走弱"
        score -= 8
        reasons.append(f"24h 跌幅 {change * 100:.1f}%")
    else:
        signal, label = "NEUTRAL", "震荡整理"
        reasons.append("涨跌幅处于中性区间")

    if vol >= 5_000_000:
        score += 5
        reasons.append("24h 成交额活跃")
    elif vol >= 1_000_000:
        score += 2

    confidence = min(95.0, max(25.0, 40 + abs(score) * 0.6))
    return signal, label, round(score, 1), confidence, reasons[:3]


def scan_opportunities(
    *,
    top_k: int = 5,
    max_symbols: int = 30,
    min_volume_24h: float = 200_000,
) -> dict[str, Any]:
    """Limited sync replica of web3-trading opportunity radar (rule-based only)."""
    t0 = time.time()
    tickers_payload = market.fetch_market_tickers(limit=max(50, max_symbols))
    tickers = tickers_payload.get("tickers") or []
    filtered = [item for item in tickers if float(item.get("volValue") or 0) >= min_volume_24h]
    filtered.sort(key=lambda item: float(item.get("volValue") or 0), reverse=True)
    candidates = filtered[:max_symbols]

    opportunities: list[dict[str, Any]] = []
    errors: list[str] = []
    for ticker in candidates:
        symbol = str(ticker.get("symbol", ""))
        if "-" not in symbol:
            continue
        base = symbol.split("-")[0]
        try:
            signal, label, score, confidence, reasons = _signal_from_ticker(ticker)
            abs_score = abs(score)
            if abs_score >= 40 and confidence >= 65:
                risk_level = "low"
            elif abs_score <= 15 or confidence < 40:
                risk_level = "high"
            else:
                risk_level = "medium"
            if signal in ("BUY", "WEAK_BUY"):
                bias = "bullish"
            elif signal in ("SELL", "WEAK_SELL"):
                bias = "bearish"
            else:
                bias = "neutral"
            opportunities.append(
                {
                    "symbol": base,
                    "pair": symbol,
                    "signal": signal,
                    "label": label,
                    "score": score,
                    "confidence": confidence,
                    "change24h": float(ticker.get("changeRate") or 0),
                    "volume24h": float(ticker.get("volValue") or 0),
                    "last": float(ticker.get("last") or 0),
                    "keyReasons": reasons,
                    "tradePlan": None,
                    "riskLevel": risk_level,
                    "bias": bias,
                    "marketState": "uncertain",
                }
            )
        except Exception as exc:
            errors.append(f"{base}: {exc}")

    opportunities.sort(key=lambda item: abs(float(item["score"])), reverse=True)
    ranked = [{**item, "rank": index + 1} for index, item in enumerate(opportunities[:top_k])]
    overview = _market_overview(ranked, len(candidates))
    return {
        "ok": True,
        "source": "live",
        "scanTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "totalScanned": len(candidates),
        "topK": top_k,
        "opportunities": ranked,
        "marketOverview": overview,
        "scanDurationMs": int((time.time() - t0) * 1000),
        "engine": "sandbox-rule-based",
        "errors": errors,
    }


def _market_overview(items: list[dict[str, Any]], total_scanned: int) -> str:
    if not items:
        return "暂无足够数据生成市场概览。"
    buy_count = sum(1 for item in items if item["signal"] in ("BUY", "WEAK_BUY"))
    sell_count = sum(1 for item in items if item["signal"] in ("SELL", "WEAK_SELL"))
    neutral_count = sum(1 for item in items if item["signal"] == "NEUTRAL")
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
