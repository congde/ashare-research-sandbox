# -*- coding: utf-8 -*-
"""权重优化器单元测试。"""

from unittest.mock import AsyncMock, patch

import pytest

from factors.analysis.models import OptimizerType
from factors.analysis.weight_optimizer import WeightOptimizer, WeightOptimizerResultWriter
from factors.backtest.models import BacktestReport, EvalMetrics
from factors.enums import MarketType


def _make_metrics(
    specs: list[tuple[str, float, float, float, int]],
) -> list[EvalMetrics]:
    """快捷构造 EvalMetrics 列表。specs: (factor_name, ic_mean, ic_std, ir, sample_count)"""
    return [
        EvalMetrics(
            factor_name=name,
            category="test",
            horizon="1d",
            ic_mean=ic_mean,
            ic_std=ic_std,
            ir=ir,
            hit_rate=0.55,
            sample_count=n,
            signal_distribution={"bullish": n // 2, "bearish": n // 2},
        )
        for name, ic_mean, ic_std, ir, n in specs
    ]


def _make_report(metrics: list[EvalMetrics]) -> BacktestReport:
    return BacktestReport(per_factor=metrics)


class TestWeightOptimizer:
    def test_equal_weight(self) -> None:
        metrics = _make_metrics([
            ("a", 0.05, 0.10, 0.50, 100),
            ("b", 0.03, 0.08, 0.38, 100),
        ])
        result = WeightOptimizer(_make_report(metrics)).optimize(OptimizerType.EQUAL_WEIGHT)
        assert len(result.weights) == 2
        assert result.weights[0].normalized_weight == 0.5
        assert result.weights[1].normalized_weight == 0.5

    def test_ic_weighted_normalized(self) -> None:
        metrics = _make_metrics([
            ("a", 0.06, 0.10, 0.60, 100),
            ("b", 0.03, 0.10, 0.30, 100),
        ])
        result = WeightOptimizer(_make_report(metrics)).optimize(OptimizerType.IC_WEIGHTED)
        assert len(result.weights) == 2
        total = sum(w.normalized_weight for w in result.weights)
        assert total == pytest.approx(1.0, abs=0.01)
        # Factor with higher IC should get more weight
        wa = next(w for w in result.weights if w.factor_name == "a")
        wb = next(w for w in result.weights if w.factor_name == "b")
        assert wa.normalized_weight > wb.normalized_weight

    def test_ic_weighted_zero_ic_std_handled(self) -> None:
        metrics = _make_metrics([
            ("a", 0.05, 0.0, 0.50, 100),  # zero IC std
            ("b", 0.03, 0.10, 0.30, 100),
        ])
        result = WeightOptimizer(_make_report(metrics)).optimize(OptimizerType.IC_WEIGHTED)
        total = sum(w.normalized_weight for w in result.weights)
        assert total == pytest.approx(1.0, abs=0.01)

    def test_negative_ic_zero_weight(self) -> None:
        metrics = _make_metrics([
            ("a", -0.10, 0.05, -2.0, 100),
            ("b", 0.05, 0.10, 0.50, 100),
        ])
        result = WeightOptimizer(_make_report(metrics)).optimize(OptimizerType.IC_WEIGHTED)
        wa = next(w for w in result.weights if w.factor_name == "a")
        assert wa.raw_weight == 0.0

    def test_risk_parity_signal_variance(self) -> None:
        metrics = [
            EvalMetrics(
                factor_name="stable",
                category="test",
                horizon="1d",
                ic_mean=0.03,
                ic_std=0.10,
                ir=0.3,
                hit_rate=0.55,
                sample_count=100,
                signal_distribution={"bullish": 90, "bearish": 10},  # low variance
            ),
            EvalMetrics(
                factor_name="volatile",
                category="test",
                horizon="1d",
                ic_mean=0.03,
                ic_std=0.10,
                ir=0.3,
                hit_rate=0.55,
                sample_count=100,
                signal_distribution={"bullish": 50, "bearish": 50},  # high variance
            ),
        ]
        result = WeightOptimizer(_make_report(metrics)).optimize(OptimizerType.RISK_PARITY)
        w_stable = next(w for w in result.weights if w.factor_name == "stable")
        w_volatile = next(w for w in result.weights if w.factor_name == "volatile")
        # Low variance → lower weight in risk parity
        assert w_volatile.normalized_weight > w_stable.normalized_weight

    def test_mean_variance(self) -> None:
        metrics = _make_metrics([
            ("a", 0.05, 0.10, 0.50, 100),
            ("b", 0.02, 0.08, 0.25, 100),
            ("c", 0.04, 0.12, 0.33, 100),
        ])
        result = WeightOptimizer(_make_report(metrics)).optimize(OptimizerType.MEAN_VARIANCE)
        total = sum(w.normalized_weight for w in result.weights)
        assert total == pytest.approx(1.0, abs=0.01)

    def test_best_horizon_selection(self) -> None:
        metrics = [
            EvalMetrics(factor_name="a", category="test", horizon="1h", ic_mean=0.05, ic_std=0.10, ir=0.50, hit_rate=0.55, sample_count=30),
            EvalMetrics(factor_name="a", category="test", horizon="4h", ic_mean=0.06, ic_std=0.09, ir=0.67, hit_rate=0.60, sample_count=100),
            EvalMetrics(factor_name="a", category="test", horizon="1d", ic_mean=0.04, ic_std=0.11, ir=0.36, hit_rate=0.52, sample_count=50),
        ]
        report = BacktestReport(per_factor=metrics)
        result = WeightOptimizer(report).optimize(OptimizerType.EQUAL_WEIGHT)
        assert len(result.weights) == 1
        assert result.weights[0].factor_name == "a"

    def test_sharpe_positive_for_positive_ic(self) -> None:
        metrics = _make_metrics([
            ("a", 0.05, 0.10, 0.50, 100),
            ("b", 0.04, 0.08, 0.50, 100),
        ])
        result = WeightOptimizer(_make_report(metrics)).optimize(OptimizerType.IC_WEIGHTED)
        assert result.sharpe_estimate > 0

    def test_empty_report(self) -> None:
        report = BacktestReport(per_factor=[])
        result = WeightOptimizer(report).optimize(OptimizerType.EQUAL_WEIGHT)
        assert result.weights == []

    def test_single_factor(self) -> None:
        metrics = _make_metrics([("only", 0.05, 0.10, 0.50, 100)])
        result = WeightOptimizer(_make_report(metrics)).optimize(OptimizerType.IC_WEIGHTED)
        assert len(result.weights) == 1
        assert result.weights[0].normalized_weight == 1.0


class TestWeightOptimizerResultWriter:
    @pytest.mark.asyncio
    async def test_save(self) -> None:
        result = WeightOptimizer(
            _make_report(_make_metrics([("a", 0.05, 0.10, 0.50, 100)])),
        ).optimize(OptimizerType.EQUAL_WEIGHT)
        mock_save = AsyncMock()
        with patch("factors.local_store.save_weight_optimization", mock_save):
            profile_id = await WeightOptimizerResultWriter.save(result)
        assert profile_id == result.profile_id
        mock_save.assert_called_once()
