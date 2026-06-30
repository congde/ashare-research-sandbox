"""Shared Qbot-style signal rules for rolling-window strategies.

Reference lineage: vendor/Qbot (MIT) — sma_cross, boll_strategy_bt,
bitcoin_bt_example, adx_strategy.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

from backtest.rolling.indicators import IndicatorSeries
from backtest.rolling.models import Signal
from ta.core import bollinger_bands, rolling_sma


def crossed_up(prev_a: float, prev_b: float, cur_a: float, cur_b: float) -> bool:
    return prev_a <= prev_b and cur_a > cur_b


def crossed_down(prev_a: float, prev_b: float, cur_a: float, cur_b: float) -> bool:
    return prev_a >= prev_b and cur_a < cur_b


def long_only_cross_signal(
    *,
    crossed_up_flag: bool,
    crossed_down_flag: bool,
    entry_score: float = 50.0,
    exit_score: float = -50.0,
) -> Signal | None:
    """Qbot long-only cross: golden cross enters, death cross exits (no short leg)."""
    if crossed_up_flag:
        return Signal(action="LONG", score=entry_score)
    if crossed_down_flag:
        return Signal(action="WAIT", score=exit_score)
    return None


def clamp_score(value: float, *, low: float = -100.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def sma_at(values: list[float], period: int) -> float:
    series = rolling_sma(values, period)
    last = series[-1] if series else None
    if last is not None:
        return last
    window = values[-period:]
    return sum(window) / len(window)


def bollinger_at(
    closes: list[float],
    period: int,
    num_std: float,
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    if len(closes) < period:
        return None, None, None
    bands = bollinger_bands(closes, period, num_std)
    return bands["upper"][-1], bands["middle"][-1], bands["lower"][-1]


def ema_bullish_alignment(fast: float, mid: float, slow: float) -> bool:
    return fast > mid > slow


def adx_trend_forming(adx: float, prev_adx: float, *, threshold: float) -> bool:
    return adx <= threshold and adx > prev_adx


def macd_lines_at(
    indicators: IndicatorSeries,
    idx: int,
) -> tuple[float, float, float, float] | None:
    if idx <= 0 or idx >= len(indicators.macd_line):
        return None
    macd = indicators.macd_line[idx]
    signal_line = indicators.macd_signal[idx]
    prev_macd = indicators.macd_line[idx - 1]
    prev_signal = indicators.macd_signal[idx - 1]
    if any(value is None for value in (macd, signal_line, prev_macd, prev_signal)):
        return None
    return float(macd), float(signal_line), float(prev_macd), float(prev_signal)


def macd_cross_flags(
    prev_macd: float,
    prev_signal: float,
    macd: float,
    signal_line: float,
) -> tuple[bool, bool]:
    return (
        crossed_up(prev_macd, prev_signal, macd, signal_line),
        crossed_down(prev_macd, prev_signal, macd, signal_line),
    )


def macd_cross_score_delta(
    prev_macd: float,
    prev_signal: float,
    macd: float,
    signal_line: float,
    *,
    cross_weight: float,
) -> float:
    up, down = macd_cross_flags(prev_macd, prev_signal, macd, signal_line)
    if up:
        return cross_weight
    if down:
        return -cross_weight
    return 0.0


def zero_line_cross_score_delta(prev_macd: float, macd: float, *, weight: float = 10.0) -> float:
    if prev_macd <= 0 < macd:
        return weight
    if prev_macd >= 0 > macd:
        return -weight
    return 0.0


def score_to_directional_action(score: float, *, threshold: float) -> str:
    if score >= threshold:
        return "LONG"
    if score >= 10:
        return "WEAK_LONG"
    if score <= -threshold:
        return "SHORT"
    if score <= -10:
        return "WEAK_SHORT"
    return "WAIT"


def separation_score(
    numerator: float,
    denominator: float,
    *,
    scale: float = 10.0,
) -> float:
    if not denominator:
        return 0.0
    return clamp_score((numerator / denominator) * 100 * scale)
