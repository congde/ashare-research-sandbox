# -*- coding: utf-8 -*-
"""Lag-safe ML time-series strategy for the teaching backtest lab."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from backtest.rolling.indicators import IndicatorSeries
from backtest.rolling.strategies.base import Strategy
from backtest.rolling.models import Signal


class MLTemporalStrategy(Strategy):
    name = "ml_temporal"
    display_name = "ML 时序分类策略"

    def default_params(self) -> Dict[str, Any]:
        return {
            "lookback": 72,
            "horizon": 3,
            "entry_threshold": 24,
            "learning_rate": 0.18,
            "epochs": 18,
            "l2": 0.02,
            "min_train": 36,
            "max_hold_bars": 10,
        }

    def param_grid(self) -> Dict[str, List[Any]]:
        return {
            "lookback": [48, 72, 96],
            "horizon": [1, 3, 5],
            "entry_threshold": [18, 24, 30],
            "learning_rate": [0.08, 0.18],
            "l2": [0.01, 0.03],
        }

    def backtest_config_overrides(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {"max_hold_bars": int(params.get("max_hold_bars", 10))}

    def generate_signal(
        self,
        candles: List[Dict],
        idx: int,
        params: Dict[str, Any],
        indicators: Optional[IndicatorSeries] = None,
    ) -> Signal:
        if indicators is None:
            return Signal(action="WAIT", score=0.0)

        horizon = max(1, min(10, int(params.get("horizon", 3))))
        lookback = max(24, min(240, int(params.get("lookback", 72))))
        min_train = max(20, min(lookback, int(params.get("min_train", 36))))
        start = max(12, idx - lookback - horizon)
        train_end = idx - horizon
        if train_end - start < min_train:
            return Signal(action="WAIT", score=0.0)

        rows: list[list[float]] = []
        labels: list[int] = []
        for row_idx in range(start, train_end):
            feat = _features(candles, row_idx, indicators)
            if feat is None:
                continue
            base = float(candles[row_idx]["close"])
            future = float(candles[row_idx + horizon]["close"])
            if base <= 0:
                continue
            rows.append(feat)
            labels.append(1 if future > base else 0)

        current = _features(candles, idx, indicators)
        if current is None or len(rows) < min_train:
            return Signal(action="WAIT", score=0.0)

        means, scales = _fit_scaler(rows)
        x_train = [_scale(row, means, scales) for row in rows]
        x_now = _scale(current, means, scales)
        weights, bias = _fit_logistic(
            x_train,
            labels,
            learning_rate=float(params.get("learning_rate", 0.18)),
            epochs=max(4, min(60, int(params.get("epochs", 18)))),
            l2=max(0.0, min(0.2, float(params.get("l2", 0.02)))),
        )
        prob_up = _sigmoid(sum(w * x for w, x in zip(weights, x_now)) + bias)
        score = max(-100.0, min(100.0, (prob_up - 0.5) * 200.0))
        threshold = float(params.get("entry_threshold", 24))
        if score >= threshold:
            return Signal(action="LONG", score=score)
        if score <= -threshold:
            return Signal(action="SHORT", score=score)
        if score >= threshold * 0.45:
            return Signal(action="WEAK_LONG", score=score)
        if score <= -threshold * 0.45:
            return Signal(action="WEAK_SHORT", score=score)
        return Signal(action="WAIT", score=score)


def _features(candles: List[Dict], idx: int, indicators: IndicatorSeries) -> list[float] | None:
    if idx < 10:
        return None
    closes = [float(row["close"]) for row in candles]
    close = closes[idx]
    if close <= 0:
        return None
    r1 = close / closes[idx - 1] - 1.0
    r3 = close / closes[idx - 3] - 1.0
    r5 = close / closes[idx - 5] - 1.0
    r10 = close / closes[idx - 10] - 1.0
    values = [
        r1,
        r3,
        r5,
        r10,
        _safe(indicators.rsi[idx], 50.0) / 100.0 - 0.5,
        _safe(indicators.bb_pct_b[idx], 50.0) / 100.0 - 0.5,
        _safe(indicators.atr_pct[idx], 0.0) / 10.0,
        math.log(max(1e-9, _safe(indicators.vol_ratio[idx], 1.0))),
        _safe(indicators.range_pos[idx], 50.0) / 100.0 - 0.5,
        _safe(indicators.macd_histogram[idx], 0.0) / max(close, 1e-9),
    ]
    if any(not math.isfinite(value) for value in values):
        return None
    return values


def _safe(value: float | None, default: float) -> float:
    if value is None or not math.isfinite(value):
        return default
    return float(value)


def _fit_scaler(rows: list[list[float]]) -> tuple[list[float], list[float]]:
    width = len(rows[0])
    means = [sum(row[i] for row in rows) / len(rows) for i in range(width)]
    scales: list[float] = []
    for i, mean in enumerate(means):
        var = sum((row[i] - mean) ** 2 for row in rows) / max(1, len(rows) - 1)
        scales.append(math.sqrt(var) or 1.0)
    return means, scales


def _scale(row: list[float], means: list[float], scales: list[float]) -> list[float]:
    return [(value - mean) / scale for value, mean, scale in zip(row, means, scales)]


def _fit_logistic(
    rows: list[list[float]],
    labels: list[int],
    *,
    learning_rate: float,
    epochs: int,
    l2: float,
) -> tuple[list[float], float]:
    width = len(rows[0])
    weights = [0.0] * width
    bias = 0.0
    n = max(1, len(rows))
    for _ in range(epochs):
        grad = [0.0] * width
        bias_grad = 0.0
        for row, label in zip(rows, labels):
            pred = _sigmoid(sum(w * x for w, x in zip(weights, row)) + bias)
            err = pred - label
            for i, value in enumerate(row):
                grad[i] += err * value
            bias_grad += err
        for i in range(width):
            weights[i] -= learning_rate * (grad[i] / n + l2 * weights[i])
        bias -= learning_rate * bias_grad / n
    return weights, bias


def _sigmoid(value: float) -> float:
    if value >= 35:
        return 1.0
    if value <= -35:
        return 0.0
    return 1.0 / (1.0 + math.exp(-value))
