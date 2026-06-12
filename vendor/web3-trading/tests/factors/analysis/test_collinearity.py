# -*- coding: utf-8 -*-
"""共线性检测单元测试。"""

import pytest

from factors.analysis.collinearity import CollinearityDetector
from factors.analysis.models import CollinearitySeverity, CorrelationMatrix


def _make_corr_matrix(
    factor_names: list[str],
    spearman: list[list[float]],
) -> CorrelationMatrix:
    n = len(factor_names)
    pearson = [row[:] for row in spearman]
    return CorrelationMatrix(
        factor_names=factor_names,
        pearson_matrix=pearson,
        spearman_matrix=spearman,
    )


class TestCollinearityDetector:
    def test_empty_matrix(self) -> None:
        matrix = _make_corr_matrix([], [])
        groups = CollinearityDetector(matrix).detect_groups()
        assert groups == []

    def test_no_collinearity(self) -> None:
        spearman = [
            [1.0, 0.3, 0.1],
            [0.3, 1.0, 0.2],
            [0.1, 0.2, 1.0],
        ]
        matrix = _make_corr_matrix(["a", "b", "c"], spearman)
        groups = CollinearityDetector(matrix).detect_groups(threshold=0.7)
        assert groups == []

    def test_single_group(self) -> None:
        spearman = [
            [1.0, 0.85, 0.75],
            [0.85, 1.0, 0.80],
            [0.75, 0.80, 1.0],
        ]
        matrix = _make_corr_matrix(["a", "b", "c"], spearman)
        groups = CollinearityDetector(matrix).detect_groups(threshold=0.7)
        assert len(groups) == 1
        assert set(groups[0].factor_names) == {"a", "b", "c"}
        assert groups[0].severity == CollinearitySeverity.HIGH

    def test_multiple_groups(self) -> None:
        spearman = [
            [1.0, 0.85, 0.1, 0.1],
            [0.85, 1.0, 0.1, 0.1],
            [0.1, 0.1, 1.0, 0.90],
            [0.1, 0.1, 0.90, 1.0],
        ]
        matrix = _make_corr_matrix(["a", "b", "c", "d"], spearman)
        groups = CollinearityDetector(matrix).detect_groups(threshold=0.7)
        assert len(groups) == 2

    def test_recommend_dedup_keeps_highest_ic(self) -> None:
        spearman = [
            [1.0, 0.85],
            [0.85, 1.0],
        ]
        matrix = _make_corr_matrix(["weak", "strong"], spearman)
        detector = CollinearityDetector(matrix)
        groups = detector.detect_groups(threshold=0.7)
        plan = detector.recommend_dedup(
            groups=groups,
            ic_scores={"weak": 0.03, "strong": 0.08},
        )
        assert plan.groups[0].primary_factor == "strong"

    def test_recommend_dedup_downweights_others(self) -> None:
        spearman = [
            [1.0, 0.85, 0.80],
            [0.85, 1.0, 0.75],
            [0.80, 0.75, 1.0],
        ]
        matrix = _make_corr_matrix(["a", "b", "c"], spearman)
        detector = CollinearityDetector(matrix)
        groups = detector.detect_groups(threshold=0.7)
        plan = detector.recommend_dedup(
            groups=groups,
            ic_scores={"a": 0.10, "b": 0.05, "c": 0.03},
            current_weights={"a": 7.0, "b": 7.0, "c": 7.0},
        )
        # a is primary (highest IC), b and c downweighted
        assert plan.adjusted_weights["a"] == 7.0
        assert plan.adjusted_weights["b"] == pytest.approx(2.1, abs=0.01)
        assert plan.adjusted_weights["c"] == pytest.approx(2.1, abs=0.01)

    def test_recommend_dedup_with_vif(self) -> None:
        spearman = [
            [1.0, 0.85],
            [0.85, 1.0],
        ]
        matrix = _make_corr_matrix(["a", "b"], spearman)
        detector = CollinearityDetector(matrix)
        groups = detector.detect_groups(threshold=0.7)
        plan = detector.recommend_dedup(
            groups=groups,
            ic_scores={"a": 0.05, "b": 0.04},
            vif_scores={"a": 2.0, "b": 12.0},
        )
        assert "VIF > 10" in plan.groups[0].recommendation

    def test_single_factor_not_grouped(self) -> None:
        """Isolated factors should not form groups."""
        spearman = [
            [1.0, 0.85, 0.1],
            [0.85, 1.0, 0.1],
            [0.1, 0.1, 1.0],
        ]
        matrix = _make_corr_matrix(["a", "b", "c"], spearman)
        groups = CollinearityDetector(matrix).detect_groups(threshold=0.7)
        assert len(groups) == 1
        assert "c" not in groups[0].factor_names
