# -*- coding: utf-8 -*-
"""Evaluator 单元测试。"""

import pytest

from factors.backtest.config import BacktestConfig
from factors.backtest.evaluator import Evaluator


class TestEvaluatorCore:
    """核心指标计算逻辑（纯函数，不涉及 MongoDB/I/O）。"""

    def test_compute_hit_rate_perfect(self) -> None:
        """信号方向与收益方向完全一致 → Hit Rate 1.0"""
        evaluator = Evaluator(kucoin=None)
        signals = [0.5, 0.3, -0.2, -0.8, 0.1]
        returns = [0.02, 0.05, -0.01, -0.03, 0.0]
        hr = evaluator._compute_hit_rate(signals, returns)
        assert hr == 1.0

    def test_compute_hit_rate_partial(self) -> None:
        """信号方向与收益方向部分一致。"""
        evaluator = Evaluator(kucoin=None)
        signals = [0.5, 0.3, -0.2]
        returns = [0.02, -0.05, 0.01]
        hr = evaluator._compute_hit_rate(signals, returns)
        assert hr == pytest.approx(1 / 3)

    def test_compute_ic_positive_correlation(self) -> None:
        """线性正相关信号应有正 IC。"""
        evaluator = Evaluator(kucoin=None)
        signals = [0.1, 0.2, 0.3, 0.4, 0.5]
        returns = [0.01, 0.02, 0.03, 0.04, 0.05]
        ic_mean, _ = evaluator._compute_ic(signals, returns)
        assert ic_mean > 0

    def test_compute_ic_negative_correlation(self) -> None:
        """线性负相关信号应有负 IC。"""
        evaluator = Evaluator(kucoin=None)
        signals = [0.1, 0.2, 0.3, 0.4, 0.5]
        returns = [-0.01, -0.02, -0.03, -0.04, -0.05]
        ic_mean, _ = evaluator._compute_ic(signals, returns)
        assert ic_mean < 0

    def test_signal_distribution(self) -> None:
        """信号分布计数正确。"""
        evaluator = Evaluator(kucoin=None)
        signals = [0.5, -0.3, 0.0, 0.2, -0.1]
        dist = evaluator._signal_dist(signals)
        assert dist["bullish"] == 3
        assert dist["bearish"] == 2


class TestEvaluatorEmpty:
    @pytest.mark.asyncio
    async def test_evaluate_empty_timepoints(self) -> None:
        evaluator = Evaluator(kucoin=None)
        report = await evaluator.evaluate([], BacktestConfig(symbols=["BTC"]))
        assert report.per_factor == []
        assert report.top_factors_by_ic == []
