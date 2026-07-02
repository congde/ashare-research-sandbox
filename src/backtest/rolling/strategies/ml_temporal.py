# -*- coding: utf-8 -*-
"""Lag-safe ML time-series strategies for the teaching backtest lab.

The models are intentionally small pure-Python classifiers. They are trained
only on rows whose labels are known before the current candle, so the strategy
remains safe for the course's lookahead checks without adding heavy runtime
dependencies.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from backtest.rolling.indicators import IndicatorSeries
from backtest.rolling.models import Signal
from backtest.rolling.strategies.base import Strategy


@dataclass(frozen=True)
class _TrainingSet:
    rows: list[list[float]]
    labels: list[int]
    x_now: list[float]


class _MLTemporalBase(Strategy):
    model_key = "logistic"
    model_label = "Logistic"
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
            "model": self.model_key,
            "neighbors": 9,
            "tree_count": 21,
            "boost_rounds": 12,
        }

    def param_grid(self) -> Dict[str, List[Any]]:
        return {
            "lookback": [48, 72, 96],
            "horizon": [1, 3, 5],
            "entry_threshold": [18, 24, 30],
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

        training = _build_training_set(candles, idx, params, indicators)
        if training is None:
            return Signal(action="WAIT", score=0.0)

        model = str(params.get("model") or self.model_key)
        prob_up = _predict_probability(training, params, model)
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


class MLTemporalStrategy(_MLTemporalBase):
    """Backward-compatible default: regularized logistic classifier."""

    model_key = "logistic"
    model_label = "Logistic"
    name = "ml_temporal"
    display_name = "ML 时序 Logistic 分类"


class MLTemporalKNNStrategy(_MLTemporalBase):
    model_key = "knn"
    model_label = "KNN"
    name = "ml_temporal_knn"
    display_name = "ML 时序 KNN 分类"


class MLTemporalTreeStrategy(_MLTemporalBase):
    model_key = "tree_ensemble"
    model_label = "Tree Ensemble"
    name = "ml_temporal_tree"
    display_name = "ML 时序树集成"


class MLTemporalBoostingStrategy(_MLTemporalBase):
    model_key = "boosted_stumps"
    model_label = "Boosted Stumps"
    name = "ml_temporal_boosting"
    display_name = "ML 时序梯度提升"


class MLTemporalEnsembleStrategy(_MLTemporalBase):
    model_key = "ensemble"
    model_label = "Ensemble"
    name = "ml_temporal_ensemble"
    display_name = "ML 时序投票集成"


def _build_training_set(
    candles: List[Dict],
    idx: int,
    params: Dict[str, Any],
    indicators: IndicatorSeries,
) -> _TrainingSet | None:
    horizon = max(1, min(10, int(params.get("horizon", 3))))
    lookback = max(24, min(240, int(params.get("lookback", 72))))
    min_train = max(20, min(lookback, int(params.get("min_train", 36))))
    start = max(12, idx - lookback - horizon)
    train_end = idx - horizon
    if train_end - start < min_train:
        return None

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
        return None

    means, scales = _fit_scaler(rows)
    return _TrainingSet(
        rows=[_scale(row, means, scales) for row in rows],
        labels=labels,
        x_now=_scale(current, means, scales),
    )


def _predict_probability(training: _TrainingSet, params: Dict[str, Any], model: str) -> float:
    if model == "knn":
        return _predict_knn(training, neighbors=int(params.get("neighbors", 9)))
    if model == "tree_ensemble":
        return _predict_tree_ensemble(training, tree_count=int(params.get("tree_count", 21)))
    if model == "boosted_stumps":
        return _predict_boosted_stumps(training, rounds=int(params.get("boost_rounds", 12)))
    if model == "ensemble":
        votes = [
            _predict_logistic(training, params),
            _predict_knn(training, neighbors=int(params.get("neighbors", 9))),
            _predict_tree_ensemble(training, tree_count=int(params.get("tree_count", 21))),
            _predict_boosted_stumps(training, rounds=int(params.get("boost_rounds", 12))),
        ]
        return sum(votes) / len(votes)
    return _predict_logistic(training, params)


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
    momentum_slope = (r3 + r5 + r10) / 3.0
    values = [
        r1,
        r3,
        r5,
        r10,
        momentum_slope,
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


def _predict_logistic(training: _TrainingSet, params: Dict[str, Any]) -> float:
    weights, bias = _fit_logistic(
        training.rows,
        training.labels,
        learning_rate=float(params.get("learning_rate", 0.18)),
        epochs=max(4, min(60, int(params.get("epochs", 18)))),
        l2=max(0.0, min(0.2, float(params.get("l2", 0.02)))),
    )
    return _sigmoid(sum(w * x for w, x in zip(weights, training.x_now)) + bias)


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


def _predict_knn(training: _TrainingSet, *, neighbors: int) -> float:
    k = max(3, min(21, neighbors, len(training.rows)))
    distances = [
        (sum((a - b) ** 2 for a, b in zip(row, training.x_now)), label)
        for row, label in zip(training.rows, training.labels)
    ]
    distances.sort(key=lambda item: item[0])
    weight_sum = 0.0
    score_sum = 0.0
    for dist, label in distances[:k]:
        weight = 1.0 / (math.sqrt(dist) + 1e-6)
        weight_sum += weight
        score_sum += weight * label
    return score_sum / weight_sum if weight_sum else _label_prior(training.labels)


def _predict_tree_ensemble(training: _TrainingSet, *, tree_count: int) -> float:
    count = max(5, min(51, tree_count))
    votes: list[float] = []
    width = len(training.rows[0])
    for tree_idx in range(count):
        sample_indices = [
            (tree_idx * 17 + offset * 7) % len(training.rows)
            for offset in range(max(12, len(training.rows) // 2))
        ]
        candidates = [
            (tree_idx + 2 * depth) % width
            for depth in range(min(4, width))
        ]
        stump = _best_stump(training.rows, training.labels, sample_indices, candidates)
        votes.append(_stump_probability(stump, training.x_now))
    return sum(votes) / len(votes) if votes else _label_prior(training.labels)


def _predict_boosted_stumps(training: _TrainingSet, *, rounds: int) -> float:
    n = len(training.rows)
    weights = [1.0 / n] * n
    learners: list[tuple[tuple[int, float, int, float, float], float]] = []
    width = len(training.rows[0])
    for round_idx in range(max(3, min(30, rounds))):
        candidates = [(round_idx + offset) % width for offset in range(width)]
        stump = _best_stump(
            training.rows,
            training.labels,
            list(range(n)),
            candidates,
            row_weights=weights,
        )
        err = 0.0
        for i, row in enumerate(training.rows):
            pred = 1 if _stump_probability(stump, row) >= 0.5 else 0
            if pred != training.labels[i]:
                err += weights[i]
        err = max(1e-6, min(0.499, err))
        alpha = 0.5 * math.log((1.0 - err) / err)
        for i, row in enumerate(training.rows):
            pred_sign = 1 if _stump_probability(stump, row) >= 0.5 else -1
            label_sign = 1 if training.labels[i] == 1 else -1
            weights[i] *= math.exp(-alpha * label_sign * pred_sign)
        total = sum(weights) or 1.0
        weights = [value / total for value in weights]
        learners.append((stump, alpha))

    margin = sum(
        alpha * (1 if _stump_probability(stump, training.x_now) >= 0.5 else -1)
        for stump, alpha in learners
    )
    return _sigmoid(2.0 * margin)


def _best_stump(
    rows: Sequence[Sequence[float]],
    labels: Sequence[int],
    sample_indices: Sequence[int],
    candidate_features: Sequence[int],
    *,
    row_weights: Sequence[float] | None = None,
) -> tuple[int, float, int, float, float]:
    best: tuple[int, float, int, float, float] | None = None
    best_loss = float("inf")
    for feature_idx in candidate_features:
        values = sorted(rows[i][feature_idx] for i in sample_indices)
        if not values:
            continue
        thresholds = _quantile_thresholds(values)
        for threshold in thresholds:
            for polarity in (1, -1):
                left_weight = right_weight = left_up = right_up = 0.0
                loss = 0.0
                for idx in sample_indices:
                    weight = row_weights[idx] if row_weights is not None else 1.0
                    goes_up = rows[idx][feature_idx] >= threshold if polarity == 1 else rows[idx][feature_idx] < threshold
                    if goes_up:
                        right_weight += weight
                        right_up += weight * labels[idx]
                    else:
                        left_weight += weight
                        left_up += weight * labels[idx]
                left_prob = left_up / left_weight if left_weight else 0.5
                right_prob = right_up / right_weight if right_weight else 0.5
                for idx in sample_indices:
                    weight = row_weights[idx] if row_weights is not None else 1.0
                    prob = right_prob if (
                        rows[idx][feature_idx] >= threshold if polarity == 1 else rows[idx][feature_idx] < threshold
                    ) else left_prob
                    loss += weight * abs(labels[idx] - prob)
                if loss < best_loss:
                    best_loss = loss
                    best = (feature_idx, threshold, polarity, left_prob, right_prob)
    return best or (0, 0.0, 1, _label_prior(labels), _label_prior(labels))


def _quantile_thresholds(values: Sequence[float]) -> list[float]:
    if len(values) <= 4:
        return list(values)
    return [
        values[int((len(values) - 1) * q)]
        for q in (0.2, 0.35, 0.5, 0.65, 0.8)
    ]


def _stump_probability(stump: tuple[int, float, int, float, float], row: Sequence[float]) -> float:
    feature_idx, threshold, polarity, left_prob, right_prob = stump
    right = row[feature_idx] >= threshold if polarity == 1 else row[feature_idx] < threshold
    return right_prob if right else left_prob


def _label_prior(labels: Sequence[int]) -> float:
    return sum(labels) / len(labels) if labels else 0.5


def _sigmoid(value: float) -> float:
    if value >= 35:
        return 1.0
    if value <= -35:
        return 0.0
    return 1.0 / (1.0 + math.exp(-value))
