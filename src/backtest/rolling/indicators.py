# -*- coding: utf-8 -*-
"""
Incremental technical indicators — O(n) single-pass computation.

Replaces the O(n²) pattern where analyze_candles(candles[:idx+1]) was called
for every candle.  All indicators are pre-computed in a single forward pass
and stored as arrays indexed by candle position.

Analogous to Claude Code's prefetch pattern — compute once upfront so the
hot loop (engine iteration) does O(1) lookups.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ta.core import rolling_rsi as _rolling_rsi, rolling_sma as _rolling_sma


@dataclass
class IndicatorSeries:
    """Pre-computed indicator arrays aligned to candle indices."""
    sma20: List[Optional[float]] = field(default_factory=list)
    sma60: List[Optional[float]] = field(default_factory=list)
    rsi: List[Optional[float]] = field(default_factory=list)
    bb_upper: List[Optional[float]] = field(default_factory=list)
    bb_lower: List[Optional[float]] = field(default_factory=list)
    bb_width: List[Optional[float]] = field(default_factory=list)
    bb_pct_b: List[Optional[float]] = field(default_factory=list)
    atr: List[Optional[float]] = field(default_factory=list)
    atr_pct: List[Optional[float]] = field(default_factory=list)
    trend: List[str] = field(default_factory=list)
    regime: List[str] = field(default_factory=list)
    breakout: List[str] = field(default_factory=list)
    vol_ratio: List[float] = field(default_factory=list)
    range_pos: List[float] = field(default_factory=list)
    support: List[float] = field(default_factory=list)
    resistance: List[float] = field(default_factory=list)
    # MACD indicators
    macd_line: List[Optional[float]] = field(default_factory=list)
    macd_signal: List[Optional[float]] = field(default_factory=list)
    macd_histogram: List[Optional[float]] = field(default_factory=list)
    # ADX / trend EMAs (Qbot adx_strategy.py)
    adx: List[Optional[float]] = field(default_factory=list)
    plus_di: List[Optional[float]] = field(default_factory=list)
    minus_di: List[Optional[float]] = field(default_factory=list)
    ema13: List[Optional[float]] = field(default_factory=list)
    ema55: List[Optional[float]] = field(default_factory=list)
    ema89: List[Optional[float]] = field(default_factory=list)


def compute_all_indicators(candles: List[Dict[str, Any]]) -> IndicatorSeries:
    """Compute all indicator series in a single O(n) forward pass.

    Args:
        candles: sorted K-line dicts with keys: open, high, low, close, volume, tsSec

    Returns:
        IndicatorSeries with arrays aligned to candle indices.
    """
    n = len(candles)
    if n == 0:
        return IndicatorSeries()

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    volumes = [c["volume"] for c in candles]

    # --- SMA (running sum) ---
    sma20 = _rolling_sma(closes, 20)
    sma60 = _rolling_sma(closes, 60)

    # --- RSI (Wilder smoothing, single pass) ---
    rsi_series = _rolling_rsi(closes, 14)

    # --- Bollinger Bands (20-period, 2 std) ---
    bb_upper, bb_lower, bb_width, bb_pct_b = _rolling_bollinger(closes, 20, 2.0)

    # --- ATR (14-period, Wilder smoothing) ---
    atr_series, atr_pct_series = _rolling_atr(candles, 14)

    # --- Volume ratio (5-bar recent vs 20-bar average) ---
    vol_ratio_series = _rolling_vol_ratio(volumes, 5, 20)

    # --- Support / Resistance / Range position (20-bar lookback) ---
    support_s, resistance_s, range_pos_s = _rolling_support_resistance(candles, 20)

    # --- Trend classification ---
    trend_series = _classify_trend_series(closes, sma20, sma60)

    # --- Breakout detection ---
    breakout_series = _detect_breakout_series(candles, highs, lows, vol_ratio_series, 20)

    # --- Regime detection ---
    regime_series = _classify_regime_series(bb_width, atr_pct_series)

    # --- MACD (12, 26, 9) ---
    macd_line, macd_signal, macd_hist = _rolling_macd(closes, 12, 26, 9)

    # --- ADX (14) and Qbot EMA stack (13 / 55 / 89) ---
    adx_series, plus_di, minus_di = _rolling_adx(highs, lows, closes, 14)
    ema13 = _rolling_ema(closes, 13)
    ema55 = _rolling_ema(closes, 55)
    ema89 = _rolling_ema(closes, 89)

    return IndicatorSeries(
        sma20=sma20, sma60=sma60, rsi=rsi_series,
        bb_upper=bb_upper, bb_lower=bb_lower,
        bb_width=bb_width, bb_pct_b=bb_pct_b,
        atr=atr_series, atr_pct=atr_pct_series,
        trend=trend_series, regime=regime_series,
        breakout=breakout_series,
        vol_ratio=vol_ratio_series,
        range_pos=range_pos_s,
        support=support_s, resistance=resistance_s,
        macd_line=macd_line, macd_signal=macd_signal,
        macd_histogram=macd_hist,
        adx=adx_series, plus_di=plus_di, minus_di=minus_di,
        ema13=ema13, ema55=ema55, ema89=ema89,
    )


def get_analysis_at(indicators: IndicatorSeries, idx: int) -> Optional[Dict[str, Any]]:
    """Get the analysis dict for a specific candle index (matches dashboard_service.analyze_candles output)."""
    if idx < 0 or idx >= len(indicators.trend):
        return None
    return {
        "trend": indicators.trend[idx],
        "sma20": indicators.sma20[idx],
        "sma60": indicators.sma60[idx],
        "rsi": round(indicators.rsi[idx], 1) if indicators.rsi[idx] is not None else None,
        "bbUpper": round(indicators.bb_upper[idx], 6) if indicators.bb_upper[idx] is not None else None,
        "bbLower": round(indicators.bb_lower[idx], 6) if indicators.bb_lower[idx] is not None else None,
        "bbWidth": round(indicators.bb_width[idx], 2) if indicators.bb_width[idx] is not None else None,
        "bbPctB": round(indicators.bb_pct_b[idx], 1) if indicators.bb_pct_b[idx] is not None else None,
        "atr": round(indicators.atr[idx], 6) if indicators.atr[idx] is not None else None,
        "atrPct": round(indicators.atr_pct[idx], 2) if indicators.atr_pct[idx] is not None else None,
        "regime": indicators.regime[idx],
        "breakout": indicators.breakout[idx],
        "volRatio": round(indicators.vol_ratio[idx], 2),
        "rangePos": round(indicators.range_pos[idx], 1),
        "support": indicators.support[idx],
        "resistance": indicators.resistance[idx],
        "macdLine": round(indicators.macd_line[idx], 6) if indicators.macd_line[idx] is not None else None,
        "macdSignal": round(indicators.macd_signal[idx], 6) if indicators.macd_signal[idx] is not None else None,
        "macdHistogram": round(indicators.macd_histogram[idx], 6) if indicators.macd_histogram[idx] is not None else None,
        "adx": round(indicators.adx[idx], 2) if indicators.adx[idx] is not None else None,
        "plusDi": round(indicators.plus_di[idx], 2) if indicators.plus_di[idx] is not None else None,
        "minusDi": round(indicators.minus_di[idx], 2) if indicators.minus_di[idx] is not None else None,
    }


# ===================================================================
# Internal computation helpers — all O(n)
# ===================================================================

def _rolling_bollinger(
    closes: List[float], period: int = 20, num_std: float = 2.0,
) -> tuple:
    """O(n) Bollinger Bands using running sum and sum-of-squares."""
    n = len(closes)
    upper: List[Optional[float]] = [None] * n
    lower: List[Optional[float]] = [None] * n
    width: List[Optional[float]] = [None] * n
    pct_b: List[Optional[float]] = [None] * n

    if n < period:
        return upper, lower, width, pct_b

    running_sum = 0.0
    running_sq = 0.0

    for i in range(period):
        running_sum += closes[i]
        running_sq += closes[i] ** 2

    for i in range(period - 1, n):
        if i >= period:
            old = closes[i - period]
            running_sum += closes[i] - old
            running_sq += closes[i] ** 2 - old ** 2

        mean = running_sum / period
        variance = running_sq / period - mean ** 2
        std = math.sqrt(max(0, variance))

        bb_u = mean + num_std * std
        bb_l = mean - num_std * std
        upper[i] = bb_u
        lower[i] = bb_l

        if mean > 0:
            width[i] = (bb_u - bb_l) / mean * 100
        else:
            width[i] = 0.0

        band_range = bb_u - bb_l
        if band_range > 0:
            pct_b[i] = (closes[i] - bb_l) / band_range * 100
        else:
            pct_b[i] = 50.0

    return upper, lower, width, pct_b


def _rolling_atr(candles: List[Dict], period: int = 14) -> tuple:
    """O(n) ATR with Wilder smoothing."""
    n = len(candles)
    atr_s: List[Optional[float]] = [None] * n
    atr_pct_s: List[Optional[float]] = [None] * n

    if n < period + 1:
        return atr_s, atr_pct_s

    trs: List[float] = [0.0]  # first candle has no previous
    for i in range(1, n):
        h = candles[i]["high"]
        l = candles[i]["low"]
        pc = candles[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))

    atr_val = sum(trs[1:period + 1]) / period
    atr_s[period] = atr_val
    c = candles[period]["close"]
    atr_pct_s[period] = (atr_val / c * 100) if c > 0 else None

    for i in range(period + 1, n):
        atr_val = (atr_val * (period - 1) + trs[i]) / period
        atr_s[i] = atr_val
        c = candles[i]["close"]
        atr_pct_s[i] = (atr_val / c * 100) if c > 0 else None

    return atr_s, atr_pct_s


def _rolling_vol_ratio(volumes: List[float], short: int = 5, long: int = 20) -> List[float]:
    """O(n) volume ratio (short ma / long ma)."""
    n = len(volumes)
    result = [1.0] * n
    short_sum = 0.0
    long_sum = 0.0

    for i in range(n):
        short_sum += volumes[i]
        long_sum += volumes[i]
        if i >= short:
            short_sum -= volumes[i - short]
        if i >= long:
            long_sum -= volumes[i - long]

        short_count = min(i + 1, short)
        long_count = min(i + 1, long)
        short_avg = short_sum / short_count
        long_avg = long_sum / long_count
        result[i] = short_avg / long_avg if long_avg > 0 else 1.0

    return result


def _rolling_support_resistance(
    candles: List[Dict], lookback: int = 20,
) -> tuple:
    """O(n) support/resistance using a rolling min/max deque approach (simplified)."""
    from collections import deque
    n = len(candles)
    support = [0.0] * n
    resistance = [0.0] * n
    range_pos = [50.0] * n

    min_deque: deque = deque()  # (value, index) — monotonic increasing
    max_deque: deque = deque()  # (value, index) — monotonic decreasing

    for i in range(n):
        low_val = candles[i]["low"]
        high_val = candles[i]["high"]
        close_val = candles[i]["close"]

        # Remove elements outside the window
        while min_deque and min_deque[0][1] <= i - lookback:
            min_deque.popleft()
        while max_deque and max_deque[0][1] <= i - lookback:
            max_deque.popleft()

        # Maintain monotonic deques
        while min_deque and min_deque[-1][0] >= low_val:
            min_deque.pop()
        min_deque.append((low_val, i))

        while max_deque and max_deque[-1][0] <= high_val:
            max_deque.pop()
        max_deque.append((high_val, i))

        sup = min_deque[0][0]
        res = max_deque[0][0]
        support[i] = sup
        resistance[i] = res
        rng = res - sup
        range_pos[i] = (close_val - sup) / rng * 100 if rng > 0 else 50.0

    return support, resistance, range_pos


def _classify_trend_series(
    closes: List[float],
    sma20: List[Optional[float]],
    sma60: List[Optional[float]],
) -> List[str]:
    """Classify trend at each candle."""
    n = len(closes)
    result = ["unknown"] * n
    for i in range(n):
        s20 = sma20[i]
        s60 = sma60[i]
        if s20 is None:
            result[i] = "unknown"
            continue
        close = closes[i]
        if s60 is not None:
            if close > s20 and s20 > s60:
                result[i] = "bullish"
            elif close < s20 and s20 < s60:
                result[i] = "bearish"
            else:
                result[i] = "weak_bullish" if close > s20 else "weak_bearish"
        else:
            result[i] = "weak_bullish" if close > s20 else "weak_bearish"
    return result


def _detect_breakout_series(
    candles: List[Dict],
    highs: List[float],
    lows: List[float],
    vol_ratio: List[float],
    lookback: int = 20,
) -> List[str]:
    """Detect breakouts by close beyond previous-bar range with volume surge."""
    n = len(candles)
    result = ["none"] * n

    for i in range(lookback + 1, n):
        prev_high = max(highs[i - lookback - 1:i - 1]) if i > lookback else highs[max(0, i - 2)]
        prev_low = min(lows[i - lookback - 1:i - 1]) if i > lookback else lows[max(0, i - 2)]
        close = candles[i]["close"]
        vr = vol_ratio[i]

        if close > prev_high and vr >= 1.3:
            result[i] = "bullish"
        elif close < prev_low and vr >= 1.3:
            result[i] = "bearish"

    return result


def _classify_regime_series(
    bb_width: List[Optional[float]],
    atr_pct: List[Optional[float]],
) -> List[str]:
    """Classify market regime: trending / ranging / transitional."""
    n = len(bb_width)
    result = ["unknown"] * n
    for i in range(n):
        bw = bb_width[i]
        ap = atr_pct[i]
        if bw is None or ap is None:
            continue
        if bw < 3.0 and ap < 1.5:
            result[i] = "ranging"
        elif bw > 6.0 or ap > 3.0:
            result[i] = "trending"
        else:
            result[i] = "transitional"
    return result


def _ema_series(values: List[float], period: int) -> List[float]:
    """Full-length EMA array (used internally by ADX)."""
    n = len(values)
    if n == 0:
        return []
    alpha = 2.0 / (period + 1)
    out = [values[0]]
    for i in range(1, n):
        out.append(alpha * values[i] + (1 - alpha) * out[-1])
    return out


def _rolling_ema(values: List[float], period: int) -> List[Optional[float]]:
    """O(n) EMA with None until `period` bars are available."""
    n = len(values)
    result: List[Optional[float]] = [None] * n
    if n < period:
        return result
    ema_vals = _ema_series(values, period)
    for i in range(period - 1, n):
        result[i] = ema_vals[i]
    return result


def _rolling_adx(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14,
) -> tuple:
    """O(n) ADX with +DI / -DI (Wilder-style EMA smoothing)."""
    n = len(closes)
    adx: List[Optional[float]] = [None] * n
    plus_di: List[Optional[float]] = [None] * n
    minus_di: List[Optional[float]] = [None] * n

    if n < period + 1:
        return adx, plus_di, minus_di

    tr = [0.0] * n
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    for i in range(1, n):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        tr[i] = max(hl, hc, lc)
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move
        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move

    atr_ema = _ema_series(tr, period)
    plus_ema = _ema_series(plus_dm, period)
    minus_ema = _ema_series(minus_dm, period)

    dx = [0.0] * n
    for i in range(period, n):
        atr_val = max(atr_ema[i], 1e-10)
        pdi = 100.0 * plus_ema[i] / atr_val
        mdi = 100.0 * minus_ema[i] / atr_val
        plus_di[i] = pdi
        minus_di[i] = mdi
        denom = max(pdi + mdi, 1e-10)
        dx[i] = 100.0 * abs(pdi - mdi) / denom

    adx_ema = _ema_series(dx, period)
    warmup = period * 2 - 1
    for i in range(warmup, n):
        adx[i] = adx_ema[i]

    return adx, plus_di, minus_di


def _rolling_macd(
    closes: List[float],
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> tuple:
    """O(n) MACD computation using EMA."""
    n = len(closes)
    macd_line: List[Optional[float]] = [None] * n
    macd_signal: List[Optional[float]] = [None] * n
    macd_hist: List[Optional[float]] = [None] * n

    if n < slow:
        return macd_line, macd_signal, macd_hist

    alpha_fast = 2.0 / (fast + 1)
    alpha_slow = 2.0 / (slow + 1)
    alpha_sig = 2.0 / (signal_period + 1)

    ema_fast = closes[0]
    ema_slow = closes[0]
    sig_ema = None

    for i in range(n):
        ema_fast = alpha_fast * closes[i] + (1 - alpha_fast) * ema_fast
        ema_slow = alpha_slow * closes[i] + (1 - alpha_slow) * ema_slow

        if i >= slow - 1:
            ml = ema_fast - ema_slow
            macd_line[i] = ml

            if sig_ema is None:
                sig_ema = ml
            else:
                sig_ema = alpha_sig * ml + (1 - alpha_sig) * sig_ema

            if i >= slow - 1 + signal_period - 1:
                macd_signal[i] = sig_ema
                macd_hist[i] = ml - sig_ema

    return macd_line, macd_signal, macd_hist
