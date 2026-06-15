from __future__ import annotations

from typing import Any

from dashboard import market
from dashboard.fixtures import load_offline
from dashboard.indicators import atr, bollinger_bands, extract_ohlcv, last_sma, rsi
from dashboard.mode import prefer_offline, try_live_public


TREND_LABELS = {
    "bullish": "多头趋势",
    "bearish": "空头趋势",
    "weak_bullish": "短线偏多",
    "weak_bearish": "短线偏空",
    "neutral": "中性",
}

REGIME_LABELS = {
    "trending": "趋势行情",
    "ranging": "震荡行情",
    "transitional": "过渡阶段",
    "unknown": "未知",
}

KLINE_TYPES = {"15min", "1hour", "4hour", "1day"}


def _classify_ma_trend(close: float, sma20: float | None, sma60: float | None) -> str:
    if sma20 is None:
        return "neutral"
    if sma60 is not None:
        if close > sma20 > sma60:
            return "bullish"
        if close < sma20 < sma60:
            return "bearish"
    return "weak_bullish" if close > sma20 else "weak_bearish"


def analyze_candles(candles: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(candles) < 20:
        return None
    ohlcv = extract_ohlcv(candles)
    highs = ohlcv["high"]
    lows = ohlcv["low"]
    closes = ohlcv["close"]
    volumes = ohlcv["volume"]
    latest_close = closes[-1]

    sma20 = last_sma(closes, 20)
    sma60 = last_sma(closes, 60)
    support = min(lows[-20:])
    resistance = max(highs[-20:])
    rng = resistance - support
    range_pos = (latest_close - support) / rng * 100 if rng > 0 else 50.0

    vol_recent = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else 0.0
    vol_avg = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else 0.0
    vol_ratio = vol_recent / vol_avg if vol_avg > 0 else 1.0

    rsi_values = rsi(closes, 14)
    rsi_val = rsi_values[-1] if rsi_values else None

    bb = bollinger_bands(closes, 20, 2.0)
    bb_upper = bb["upper"][-1] if bb["upper"] else None
    bb_mid = bb["middle"][-1] if bb["middle"] else None
    bb_lower = bb["lower"][-1] if bb["lower"] else None
    bb_width = None
    bb_pct_b = None
    if bb_upper is not None and bb_lower is not None and bb_mid and bb_mid > 0:
        bb_width = (bb_upper - bb_lower) / bb_mid * 100
        band_range = bb_upper - bb_lower
        bb_pct_b = (latest_close - bb_lower) / band_range * 100 if band_range > 0 else 50.0

    atr_values = atr(highs, lows, closes, 14)
    atr_val = atr_values[-1] if atr_values else None
    atr_pct = (atr_val / latest_close * 100) if atr_val and latest_close > 0 else None

    regime = "unknown"
    if bb_width is not None and atr_pct is not None:
        if bb_width < 3.0 and atr_pct < 1.5:
            regime = "ranging"
        elif bb_width > 6.0 or atr_pct > 3.0:
            regime = "trending"
        else:
            regime = "transitional"

    prev_high = max(highs[-21:-1]) if len(highs) >= 21 else resistance
    prev_low = min(lows[-21:-1]) if len(lows) >= 21 else support
    breakout = "none"
    if latest_close > prev_high and vol_ratio >= 1.3:
        breakout = "bullish"
    elif latest_close < prev_low and vol_ratio >= 1.3:
        breakout = "bearish"

    return {
        "trend": _classify_ma_trend(latest_close, sma20, sma60),
        "sma20": sma20,
        "sma60": sma60,
        "close": latest_close,
        "open": ohlcv["open"][-1] if ohlcv["open"] else None,
        "rangePos": range_pos,
        "support": support,
        "resistance": resistance,
        "volRatio": round(vol_ratio, 2),
        "rsi": round(rsi_val, 1) if rsi_val is not None else None,
        "bbUpper": round(bb_upper, 6) if bb_upper is not None else None,
        "bbLower": round(bb_lower, 6) if bb_lower is not None else None,
        "bbWidth": round(bb_width, 2) if bb_width is not None else None,
        "bbPctB": round(bb_pct_b, 1) if bb_pct_b is not None else None,
        "atr": round(atr_val, 6) if atr_val is not None else None,
        "atrPct": round(atr_pct, 2) if atr_pct is not None else None,
        "regime": regime,
        "breakout": breakout,
    }


def kline_verdict(analysis: dict[str, Any] | None) -> dict[str, Any]:
    if not analysis:
        return {
            "action": "WAIT",
            "actionLabel": "等待",
            "direction": "neutral",
            "score": 0,
            "confidence": 0,
            "reasons": ["数据不足"],
        }

    score = 0.0
    reasons: list[str] = []
    trend = analysis.get("trend", "")
    rsi_val = analysis.get("rsi")
    bb_pct_b = analysis.get("bbPctB")
    bb_width = analysis.get("bbWidth")
    regime = analysis.get("regime", "unknown")
    breakout = analysis.get("breakout", "none")
    vol_ratio = analysis.get("volRatio", 1.0)
    range_pos = analysis.get("rangePos", 50)

    trend_map = {
        "bullish": (20, "均线多头排列，趋势向上"),
        "weak_bullish": (10, "短线偏多，价格站上 MA20"),
        "bearish": (-20, "均线空头排列，趋势向下"),
        "weak_bearish": (-10, "短线偏空，价格跌破 MA20"),
    }
    if trend in trend_map:
        delta, reason = trend_map[trend]
        score += delta
        reasons.append(reason)

    if rsi_val is not None:
        if rsi_val >= 70:
            score -= 7
            reasons.append(f"RSI {rsi_val:.1f} 超买，注意回调")
        elif rsi_val <= 30:
            score += 7
            reasons.append(f"RSI {rsi_val:.1f} 超卖，关注反弹")

    if breakout == "bullish":
        score += 8
        reasons.append(f"向上突破前期高点，量比 {vol_ratio:.1f}x")
    elif breakout == "bearish":
        score -= 8
        reasons.append(f"向下跌破前期低点，量比 {vol_ratio:.1f}x")

    if regime == "ranging":
        if range_pos >= 80:
            score -= 4
            reasons.append("震荡行情中接近区间顶部")
        elif range_pos <= 20:
            score += 4
            reasons.append("震荡行情中接近区间底部")

    score = max(-100, min(100, score))
    if score >= 25:
        action, label, direction = "LONG", "做多", "bullish"
    elif score >= 10:
        action, label, direction = "WEAK_LONG", "偏多观望", "bullish"
    elif score <= -25:
        action, label, direction = "SHORT", "做空", "bearish"
    elif score <= -10:
        action, label, direction = "WEAK_SHORT", "偏空观望", "bearish"
    else:
        action, label, direction = "WAIT", "观望等待", "neutral"

    return {
        "action": action,
        "actionLabel": label,
        "direction": direction,
        "score": round(score, 1),
        "confidence": min(95, round(abs(score), 1)),
        "reasons": reasons,
    }


def _normalize_pair(symbol: str) -> str:
    raw = (symbol or "BTC-USDT").strip().upper()
    if "-" not in raw:
        raw = f"{raw}-USDT"
    return raw


def fetch_candles_for_analysis(
    symbol: str,
    *,
    kline_type: str = "1hour",
    limit: int = 120,
) -> list[dict[str, Any]]:
    pair = _normalize_pair(symbol)
    ktype = kline_type if kline_type in KLINE_TYPES else "1hour"
    limit = max(20, min(300, limit))

    if prefer_offline():
        cached = load_offline("market_candles")
        candles = list(cached.get("candles") or [])
        if len(candles) >= 20 and str(cached.get("symbol", pair)).upper() == pair:
            return candles[-limit:]
    if try_live_public():
        try:
            payload = market.fetch_candles(pair, kline_type=ktype, limit=limit)
            return list(payload.get("candles") or [])
        except Exception:
            pass
    cached = load_offline("market_candles")
    return list(cached.get("candles") or [])[-limit:]


def run_kline_analysis(
    symbol: str = "BTC-USDT",
    *,
    kline_type: str = "1hour",
    limit: int = 120,
) -> dict[str, Any]:
    pair = _normalize_pair(symbol)
    ktype = kline_type if kline_type in KLINE_TYPES else "1hour"
    candles = fetch_candles_for_analysis(pair, kline_type=ktype, limit=limit)
    candles = sorted(candles, key=lambda item: int(item.get("tsSec") or 0))
    if len(candles) < 20:
        return {
            "ok": False,
            "message": f"K线数量不足: {len(candles)}",
            "error": "insufficient_candles",
        }

    analysis = analyze_candles(candles)
    latest = candles[-1]
    prev = candles[-2] if len(candles) >= 2 else latest
    prev_close = float(prev.get("close") or 0)
    latest_close = float(latest.get("close") or 0)
    change_pct = ((latest_close - prev_close) / prev_close * 100) if prev_close else 0
    ranges = [float(c.get("high") or 0) - float(c.get("low") or 0) for c in candles]
    vol_pct = (sum(ranges) / len(ranges) / latest_close * 100) if latest_close else 0
    verdict = kline_verdict(analysis)
    trend_key = (analysis or {}).get("trend", "neutral")

    return {
        "ok": True,
        "source": "live" if try_live_public() and not prefer_offline() else "snapshot",
        "symbol": pair,
        "type": ktype,
        "limit": len(candles),
        "trend": TREND_LABELS.get(trend_key, "数据不足"),
        "trendKey": trend_key,
        "verdict": verdict,
        "metrics": {
            "latestClose": latest_close,
            "latestOpen": float(latest.get("open") or 0),
            "latestHigh": float(latest.get("high") or 0),
            "latestLow": float(latest.get("low") or 0),
            "latestVolume": float(latest.get("volume") or 0),
            "candleChangeRatePct": change_pct,
            "sma20": analysis.get("sma20") if analysis else None,
            "sma60": analysis.get("sma60") if analysis else None,
            "support20": analysis.get("support") if analysis else float(latest.get("low") or 0),
            "resistance20": analysis.get("resistance") if analysis else float(latest.get("high") or 0),
            "volatilityPct": vol_pct,
            "rangePositionPct": analysis.get("rangePos") if analysis else 50,
            "rsi": analysis.get("rsi") if analysis else None,
            "bbUpper": analysis.get("bbUpper") if analysis else None,
            "bbLower": analysis.get("bbLower") if analysis else None,
            "bbWidth": analysis.get("bbWidth") if analysis else None,
            "bbPctB": analysis.get("bbPctB") if analysis else None,
            "atr": analysis.get("atr") if analysis else None,
            "atrPct": analysis.get("atrPct") if analysis else None,
            "regime": REGIME_LABELS.get((analysis or {}).get("regime", ""), "未知"),
            "breakout": analysis.get("breakout") if analysis else "none",
        },
        "analysis": analysis or {},
        "candles": candles,
    }
