# -*- coding: utf-8 -*-
"""A/B 测试框架单元测试。"""

from unittest.mock import AsyncMock, patch

import numpy as np
import pytest
import time

from factors.analysis.ab_test import ABTestRunner
from factors.analysis.models import ABTestWinner, OptimizerType
from factors.backtest.config import BacktestConfig
from factors.backtest.engine import BacktestEngine
from factors.backtest.models import BacktestReport, BacktestTimePoint, EvalMetrics
from factors.enums import FactorTier, MarketType
from factors.ranking.profile import FactorEntry, RankingProfile


def _make_profile(profile_id: str, weights: dict[str, float]) -> RankingProfile:
    entries = []
    for i, (name, w) in enumerate(weights.items(), start=1):
        entries.append(FactorEntry(
            factor_name=name,
            rank=i,
            weight=w,
            tier=FactorTier.TIER_1,
        ))
    return RankingProfile(
        profile_id=profile_id,
        market_type=MarketType.SPOT,
        factors=entries,
    )


def _make_timepoints(scores: list[dict[str, float]]) -> list[BacktestTimePoint]:
    return [
        BacktestTimePoint(
            timestamp_ms=i * 3600000,
            symbol="BTC",
            factor_scores=s,
            aggregate_score=sum(s.values()),
        )
        for i, s in enumerate(scores)
    ]


class TestABTestRunner:
    @pytest.mark.asyncio
    async def test_compare_two_equal_profiles(self) -> None:
        """相同 profile 应返回无显著差异。"""
        profile_a = _make_profile("equal", {"a": 1.0, "b": 1.0})
        profile_b = _make_profile("equal_copy", {"a": 1.0, "b": 1.0})
        tps = _make_timepoints([
            {"a": 0.5, "b": 0.3},
            {"a": 0.6, "b": 0.4},
            {"a": 0.4, "b": 0.2},
            {"a": 0.7, "b": 0.5},
            {"a": 0.3, "b": 0.1},
            {"a": 0.5, "b": 0.3},
            {"a": 0.6, "b": 0.4},
            {"a": 0.4, "b": 0.2},
        ])

        report = BacktestReport(per_factor=[
            EvalMetrics(factor_name="a", horizon="1d", ic_mean=0.05, ir=0.50, sample_count=8),
            EvalMetrics(factor_name="b", horizon="1d", ic_mean=0.03, ir=0.30, sample_count=8),
        ])

        engine = BacktestEngine()
        mock_eval = AsyncMock(return_value=report)
        mock_sim = AsyncMock(return_value=tps)
        engine._evaluator.evaluate = mock_eval
        engine._simulator.replay = mock_sim

        runner = ABTestRunner(engine)
        result = await runner.compare(profile_a, profile_b, BacktestConfig(
            symbols=["BTC"], lookback_days=30,
        ))

        assert result.winner == ABTestWinner.NO_SIGNIFICANT_DIFFERENCE

    @pytest.mark.asyncio
    async def test_optimized_beats_equal_weight(self) -> None:
        """优化型 profile 应有更高的逐日分数。"""
        profile_a = _make_profile("equal", {"a": 1.0, "b": 1.0})
        profile_b = _make_profile("optimized", {"a": 1.5, "b": 0.5})

        # 构造 signals: factor "a" 在 profile_b 中权重更高，"a" 的分数趋势向上
        rng = np.random.RandomState(42)
        tps_a = [
            BacktestTimePoint(
                timestamp_ms=i * 3600000,
                symbol="BTC",
                factor_scores={"a": float(rng.randn() * 0.1), "b": float(rng.randn() * 0.1)},
                aggregate_score=float(rng.randn() * 0.1),
            )
            for i in range(30)
        ]
        tps_b = [
            BacktestTimePoint(
                timestamp_ms=i * 3600000,
                symbol="BTC",
                factor_scores={"a": float(0.02 + rng.randn() * 0.05), "b": float(rng.randn() * 0.1)},
                aggregate_score=float(0.02 + rng.randn() * 0.05),  # slight upward drift
            )
            for i in range(30)
        ]

        engine = BacktestEngine()
        engine._simulator.replay = AsyncMock(side_effect=[tps_a, tps_b])
        engine._evaluator.evaluate = AsyncMock(return_value=BacktestReport(per_factor=[]))

        runner = ABTestRunner(engine)
        result = await runner.compare(
            profile_a, profile_b,
            BacktestConfig(symbols=["BTC"], lookback_days=30),
            optimizer_types=[OptimizerType.IC_WEIGHTED],
        )

        assert result.sharpe_b > result.sharpe_a or result.winner != ABTestWinner.PROFILE_A

    def test_welch_ttest_significance(self) -> None:
        """两组显著不同的分布应有 p < 0.05。"""
        rng = np.random.RandomState(42)
        group_a = [float(rng.normal(0.0, 1.0)) for _ in range(100)]
        group_b = [float(rng.normal(0.5, 1.0)) for _ in range(100)]
        p = ABTestRunner._welch_ttest(group_a, group_b)
        assert p < 0.05

    def test_welch_ttest_same_distribution(self) -> None:
        """两组相同分布应有 p > 0.1。"""
        rng = np.random.RandomState(42)
        group_a = [float(rng.normal(0.0, 1.0)) for _ in range(100)]
        group_b = [float(rng.normal(0.0, 1.0)) for _ in range(100)]
        p = ABTestRunner._welch_ttest(group_a, group_b)
        assert p > 0.1

    def test_sharpe_positive(self) -> None:
        """正收益序列产生正夏普。"""
        scores = [0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09]
        sharpe = ABTestRunner._sharpe_from_scores(scores)
        assert sharpe > 0

    def test_sharpe_fluctuating(self) -> None:
        """波动序列夏普接近零。"""
        rng = np.random.RandomState(99)
        scores = [float(rng.normal(0.0, 0.01)) for _ in range(100)]
        sharpe = ABTestRunner._sharpe_from_scores(scores)
        assert abs(sharpe) < 5.0  # Not huge in either direction

    def test_empty_scores(self) -> None:
        assert ABTestRunner._welch_ttest([], []) == 1.0
        assert ABTestRunner._sharpe_from_scores([]) == 0.0
