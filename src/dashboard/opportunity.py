from __future__ import annotations

import time
from typing import Any

from dashboard import market
from dashboard.text import market_overview


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


def scan_opportunities_from_tickers(
    tickers_payload: dict[str, Any],
    *,
    min_volume_24h: float = 200_000,
    max_symbols: int | None = None,
) -> dict[str, Any]:
    t0 = time.time()
    tickers = tickers_payload.get("tickers") or []
    filtered = [item for item in tickers if float(item.get("volValue") or 0) >= min_volume_24h]
    filtered.sort(key=lambda item: float(item.get("volValue") or 0), reverse=True)
    if max_symbols is not None and max_symbols > 0:
        candidates = filtered[:max_symbols]
    else:
        candidates = filtered

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
    ranked = [{**item, "rank": index + 1} for index, item in enumerate(opportunities)]
    overview = market_overview(ranked[:5], len(candidates))
    return {
        "ok": True,
        "source": "live",
        "full": max_symbols is None,
        "scanTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "totalScanned": len(candidates),
        "topK": len(ranked),
        "opportunities": ranked,
        "marketOverview": overview,
        "scanDurationMs": int((time.time() - t0) * 1000),
        "engine": "sandbox-rule-based",
        "errors": errors,
    }


def scan_opportunities(
    *,
    top_k: int = 5,
    max_symbols: int = 30,
    min_volume_24h: float = 200_000,
) -> dict[str, Any]:
    """Limited sync replica of web3-trading opportunity radar (rule-based only)."""
    tickers_payload = market.fetch_market_tickers(limit=max(50, max_symbols))
    payload = scan_opportunities_from_tickers(
        tickers_payload,
        min_volume_24h=min_volume_24h,
        max_symbols=max_symbols,
    )
    payload["topK"] = top_k
    payload["opportunities"] = payload["opportunities"][:top_k]
    payload["opportunities"] = [
        {**item, "rank": index + 1} for index, item in enumerate(payload["opportunities"])
    ]
    payload["marketOverview"] = market_overview(payload["opportunities"], payload["totalScanned"])
    return payload


def scan_opportunities_full(*, min_volume_24h: float = 200_000) -> dict[str, Any]:
    tickers_payload = market.fetch_market_tickers(limit=None)
    return scan_opportunities_from_tickers(
        tickers_payload,
        min_volume_24h=min_volume_24h,
        max_symbols=None,
    )
