# -*- coding: utf-8 -*-
"""
技术指标库。

纯 Python 实现核心量化指标，无 TA-Lib 依赖。
输入 candle 支持两类字段：
- KuCoin/dashboard 格式：open/high/low/close/volume
- 量化通用格式：o/h/l/c/v
"""

from __future__ import annotations

from typing import Optional


def ema(closes: list[float], period: int) -> list[float]:
    """Exponential Moving Average."""
    if not closes or period <= 0:
        return []
    k = 2.0 / (period + 1)
    result = [closes[0]]
    for i in range(1, len(closes)):
        result.append(closes[i] * k + result[-1] * (1 - k))
    return result


def sma(closes: list[float], period: int) -> list[float]:
    """Simple Moving Average."""
    if not closes or period <= 0:
        return []
    result: list[float] = []
    for i in range(len(closes)):
        if i < period - 1:
            result.append(sum(closes[: i + 1]) / (i + 1))
        else:
            result.append(sum(closes[i - period + 1: i + 1]) / period)
    return result


def last_sma(values: list[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def rolling_stdev(values: list[float], period: int) -> list[float]:
    if not values or period <= 0:
        return []
    result: list[float] = []
    for i in range(len(values)):
        window = values[max(0, i - period + 1): i + 1]
        mean = sum(window) / len(window)
        result.append((sum((x - mean) ** 2 for x in window) / len(window)) ** 0.5)
    return result


def last_stdev(values: list[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    window = values[-period:]
    mean = sum(window) / period
    return (sum((v - mean) ** 2 for v in window) / period) ** 0.5


def rsi(closes: list[float], period: int = 14) -> list[float]:
    """Relative Strength Index (Wilder smoothing)."""
    if len(closes) < 2:
        return [50.0] * len(closes)

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0) for d in deltas]
    losses = [max(-d, 0) for d in deltas]

    result = [50.0]
    if len(gains) < period:
        avg_gain = sum(gains) / max(len(gains), 1)
        avg_loss = sum(losses) / max(len(losses), 1)
    else:
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

    for i in range(len(gains)):
        if i < period:
            avg_gain_i = sum(gains[: i + 1]) / (i + 1)
            avg_loss_i = sum(losses[: i + 1]) / (i + 1)
        elif i == period:
            avg_gain_i = avg_gain
            avg_loss_i = avg_loss
        else:
            avg_gain_i = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss_i = (avg_loss * (period - 1) + losses[i]) / period
            avg_gain = avg_gain_i
            avg_loss = avg_loss_i

        if avg_loss_i == 0:
            result.append(100.0)
        else:
            rs = avg_gain_i / avg_loss_i
            result.append(100.0 - 100.0 / (1.0 + rs))

    return result


def macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> dict:
    """MACD: returns {macd, signal, histogram}."""
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = ema(macd_line, signal_period)
    histogram = [m - s for m, s in zip(macd_line, signal_line)]
    return {"macd": macd_line, "signal": signal_line, "histogram": histogram}


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float]:
    """Average True Range."""
    if len(closes) < 2:
        return [0.0] * len(closes)

    true_ranges = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        true_ranges.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        ))
    return ema(true_ranges, period)


def bollinger_bands(closes: list[float], period: int = 20, std_dev: float = 2.0) -> dict:
    """Bollinger Bands: returns {upper, middle, lower}."""
    middle = sma(closes, period)
    upper: list[float] = []
    lower: list[float] = []

    for i in range(len(closes)):
        window_size = min(i + 1, period)
        window = closes[max(0, i - window_size + 1): i + 1]
        mean = middle[i]
        variance = sum((x - mean) ** 2 for x in window) / max(window_size, 1)
        std = variance ** 0.5
        upper.append(mean + std_dev * std)
        lower.append(mean - std_dev * std)

    return {"upper": upper, "middle": middle, "lower": lower}


def find_swing_high(highs: list[float], lookback: int = 5) -> Optional[float]:
    """Find the most recent swing high within the lookback window."""
    if len(highs) < lookback * 2 + 1:
        return max(highs) if highs else None

    for i in range(len(highs) - 1, lookback - 1, -1):
        is_swing = True
        for j in range(1, lookback + 1):
            left = i - j if i - j >= 0 else 0
            right = i + j if i + j < len(highs) else len(highs) - 1
            if highs[i] < highs[left] or highs[i] < highs[right]:
                is_swing = False
                break
        if is_swing:
            return highs[i]
    return max(highs[-lookback * 2:]) if len(highs) >= lookback * 2 else max(highs)


def find_swing_low(lows: list[float], lookback: int = 5) -> Optional[float]:
    """Find the most recent swing low within the lookback window."""
    if len(lows) < lookback * 2 + 1:
        return min(lows) if lows else None

    for i in range(len(lows) - 1, lookback - 1, -1):
        is_swing = True
        for j in range(1, lookback + 1):
            left = i - j if i - j >= 0 else 0
            right = i + j if i + j < len(lows) else len(lows) - 1
            if lows[i] > lows[left] or lows[i] > lows[right]:
                is_swing = False
                break
        if is_swing:
            return lows[i]
    return min(lows[-lookback * 2:]) if len(lows) >= lookback * 2 else min(lows)


def determine_trend(closes: list[float], ema_period: int = 50) -> str:
    """Determine trend based on EMA and price position."""
    if len(closes) < ema_period:
        return "neutral"
    ema_values = ema(closes, ema_period)
    current_price = closes[-1]
    current_ema = ema_values[-1]
    prev_ema = ema_values[-2] if len(ema_values) > 1 else current_ema

    if current_price > current_ema and current_ema > prev_ema:
        return "bullish"
    if current_price < current_ema and current_ema < prev_ema:
        return "bearish"
    return "neutral"


def extract_ohlcv(candles: list[dict]) -> dict:
    """Extract OHLCV arrays from candle dicts."""
    opens = [float(c.get("o", c.get("open", 0))) for c in candles]
    highs = [float(c.get("h", c.get("high", 0))) for c in candles]
    lows = [float(c.get("l", c.get("low", 0))) for c in candles]
    closes = [float(c.get("c", c.get("close", 0))) for c in candles]
    volumes = [float(c.get("v", c.get("volume", 0))) for c in candles]
    return {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes}


def compute_indicators(candles: list[dict]) -> dict:
    """Compute a full indicator suite from candle data."""
    ohlcv = extract_ohlcv(candles)
    closes = ohlcv["close"]
    highs = ohlcv["high"]
    lows = ohlcv["low"]

    return {
        "ema20": ema(closes, 20),
        "ema50": ema(closes, 50),
        "ema200": ema(closes, 200),
        "sma20": sma(closes, 20),
        "sma60": sma(closes, 60),
        "rsi14": rsi(closes, 14),
        "macd": macd(closes),
        "atr14": atr(highs, lows, closes, 14),
        "bbands": bollinger_bands(closes, 20, 2.0),
        "swing_high": find_swing_high(highs),
        "swing_low": find_swing_low(lows),
        "trend": determine_trend(closes),
        "last_close": closes[-1] if closes else None,
        "last_volume": ohlcv["volume"][-1] if ohlcv["volume"] else None,
    }
