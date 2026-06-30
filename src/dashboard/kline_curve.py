from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def sma_at_index(values: list[float], index: int, window: int) -> float | None:
    if window <= 0 or index + 1 < window:
        return None
    sample = values[index + 1 - window : index + 1]
    return sum(sample) / len(sample)


def candles_to_curve(
    candles: list[dict[str, Any]],
    *,
    short: int = 3,
    long: int = 7,
) -> list[dict[str, Any]]:
    closes = [float(item["close"]) for item in candles]
    curve: list[dict[str, Any]] = []
    for index, candle in enumerate(candles):
        curve.append(
            {
                "date": candle["date"],
                "close": candle["close"],
                "equity": candle["close"],
                "short_ma": sma_at_index(closes, index, short),
                "long_ma": sma_at_index(closes, index, long),
            }
        )
    return curve


def kline_payload_to_curve(
    candles: list[Any],
    *,
    short: int,
    long: int,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in candles:
        if isinstance(item, dict):
            close = float(item.get("close") or item.get("c") or 0)
            ts = item.get("date") or item.get("time")
            if isinstance(ts, (int, float)):
                ts = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
            normalized.append({"date": str(ts), "close": close, "equity": close})
    if not normalized:
        return []
    closes = [float(row["close"]) for row in normalized]
    curve: list[dict[str, Any]] = []
    for index, row in enumerate(normalized):
        curve.append(
            {
                **row,
                "short_ma": sma_at_index(closes, index, short),
                "long_ma": sma_at_index(closes, index, long),
            }
        )
    return curve
