# -*- coding: utf-8 -*-
"""K 线归一化与市场状态分析。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from quant.indicators import (
    atr,
    bollinger_bands,
    extract_ohlcv,
    last_sma,
    macd,
    rsi,
)


def merge_live_price_into_candles(candles: List[Dict[str, Any]], live_price: float) -> bool:
    """Patch the forming bar OHLC with L1 / mark price."""
    if not candles or live_price <= 0:
        return False
    latest = candles[-1]
    high = float(latest.get("high") or latest.get("h") or live_price)
    low = float(latest.get("low") or latest.get("l") or live_price)
    latest["close"] = live_price
    latest["c"] = live_price
    latest["high"] = max(high, live_price)
    latest["h"] = latest["high"]
    latest["low"] = min(low, live_price)
    latest["l"] = latest["low"]
    latest["liveMerged"] = True
    return True


def normalize_candle(row: list) -> Optional[Dict[str, float]]:
    """Normalize KuCoin candle row into internal candle dict."""
    if not row or len(row) < 6:
        return None
    try:
        ts_sec = int(float(row[0]))
        return {
            "tsSec": ts_sec,
            "t": ts_sec * 1000,
            "open": float(row[1]),
            "close": float(row[2]),
            "high": float(row[3]),
            "low": float(row[4]),
            "volume": float(row[5]),
            "turnover": float(row[6]) if len(row) > 6 else 0.0,
            "o": float(row[1]),
            "c": float(row[2]),
            "h": float(row[3]),
            "l": float(row[4]),
            "v": float(row[5]),
        }
    except (IndexError, ValueError, TypeError):
        return None


def _classify_ma_trend(close: float, sma20: Optional[float], sma60: Optional[float]) -> str:
    if sma20 is None:
        return "neutral"
    if sma60 is not None:
        if close > sma20 > sma60:
            return "bullish"
        if close < sma20 < sma60:
            return "bearish"
    return "weak_bullish" if close > sma20 else "weak_bearish"


def analyze_candles(candles: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Compute trend, RSI, MACD, Bollinger Bands, ATR and breakout signals.

    该函数是 dashboard / agent 共用的统一市场分析入口，避免 API 层重复实现指标。
    """
    if len(candles) < 20:
        return None

    ohlcv = extract_ohlcv(candles)
    opens = ohlcv["open"]
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

    macd_values = macd(closes)
    macd_line = macd_values["macd"][-1] if macd_values["macd"] else None
    macd_signal = macd_values["signal"][-1] if macd_values["signal"] else None
    macd_hist = macd_values["histogram"][-1] if macd_values["histogram"] else None

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
        "open": opens[-1] if opens else None,
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
        "macd": round(macd_line, 8) if macd_line is not None else None,
        "macdSignal": round(macd_signal, 8) if macd_signal is not None else None,
        "macdHistogram": round(macd_hist, 8) if macd_hist is not None else None,
        "regime": regime,
        "breakout": breakout,
    }
