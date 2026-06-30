#!/usr/bin/env python3
"""Regenerate deterministic teaching sample data/prices.csv."""

from __future__ import annotations

import csv
import math
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "prices.csv"

START = date(2025, 1, 2)
END = date(2026, 6, 18)


def trading_days(start: date, end: date):
    current = start
    while current <= end:
        if current.weekday() < 5:
            yield current
        current += timedelta(days=1)


def close_price(index: int) -> float:
    base = 8.20 + index * 0.0165
    cycle1 = 1.15 * math.sin(index * 0.062)
    cycle2 = 0.55 * math.sin(index * 0.185 + 0.9)
    cycle3 = 0.25 * math.sin(index * 0.41 + 2.1)
    correction = -1.05 * max(0.0, math.sin(index * 0.038 - 1.2)) ** 2
    shock = 0.35 * math.sin(index * 0.97 + 4.2) * (0.5 + 0.5 * math.sin(index * 0.013))
    return round(max(4.5, base + cycle1 + cycle2 + cycle3 + correction + shock), 2)


def main() -> int:
    rows: list[tuple[str, str]] = []
    for index, day in enumerate(trading_days(START, END)):
        rows.append((day.isoformat(), f"{close_price(index):.2f}"))

    with OUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "close"])
        writer.writerows(rows)

    print(f"wrote {len(rows)} rows to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
