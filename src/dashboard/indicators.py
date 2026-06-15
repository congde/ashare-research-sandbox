from __future__ import annotations

from typing import Any


def sma(values: list[float], window: int) -> list[float | None]:
    out: list[float | None] = []
    for index in range(len(values)):
        if index + 1 < window:
            out.append(None)
            continue
        sample = values[index + 1 - window : index + 1]
        out.append(sum(sample) / len(sample))
    return out


def last_sma(values: list[float], window: int) -> float | None:
    series = sma(values, window)
    return series[-1] if series else None


def rsi(values: list[float], period: int = 14) -> list[float | None]:
    if len(values) < period + 1:
        return [None] * len(values)
    out: list[float | None] = [None] * len(values)
    gains: list[float] = []
    losses: list[float] = []
    for index in range(1, len(values)):
        delta = values[index] - values[index - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    if avg_loss == 0:
        out[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        out[period] = 100 - (100 / (1 + rs))

    for index in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[index]) / period
        avg_loss = (avg_loss * (period - 1) + losses[index]) / period
        if avg_loss == 0:
            out[index + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            out[index + 1] = 100 - (100 / (1 + rs))
    return out


def bollinger_bands(values: list[float], window: int = 20, mult: float = 2.0) -> dict[str, list[float | None]]:
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


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float | None]:
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
