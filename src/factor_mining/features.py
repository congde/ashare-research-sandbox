"""Point-in-time feature matrix from OHLCV + pre-computed indicators."""

from __future__ import annotations

import math
from typing import Any, Literal

from backtest.rolling.indicators import compute_all_indicators

MiningTarget = Literal["return", "risk"]
RiskKind = Literal["abs_ret", "realized_vol"]


def _pct_change(values: list[float], lag: int) -> list[float | None]:
    n = len(values)
    out: list[float | None] = [None] * n
    for i in range(lag, n):
        prev = values[i - lag]
        if prev and prev != 0:
            out[i] = (values[i] - prev) / prev
    return out


def _ratio(numer: list[float | None], denom: list[float | None]) -> list[float | None]:
    n = len(numer)
    out: list[float | None] = [None] * n
    for i in range(n):
        a, b = numer[i], denom[i]
        if a is None or b is None or b == 0:
            continue
        out[i] = a / b - 1.0
    return out


def _forward_returns(closes: list[float], horizon: int) -> list[float | None]:
    n = len(closes)
    out: list[float | None] = [None] * n
    for i in range(n):
        j = i + horizon
        if j >= n:
            continue
        base = closes[i]
        if base and base != 0:
            out[i] = (closes[j] - base) / base
    return out


def _forward_abs_return(closes: list[float], horizon: int) -> list[float | None]:
    return [
        abs(value) if value is not None else None
        for value in _forward_returns(closes, horizon)
    ]


def _forward_realized_vol(closes: list[float], horizon: int) -> list[float | None]:
    """Std of bar returns over the next `horizon` bars (point-in-time risk proxy)."""
    n = len(closes)
    bar_rets = _pct_change(closes, 1)
    out: list[float | None] = [None] * n
    h = max(1, horizon)
    for i in range(n):
        chunk = [
            float(r)
            for r in bar_rets[i + 1 : i + h + 1]
            if r is not None and math.isfinite(r)
        ]
        if len(chunk) < 2:
            continue
        mean = sum(chunk) / len(chunk)
        var = sum((r - mean) ** 2 for r in chunk) / (len(chunk) - 1)
        out[i] = math.sqrt(var)
    return out


def _build_labels(
    closes: list[float],
    *,
    horizon: int,
    target: MiningTarget,
    risk_kind: RiskKind,
) -> tuple[list[float | None], str]:
    h = max(1, min(10, horizon))
    if target == "return":
        return _forward_returns(closes, h), f"forward_{h}bar_return"
    if risk_kind == "realized_vol":
        return _forward_realized_vol(closes, h), f"forward_{h}bar_realized_vol"
    return _forward_abs_return(closes, h), f"forward_{h}bar_abs_return"


def build_feature_matrix(
    candles: list[dict[str, Any]],
    *,
    horizon: int = 1,
    target: MiningTarget = "return",
    risk_kind: RiskKind = "abs_ret",
) -> tuple[dict[str, list[float | None]], list[float | None], list[str]]:
    """Build lag-safe features and labels (return or risk) aligned by bar index."""
    if len(candles) < 30:
        raise ValueError(f"需要至少 30 根 K 线构建特征，当前 {len(candles)}")

    closes = [float(c["close"]) for c in candles]
    volumes = [float(c.get("volume") or 1.0) for c in candles]
    indicators = compute_all_indicators(candles)

    features: dict[str, list[float | None]] = {
        "ret_1": _pct_change(closes, 1),
        "ret_5": _pct_change(closes, 5),
        "ret_10": _pct_change(closes, 10),
        "vol_ratio": [float(v) for v in indicators.vol_ratio],
        "range_pos": [float(v) for v in indicators.range_pos],
        "rsi": list(indicators.rsi),
        "bb_pct_b": list(indicators.bb_pct_b),
        "atr_pct": list(indicators.atr_pct),
        "macd_hist": list(indicators.macd_histogram),
        "close_sma20": _ratio(closes, indicators.sma20),
        "close_sma60": _ratio(closes, indicators.sma60),
        "log_volume": [
            math.log(v) if v and v > 0 else None for v in volumes
        ],
    }

    labels, _ = _build_labels(closes, horizon=horizon, target=target, risk_kind=risk_kind)
    names = sorted(features.keys())
    return features, labels, names
