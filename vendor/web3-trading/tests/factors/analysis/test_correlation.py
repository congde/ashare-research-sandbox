# -*- coding: utf-8 -*-
"""SignalCorrelationAnalyzer 单元测试。"""

import numpy as np
import pytest

from factors.analysis.correlation import SignalCorrelationAnalyzer
from factors.backtest.models import BacktestTimePoint


def _make_timepoint(factor_scores: dict[str, float], ts: int = 0) -> BacktestTimePoint:
    return BacktestTimePoint(
        timestamp_ms=ts,
        symbol="BTC",
        factor_scores=factor_scores,
    )


class TestSignalCorrelationAnalyzer:
    def test_empty_timepoints(self) -> None:
        analyzer = SignalCorrelationAnalyzer([])
        assert analyzer.factor_names == []
        assert analyzer.compute_pearson() == []
        assert analyzer.compute_spearman() == []

    def test_single_factor(self) -> None:
        tps = [
            _make_timepoint({"a": 0.5}, 1),
            _make_timepoint({"a": -0.3}, 2),
        ]
        analyzer = SignalCorrelationAnalyzer(tps)
        assert analyzer.factor_names == ["a"]
        pearson = analyzer.compute_pearson()
        assert pearson == [[1.0]]

    def test_perfect_correlation(self) -> None:
        tps = [
            _make_timepoint({"a": 0.5, "b": 0.5}, 1),
            _make_timepoint({"a": 0.8, "b": 0.8}, 2),
            _make_timepoint({"a": -0.3, "b": -0.3}, 3),
            _make_timepoint({"a": 0.1, "b": 0.1}, 4),
            _make_timepoint({"a": -0.9, "b": -0.9}, 5),
        ]
        analyzer = SignalCorrelationAnalyzer(tps)
        spearman = analyzer.compute_spearman()
        assert spearman[0][1] == pytest.approx(1.0, abs=0.01)
        assert spearman[0][0] == 1.0

    def test_negative_correlation(self) -> None:
        tps = [
            _make_timepoint({"a": 0.5, "b": -0.5}, 1),
            _make_timepoint({"a": 0.8, "b": -0.8}, 2),
            _make_timepoint({"a": -0.3, "b": 0.3}, 3),
            _make_timepoint({"a": 0.1, "b": -0.1}, 4),
            _make_timepoint({"a": -0.9, "b": 0.9}, 5),
        ]
        analyzer = SignalCorrelationAnalyzer(tps)
        spearman = analyzer.compute_spearman()
        assert spearman[0][1] == pytest.approx(-1.0, abs=0.01)

    def test_pearson_matrix_shape(self) -> None:
        tps = [
            _make_timepoint({"a": 0.5, "b": 0.3, "c": -0.2}, 1),
            _make_timepoint({"a": 0.8, "b": 0.1, "c": 0.4}, 2),
            _make_timepoint({"a": -0.3, "b": 0.6, "c": -0.1}, 3),
        ]
        analyzer = SignalCorrelationAnalyzer(tps)
        pearson = analyzer.compute_pearson()
        assert len(pearson) == 3
        assert all(len(row) == 3 for row in pearson)
        for i in range(3):
            assert pearson[i][i] == pytest.approx(1.0, abs=0.01)

    def test_find_high_correlation_pairs(self) -> None:
        n = 20
        rng = np.random.RandomState(42)
        base = rng.randn(n)
        a = base + rng.randn(n) * 0.1  # highly correlated with base
        tps = []
        for t in range(n):
            tps.append(_make_timepoint({
                "base": float(base[t]),
                "a": float(a[t]),
                "independent": float(rng.randn()),
            }, t))
        analyzer = SignalCorrelationAnalyzer(tps)
        pairs = analyzer.find_high_correlation_pairs(threshold=0.5)
        pair_names = {(p.factor_a, p.factor_b) for p in pairs}
        assert ("base", "a") in pair_names or ("a", "base") in pair_names

    def test_find_high_correlation_below_threshold_excluded(self) -> None:
        n = 20
        rng = np.random.RandomState(99)
        a = rng.randn(n)
        b = rng.randn(n)  # independent
        tps = [_make_timepoint({"a": float(a[t]), "b": float(b[t])}, t) for t in range(n)]
        analyzer = SignalCorrelationAnalyzer(tps)
        pairs = analyzer.find_high_correlation_pairs(threshold=0.7)
        pair_names = {(p.factor_a, p.factor_b) for p in pairs}
        assert ("a", "b") not in pair_names

    def test_build_matrix(self) -> None:
        tps = [
            _make_timepoint({"a": 0.5, "b": 0.5}, 1),
            _make_timepoint({"a": 0.8, "b": 0.8}, 2),
            _make_timepoint({"a": -0.3, "b": -0.3}, 3),
        ]
        analyzer = SignalCorrelationAnalyzer(tps)
        matrix = analyzer.build_matrix(threshold=0.5)
        assert matrix.factor_names == ["a", "b"]
        assert len(matrix.pearson_matrix) == 2
        assert len(matrix.spearman_matrix) == 2

    def test_missing_factor_in_some_timepoints(self) -> None:
        tps = [
            _make_timepoint({"a": 0.5, "b": 0.3}, 1),
            _make_timepoint({"a": 0.8}, 2),  # b missing → treated as 0
            _make_timepoint({"a": -0.3, "b": -0.1}, 3),
        ]
        analyzer = SignalCorrelationAnalyzer(tps)
        assert analyzer.factor_names == ["a", "b"]


class TestVIF:
    def test_independent_factors(self) -> None:
        n = 50
        rng = np.random.RandomState(42)
        tps = []
        for t in range(n):
            tps.append(_make_timepoint({
                "a": float(rng.randn()),
                "b": float(rng.randn()),
                "c": float(rng.randn()),
            }, t))
        analyzer = SignalCorrelationAnalyzer(tps)
        vif = analyzer.compute_vif()
        for name in ["a", "b", "c"]:
            assert vif[name] < 3.0, f"VIF for {name} should be near 1 for independent factors"

    def test_collinear_factors_high_vif(self) -> None:
        n = 50
        rng = np.random.RandomState(42)
        base = rng.randn(n)
        tps = []
        for t in range(n):
            tps.append(_make_timepoint({
                "base": float(base[t]),
                "clone": float(base[t] + rng.randn() * 0.01),  # nearly identical
            }, t))
        analyzer = SignalCorrelationAnalyzer(tps)
        vif = analyzer.compute_vif()
        assert vif["base"] > 5.0 or vif["clone"] > 5.0

    def test_single_factor_vif(self) -> None:
        tps = [_make_timepoint({"a": 0.5}, 1), _make_timepoint({"a": -0.3}, 2)]
        analyzer = SignalCorrelationAnalyzer(tps)
        vif = analyzer.compute_vif()
        assert vif["a"] == 1.0
