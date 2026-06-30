from __future__ import annotations

from typing import Any


def rolling_sma(values: list[float], period: int) -> list[float | None]:
    """O(n) SMA using a running sum."""
    n = len(values)
    result: list[float | None] = [None] * n
    if n < period:
        return result
    running = sum(values[:period])
    result[period - 1] = running / period
    for index in range(period, n):
        running += values[index] - values[index - period]
        result[index] = running / period
    return result


def rolling_rsi(closes: list[float], period: int = 14) -> list[float | None]:
    """O(n) RSI with Wilder smoothing."""
    n = len(closes)
    result: list[float | None] = [None] * n
    if n < period + 1:
        return result

    gains: list[float] = []
    losses: list[float] = []
    for index in range(1, n):
        diff = closes[index] - closes[index - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    if avg_loss == 0:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100.0 - (100.0 / (1.0 + rs))

    for index in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[index]) / period
        avg_loss = (avg_loss * (period - 1) + losses[index]) / period
        if avg_loss == 0:
            result[index + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[index + 1] = 100.0 - (100.0 / (1.0 + rs))

    return result


def sma(values: list[float], window: int) -> list[float | None]:
    return rolling_sma(values, window)


def last_sma(values: list[float], window: int) -> float | None:
    series = sma(values, window)
    return series[-1] if series else None


def rsi(values: list[float], period: int = 14) -> list[float | None]:
    return rolling_rsi(values, period)


def bollinger_bands(
    values: list[float],
    window: int = 20,
    mult: float = 2.0,
) -> dict[str, list[float | None]]:
    middle = sma(values, window)
    upper: list[float | None] = []
    lower: list[float | None] = []
    for index, mid in enumerate(middle):
        if mid is None or index + 1 < window:
            upper.append(None)
            lower.append(None)
            continue
        sample = values[index + 1 - window : index + 1]
        mean = sum(sample) / len(sample)
        variance = sum((item - mean) ** 2 for item in sample) / len(sample)
        std = variance**0.5
        upper.append(mid + mult * std)
        lower.append(mid - mult * std)
    return {"upper": upper, "middle": middle, "lower": lower}


def atr(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> list[float | None]:
    trs: list[float] = []
    for index in range(len(closes)):
        if index == 0:
            trs.append(highs[index] - lows[index])
        else:
            tr = max(
                highs[index] - lows[index],
                abs(highs[index] - closes[index - 1]),
                abs(lows[index] - closes[index - 1]),
            )
            trs.append(tr)
    return sma(trs, period)


def extract_ohlcv(candles: list[dict[str, Any]]) -> dict[str, list[float]]:
    opens, highs, lows, closes, volumes = [], [], [], [], []
    for item in candles:
        opens.append(float(item.get("open") or item.get("o") or 0))
        highs.append(float(item.get("high") or item.get("h") or 0))
        lows.append(float(item.get("low") or item.get("l") or 0))
        closes.append(float(item.get("close") or item.get("c") or 0))
        volumes.append(float(item.get("volume") or item.get("v") or 0))
    return {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes}
