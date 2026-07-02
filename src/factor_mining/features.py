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


def _rolling_mean(values: list[float | None], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for i in range(len(values)):
        start = max(0, i - window + 1)
        chunk = [float(v) for v in values[start : i + 1] if v is not None and math.isfinite(v)]
        if len(chunk) >= max(2, window // 3):
            out[i] = sum(chunk) / len(chunk)
    return out


def _rolling_std(values: list[float | None], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for i in range(len(values)):
        start = max(0, i - window + 1)
        chunk = [float(v) for v in values[start : i + 1] if v is not None and math.isfinite(v)]
        if len(chunk) < max(3, window // 3):
            continue
        mean = sum(chunk) / len(chunk)
        var = sum((v - mean) ** 2 for v in chunk) / max(1, len(chunk) - 1)
        out[i] = math.sqrt(var)
    return out


def _rolling_zscore(values: list[float | None], window: int) -> list[float | None]:
    means = _rolling_mean(values, window)
    stds = _rolling_std(values, window)
    out: list[float | None] = [None] * len(values)
    for i, value in enumerate(values):
        mean, std = means[i], stds[i]
        if value is None or mean is None or std is None or std <= 1e-12:
            continue
        out[i] = (float(value) - mean) / std
    return out


def _diff(a: list[float | None], b: list[float | None]) -> list[float | None]:
    out: list[float | None] = [None] * len(a)
    for i in range(len(a)):
        if a[i] is None or b[i] is None:
            continue
        out[i] = float(a[i]) - float(b[i])
    return out


def _mul(a: list[float | None], b: list[float | None]) -> list[float | None]:
    out: list[float | None] = [None] * len(a)
    for i in range(len(a)):
        if a[i] is None or b[i] is None:
            continue
        out[i] = float(a[i]) * float(b[i])
    return out


def _safe_ratio(a: list[float | None], b: list[float | None]) -> list[float | None]:
    out: list[float | None] = [None] * len(a)
    for i in range(len(a)):
        if a[i] is None or b[i] is None or abs(float(b[i])) < 1e-12:
            continue
        out[i] = float(a[i]) / float(b[i])
    return out


def _rolling_min(values: list[float | None], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for i in range(len(values)):
        start = max(0, i - window + 1)
        chunk = [float(v) for v in values[start : i + 1] if v is not None and math.isfinite(v)]
        if len(chunk) >= max(2, window // 3):
            out[i] = min(chunk)
    return out


def _rolling_max(values: list[float | None], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for i in range(len(values)):
        start = max(0, i - window + 1)
        chunk = [float(v) for v in values[start : i + 1] if v is not None and math.isfinite(v)]
        if len(chunk) >= max(2, window // 3):
            out[i] = max(chunk)
    return out


def _signed_abs(values: list[float | None]) -> list[float | None]:
    return [abs(float(v)) if v is not None else None for v in values]


def _clip(values: list[float | None], low: float, high: float) -> list[float | None]:
    out: list[float | None] = []
    for value in values:
        if value is None:
            out.append(None)
        else:
            out.append(max(low, min(high, float(value))))
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
    opens = [float(c["open"]) for c in candles]
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    indicators = compute_all_indicators(candles)

    ret_1 = _pct_change(closes, 1)
    ret_2 = _pct_change(closes, 2)
    ret_3 = _pct_change(closes, 3)
    ret_5 = _pct_change(closes, 5)
    ret_10 = _pct_change(closes, 10)
    ret_20 = _pct_change(closes, 20)
    ret_40 = _pct_change(closes, 40)
    abs_ret_1 = _signed_abs(ret_1)
    abs_ret_5 = _signed_abs(ret_5)
    log_volume = [math.log(v) if v and v > 0 else None for v in volumes]
    dollar_volume = [
        math.log(max(1e-9, c * v)) if c > 0 and v > 0 else None
        for c, v in zip(closes, volumes)
    ]
    intraday_range = [
        (float(c["high"]) - float(c["low"])) / float(c["close"])
        if float(c["close"]) != 0
        else None
        for c in candles
    ]
    candle_body = [
        (float(c["close"]) - float(c["open"])) / float(c["open"])
        if float(c["open"]) != 0
        else None
        for c in candles
    ]
    upper_shadow = [
        (highs[i] - max(opens[i], closes[i])) / closes[i] if closes[i] else None
        for i in range(len(candles))
    ]
    lower_shadow = [
        (min(opens[i], closes[i]) - lows[i]) / closes[i] if closes[i] else None
        for i in range(len(candles))
    ]
    close_to_high = [
        (closes[i] - lows[i]) / (highs[i] - lows[i]) if highs[i] != lows[i] else 0.5
        for i in range(len(candles))
    ]
    volume_z20 = _rolling_zscore(log_volume, 20)
    dollar_volume_z20 = _rolling_zscore(dollar_volume, 20)
    atr_z20 = _rolling_zscore(list(indicators.atr_pct), 20)
    range_z20 = _rolling_zscore(intraday_range, 20)
    body_z20 = _rolling_zscore(candle_body, 20)
    ret_1_z20 = _rolling_zscore(ret_1, 20)
    ret_5_z20 = _rolling_zscore(ret_5, 20)
    ret_vol_10 = _rolling_std(ret_1, 10)
    ret_vol_20 = _rolling_std(ret_1, 20)
    vol_of_vol = _rolling_zscore(ret_vol_10, 20)
    high_20 = _rolling_max(highs, 20)
    low_20 = _rolling_min(lows, 20)
    high_60 = _rolling_max(highs, 60)
    low_60 = _rolling_min(lows, 60)
    distance_high_20 = _ratio(closes, high_20)
    distance_low_20 = _ratio(closes, low_20)
    distance_high_60 = _ratio(closes, high_60)
    distance_low_60 = _ratio(closes, low_60)
    ema13_gap = _ratio(closes, indicators.ema13)
    ema55_gap = _ratio(closes, indicators.ema55)
    ema89_gap = _ratio(closes, indicators.ema89)
    ema13_55_spread = _diff(_ratio(closes, indicators.ema13), _ratio(closes, indicators.ema55))
    plus_minus_di = _diff(indicators.plus_di, indicators.minus_di)
    adx_norm = [float(v) / 100.0 if v is not None else None for v in indicators.adx]
    support_distance = _ratio(closes, indicators.support)
    resistance_distance = _ratio(closes, indicators.resistance)
    overnight_gap = [
        opens[i] / closes[i - 1] - 1.0 if i > 0 and closes[i - 1] else None
        for i in range(len(candles))
    ]
    intrabar_return = [
        closes[i] / opens[i] - 1.0 if opens[i] else None for i in range(len(candles))
    ]
    efficiency_10 = _safe_ratio(ret_10, _rolling_mean(abs_ret_1, 10))
    efficiency_20 = _safe_ratio(ret_20, _rolling_mean(abs_ret_1, 20))
    volume_trend_5_20 = _ratio(_rolling_mean(volumes, 5), _rolling_mean(volumes, 20))

    features: dict[str, list[float | None]] = {
        "ret_1": ret_1,
        "ret_2": ret_2,
        "ret_3": ret_3,
        "ret_5": ret_5,
        "ret_10": ret_10,
        "ret_20": ret_20,
        "ret_40": ret_40,
        "ret_1_z20": ret_1_z20,
        "ret_5_z20": ret_5_z20,
        "abs_ret_1": abs_ret_1,
        "abs_ret_5": abs_ret_5,
        "ret_5_reversal": [-float(v) if v is not None else None for v in ret_5],
        "ret_20_reversal": [-float(v) if v is not None else None for v in ret_20],
        "ret_40_reversal": [-float(v) if v is not None else None for v in ret_40],
        "momentum_accel_5_20": _diff(ret_5, ret_20),
        "momentum_accel_10_40": _diff(ret_10, ret_40),
        "efficiency_10": _clip(efficiency_10, -5.0, 5.0),
        "efficiency_20": _clip(efficiency_20, -5.0, 5.0),
        "vol_ratio": [float(v) for v in indicators.vol_ratio],
        "volume_trend_5_20": volume_trend_5_20,
        "range_pos": [float(v) for v in indicators.range_pos],
        "rsi": list(indicators.rsi),
        "rsi_centered": [
            float(v) / 100.0 - 0.5 if v is not None else None for v in indicators.rsi
        ],
        "bb_pct_b": list(indicators.bb_pct_b),
        "bb_centered": [
            float(v) / 100.0 - 0.5 if v is not None else None for v in indicators.bb_pct_b
        ],
        "bb_width": list(indicators.bb_width),
        "bb_width_z20": _rolling_zscore(list(indicators.bb_width), 20),
        "atr_pct": list(indicators.atr_pct),
        "atr_z20": atr_z20,
        "macd_hist": list(indicators.macd_histogram),
        "macd_line": list(indicators.macd_line),
        "macd_signal_gap": _diff(indicators.macd_line, indicators.macd_signal),
        "adx": list(indicators.adx),
        "adx_norm": adx_norm,
        "plus_di": list(indicators.plus_di),
        "minus_di": list(indicators.minus_di),
        "plus_minus_di": plus_minus_di,
        "close_sma20": _ratio(closes, indicators.sma20),
        "close_sma60": _ratio(closes, indicators.sma60),
        "sma20_sma60_spread": _diff(_ratio(closes, indicators.sma20), _ratio(closes, indicators.sma60)),
        "ema13_gap": ema13_gap,
        "ema55_gap": ema55_gap,
        "ema89_gap": ema89_gap,
        "ema13_55_spread": ema13_55_spread,
        "log_volume": log_volume,
        "dollar_volume": dollar_volume,
        "volume_z20": volume_z20,
        "dollar_volume_z20": dollar_volume_z20,
        "intraday_range": intraday_range,
        "range_z20": range_z20,
        "candle_body": candle_body,
        "body_z20": body_z20,
        "upper_shadow": upper_shadow,
        "lower_shadow": lower_shadow,
        "shadow_balance": _diff(lower_shadow, upper_shadow),
        "close_to_high": close_to_high,
        "overnight_gap": overnight_gap,
        "intrabar_return": intrabar_return,
        "ret_vol_10": ret_vol_10,
        "ret_vol_20": ret_vol_20,
        "vol_of_vol": vol_of_vol,
        "distance_high_20": distance_high_20,
        "distance_low_20": distance_low_20,
        "distance_high_60": distance_high_60,
        "distance_low_60": distance_low_60,
        "support_distance": support_distance,
        "resistance_distance": resistance_distance,
        "momentum_volume": _mul(ret_5, volume_z20),
        "momentum_dollar_volume": _mul(ret_10, dollar_volume_z20),
        "reversal_volume": _mul([-float(v) if v is not None else None for v in ret_5], volume_z20),
        "trend_quality": _mul(_ratio(closes, indicators.sma20), [float(v) / 100.0 for v in indicators.range_pos]),
        "trend_strength": _mul(ema13_55_spread, adx_norm),
        "di_trend_quality": _mul(plus_minus_di, adx_norm),
        "vol_breakout": _mul(atr_z20, volume_z20),
        "squeeze_breakout": _mul(_rolling_zscore(list(indicators.bb_width), 20), ret_5),
        "range_volume_pressure": _mul(range_z20, volume_z20),
        "lower_shadow_reversal": _mul(lower_shadow, [-float(v) if v is not None else None for v in ret_3]),
        "upper_shadow_reversal": _mul(upper_shadow, ret_3),
    }

    labels, _ = _build_labels(closes, horizon=horizon, target=target, risk_kind=risk_kind)
    names = sorted(features.keys())
    return features, labels, names
