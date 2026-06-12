# -*- coding: utf-8 -*-
"""
Tests for src/signal/weight_optimizer.py
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from signal_analysis.weight_optimizer import (
    compute_adaptive_weights,
    apply_weighted_score,
    _sigmoid_scale,
    DIMENSIONS,
    DEFAULT_WEIGHT,
    MIN_WEIGHT,
    MAX_WEIGHT,
    MIN_SAMPLES,
)
from web.api.signal_schema import DimensionWeight


class TestSigmoidScale:
    def test_midpoint(self):
        # 0.5 accuracy should map to moderate value
        val = _sigmoid_scale(0.5)
        assert 0.2 < val < 0.6

    def test_high_accuracy(self):
        val = _sigmoid_scale(0.9)
        assert val > _sigmoid_scale(0.5)

    def test_low_accuracy(self):
        val = _sigmoid_scale(0.2)
        assert val < _sigmoid_scale(0.5)

    def test_always_positive(self):
        for acc in [0.0, 0.1, 0.5, 0.9, 1.0]:
            assert _sigmoid_scale(acc) > 0

    def test_monotonic(self):
        vals = [_sigmoid_scale(a / 10) for a in range(11)]
        for i in range(len(vals) - 1):
            assert vals[i] <= vals[i + 1]


class TestComputeAdaptiveWeights:
    def test_equal_accuracy_returns_equal_weights(self):
        accuracy = {
            "technical": {"total": 50, "correct": 25, "accuracy": 0.5},
            "onchain": {"total": 50, "correct": 25, "accuracy": 0.5},
            "news": {"total": 50, "correct": 25, "accuracy": 0.5},
            "positioning": {"total": 50, "correct": 25, "accuracy": 0.5},
        }
        weights = compute_adaptive_weights(accuracy)
        assert len(weights) == 4
        for w in weights:
            assert abs(w.adaptiveWeight - 0.25) < 0.05

    def test_high_accuracy_gets_higher_weight(self):
        accuracy = {
            "technical": {"total": 100, "correct": 80, "accuracy": 0.8},
            "onchain": {"total": 100, "correct": 30, "accuracy": 0.3},
            "news": {"total": 100, "correct": 50, "accuracy": 0.5},
            "positioning": {"total": 100, "correct": 50, "accuracy": 0.5},
        }
        weights = compute_adaptive_weights(accuracy)
        weight_map = {w.dimension: w.adaptiveWeight for w in weights}
        assert weight_map["technical"] > weight_map["onchain"]

    def test_weights_sum_to_one(self):
        accuracy = {
            "technical": {"total": 50, "correct": 40, "accuracy": 0.8},
            "onchain": {"total": 50, "correct": 15, "accuracy": 0.3},
            "news": {"total": 50, "correct": 35, "accuracy": 0.7},
            "positioning": {"total": 50, "correct": 25, "accuracy": 0.5},
        }
        weights = compute_adaptive_weights(accuracy)
        total = sum(w.adaptiveWeight for w in weights)
        assert abs(total - 1.0) < 0.01

    def test_insufficient_samples_keep_default(self):
        accuracy = {
            "technical": {"total": 5, "correct": 4, "accuracy": 0.8},  # too few
            "onchain": {"total": 50, "correct": 40, "accuracy": 0.8},
            "news": {"total": 50, "correct": 25, "accuracy": 0.5},
            "positioning": {"total": 50, "correct": 25, "accuracy": 0.5},
        }
        weights = compute_adaptive_weights(accuracy)
        weight_map = {w.dimension: w for w in weights}
        assert weight_map["technical"].sampleSize == 5

    def test_empty_accuracy_data(self):
        weights = compute_adaptive_weights({})
        assert len(weights) == 4
        for w in weights:
            assert abs(w.adaptiveWeight - 0.25) < 0.05

    def test_weight_bounds(self):
        # Extreme accuracy difference
        accuracy = {
            "technical": {"total": 200, "correct": 190, "accuracy": 0.95},
            "onchain": {"total": 200, "correct": 10, "accuracy": 0.05},
            "news": {"total": 200, "correct": 100, "accuracy": 0.5},
            "positioning": {"total": 200, "correct": 100, "accuracy": 0.5},
        }
        weights = compute_adaptive_weights(accuracy)
        for w in weights:
            assert w.adaptiveWeight >= MIN_WEIGHT - 0.01
            assert w.adaptiveWeight <= MAX_WEIGHT + 0.01

    def test_prior_weights_smoothing(self):
        accuracy = {
            "technical": {"total": 100, "correct": 80, "accuracy": 0.8},
            "onchain": {"total": 100, "correct": 80, "accuracy": 0.8},
            "news": {"total": 100, "correct": 80, "accuracy": 0.8},
            "positioning": {"total": 100, "correct": 80, "accuracy": 0.8},
        }
        prior = {"technical": 0.4, "onchain": 0.2, "news": 0.2, "positioning": 0.2}
        weights = compute_adaptive_weights(accuracy, prior_weights=prior)
        weight_map = {w.dimension: w.adaptiveWeight for w in weights}
        # With smoothing, technical should still be higher than equal distribution
        # due to prior=0.4
        assert weight_map["technical"] > 0.24

    def test_output_model_fields(self):
        accuracy = {
            "technical": {"total": 50, "correct": 35, "accuracy": 0.7},
        }
        weights = compute_adaptive_weights(accuracy)
        for w in weights:
            assert isinstance(w, DimensionWeight)
            assert w.dimension in DIMENSIONS
            assert w.baseWeight == DEFAULT_WEIGHT
            assert 0 <= w.recentAccuracy <= 1
            assert w.sampleSize >= 0


class TestApplyWeightedScore:
    def test_basic_weighted_score(self):
        scores = {"technical": 60, "onchain": -20, "news": 30, "positioning": 10}
        weights = [
            DimensionWeight(dimension="technical", adaptiveWeight=0.4),
            DimensionWeight(dimension="onchain", adaptiveWeight=0.2),
            DimensionWeight(dimension="news", adaptiveWeight=0.2),
            DimensionWeight(dimension="positioning", adaptiveWeight=0.2),
        ]
        result = apply_weighted_score(scores, weights)
        expected = 60 * 0.4 + (-20) * 0.2 + 30 * 0.2 + 10 * 0.2
        assert abs(result - expected) < 0.01

    def test_clamped_to_range(self):
        scores = {"technical": 100, "onchain": 100, "news": 100, "positioning": 100}
        weights = [
            DimensionWeight(dimension=d, adaptiveWeight=0.25)
            for d in DIMENSIONS
        ]
        result = apply_weighted_score(scores, weights)
        assert result <= 100.0

        scores_neg = {"technical": -100, "onchain": -100, "news": -100, "positioning": -100}
        result_neg = apply_weighted_score(scores_neg, weights)
        assert result_neg >= -100.0

    def test_missing_dimension_uses_default(self):
        scores = {"technical": 80}
        weights = [DimensionWeight(dimension="technical", adaptiveWeight=0.5)]
        result = apply_weighted_score(scores, weights)
        assert result == 80 * 0.5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])