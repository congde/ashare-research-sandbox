"""Factor quality metrics — Spearman IC / IR without scipy."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class FactorMetrics:
    ic_mean: float
    ic_std: float
    ir: float
    hit_rate: float
    sample_count: int
    quintile_spread: float = 0.0
    turnover_rate: float = 0.0
    top_quintile_return: float = 0.0
    bottom_quintile_return: float = 0.0


def _rank_values(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return ranks


def spearman(x: Sequence[float], y: Sequence[float]) -> float:
    if len(x) < 3 or len(x) != len(y):
        return 0.0
    rx = _rank_values(list(x))
    ry = _rank_values(list(y))
    mx = sum(rx) / len(rx)
    my = sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den_x = math.sqrt(sum((a - mx) ** 2 for a in rx))
    den_y = math.sqrt(sum((b - my) ** 2 for b in ry))
    if den_x == 0 or den_y == 0:
        return 0.0
    return num / (den_x * den_y)


def _paired_rows(
    signal: Sequence[float | None],
    labels: Sequence[float | None],
) -> tuple[list[float], list[float]]:
    xs: list[float] = []
    ys: list[float] = []
    for a, b in zip(signal, labels):
        if a is None or b is None:
            continue
        if not math.isfinite(a) or not math.isfinite(b):
            continue
        xs.append(float(a))
        ys.append(float(b))
    return xs, ys


def _quintile_spread(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """Top-minus-bottom quintile mean forward return (single-series teaching proxy)."""
    if len(xs) < 10:
        return 0.0, 0.0, 0.0
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    bucket = max(1, len(order) // 5)
    bottom = order[:bucket]
    top = order[-bucket:]
    bottom_mean = sum(ys[i] for i in bottom) / len(bottom)
    top_mean = sum(ys[i] for i in top) / len(top)
    return top_mean - bottom_mean, top_mean, bottom_mean


def _turnover_rate(signal: Sequence[float | None]) -> float:
    """Share of bars where signal sign flips vs previous valid value."""
    prev: float | None = None
    flips = 0
    steps = 0
    for value in signal:
        if value is None or not math.isfinite(value):
            continue
        curr_sign = 1 if value > 0 else (-1 if value < 0 else 0)
        if prev is not None and curr_sign != prev:
            flips += 1
        if prev is not None:
            steps += 1
        prev = curr_sign
    return flips / steps if steps else 0.0


def evaluate_factor(
    signal: Sequence[float | None],
    labels: Sequence[float | None],
    *,
    min_samples: int = 20,
    rolling_window: int = 10,
) -> FactorMetrics | None:
    xs, ys = _paired_rows(signal, labels)
    if len(xs) < min_samples:
        return None

    ic = spearman(xs, ys)
    window = min(rolling_window, max(3, len(xs) // 2))
    rolling_ics: list[float] = []
    for start in range(0, len(xs) - window + 1):
        chunk_x = xs[start : start + window]
        chunk_y = ys[start : start + window]
        rolling_ics.append(spearman(chunk_x, chunk_y))

    ic_std = 0.0
    if len(rolling_ics) >= 2:
        mean_ic = sum(rolling_ics) / len(rolling_ics)
        ic_std = math.sqrt(sum((v - mean_ic) ** 2 for v in rolling_ics) / (len(rolling_ics) - 1))
    ir = ic / ic_std if ic_std > 1e-9 else 0.0

    hits = sum(1 for a, b in zip(xs, ys) if (a > 0 and b > 0) or (a < 0 and b < 0))
    hit_rate = hits / len(xs)
    spread, top_ret, bottom_ret = _quintile_spread(xs, ys)
    turnover = _turnover_rate(signal)

    return FactorMetrics(
        ic_mean=round(ic, 6),
        ic_std=round(ic_std, 6),
        ir=round(ir, 6),
        hit_rate=round(hit_rate, 6),
        sample_count=len(xs),
        quintile_spread=round(spread, 6),
        turnover_rate=round(turnover, 6),
        top_quintile_return=round(top_ret, 6),
        bottom_quintile_return=round(bottom_ret, 6),
    )


def chronological_split(n: int, train_ratio: float = 0.7) -> tuple[slice, slice]:
    if n < 2:
        return slice(0, n), slice(n, n)
    cut = max(1, min(n - 1, int(n * train_ratio)))
    return slice(0, cut), slice(cut, n)


def slice_series(values: Sequence[float | None], part: slice) -> list[float | None]:
    return list(values)[part]
