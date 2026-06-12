# -*- coding: utf-8 -*-
"""分析模型构造与序列化测试。"""

import uuid

from factors.analysis.models import (
    ABComparisonRow,
    ABTestReport,
    ABTestWinner,
    CollinearityGroup,
    CollinearitySeverity,
    CorrelationMatrix,
    DedupPlan,
    FactorCorrelationPair,
    MarketState,
    MarketStateResult,
    OptimizedWeight,
    OptimizerResult,
    OptimizerType,
    StateProfile,
    StateWeightBias,
)
from factors.enums import MarketType


class TestOptimizedWeight:
    def test_construction(self) -> None:
        w = OptimizedWeight(
            factor_name="spot_trade_inflow",
            raw_weight=2.5,
        )
        assert w.factor_name == "spot_trade_inflow"
        assert w.raw_weight == 2.5

    def test_normalized_defaults(self) -> None:
        w = OptimizedWeight(factor_name="test", raw_weight=1.0)
        assert w.normalized_weight == 0.0
        assert w.optimizer_metric == 0.0


class TestOptimizerResult:
    def test_construction(self) -> None:
        result = OptimizerResult(
            optimizer_type=OptimizerType.IC_WEIGHTED,
            profile_id="ic_v1",
            market_type=MarketType.SPOT,
            weights=[
                OptimizedWeight(factor_name="a", raw_weight=0.6, normalized_weight=0.6),
                OptimizedWeight(factor_name="b", raw_weight=0.4, normalized_weight=0.4),
            ],
        )
        assert result.optimizer_type == OptimizerType.IC_WEIGHTED
        assert len(result.weights) == 2

    def test_serializable(self) -> None:
        result = OptimizerResult(
            optimizer_type=OptimizerType.EQUAL_WEIGHT,
            profile_id="ew_v1",
            market_type=MarketType.SPOT,
            weights=[OptimizedWeight(factor_name="x", raw_weight=1.0, normalized_weight=1.0)],
            sharpe_estimate=0.85,
            sharpe_improvement=0.12,
        )
        d = result.model_dump()
        assert d["optimizer_type"] == "equal_weight"
        assert d["sharpe_estimate"] == 0.85


class TestABTestReport:
    def test_construction(self) -> None:
        report = ABTestReport(
            id=uuid.uuid4().hex,
            profile_a_id="equal_weight",
            profile_b_id="ic_weighted",
            winner=ABTestWinner.PROFILE_B,
            sharpe_a=0.75,
            sharpe_b=0.92,
            p_value=0.03,
            recommendation="切换到 IC 加权方案",
        )
        assert report.winner == ABTestWinner.PROFILE_B
        assert report.p_value == 0.03

    def test_no_significant_difference(self) -> None:
        report = ABTestReport(
            id=uuid.uuid4().hex,
            profile_a_id="a",
            profile_b_id="b",
            winner=ABTestWinner.NO_SIGNIFICANT_DIFFERENCE,
            sharpe_a=0.80,
            sharpe_b=0.81,
            p_value=0.45,
        )
        assert report.winner == ABTestWinner.NO_SIGNIFICANT_DIFFERENCE


class TestCorrelationMatrix:
    def test_construction(self) -> None:
        matrix = CorrelationMatrix(
            factor_names=["a", "b", "c"],
            pearson_matrix=[[1.0, 0.5, 0.3], [0.5, 1.0, 0.2], [0.3, 0.2, 1.0]],
            spearman_matrix=[[1.0, 0.4, 0.3], [0.4, 1.0, 0.1], [0.3, 0.1, 1.0]],
        )
        assert len(matrix.factor_names) == 3
        assert matrix.pearson_matrix[0][0] == 1.0

    def test_serializable(self) -> None:
        matrix = CorrelationMatrix(
            factor_names=["x", "y"],
            pearson_matrix=[[1.0, 0.8], [0.8, 1.0]],
            spearman_matrix=[[1.0, 0.7], [0.7, 1.0]],
        )
        d = matrix.model_dump()
        assert d["factor_names"] == ["x", "y"]


class TestCollinearityGroup:
    def test_construction(self) -> None:
        group = CollinearityGroup(
            group_id="g1",
            factor_names=["a", "b", "c"],
            avg_correlation=0.82,
            severity=CollinearitySeverity.HIGH,
            primary_factor="a",
            vif_scores={"a": 2.1, "b": 8.5, "c": 9.2},
        )
        assert group.severity == CollinearitySeverity.HIGH
        assert group.primary_factor == "a"


class TestDedupPlan:
    def test_construction(self) -> None:
        plan = DedupPlan(
            groups=[
                CollinearityGroup(
                    group_id="g1",
                    factor_names=["a", "b"],
                    avg_correlation=0.85,
                    severity=CollinearitySeverity.HIGH,
                    primary_factor="a",
                    recommendation="保留 a，b 降权至 0.3 倍",
                ),
            ],
            adjusted_weights={"a": 7.0, "b": 2.1},
        )
        assert len(plan.groups) == 1
        assert plan.adjusted_weights["a"] == 7.0


class TestMarketStateResult:
    def test_trending_up(self) -> None:
        r = MarketStateResult(
            state=MarketState.TRENDING_UP,
            confidence=0.85,
            indicators={"adx": 32.0, "atr_pct": 0.55, "ema_ratio": 1.05},
        )
        assert r.state == MarketState.TRENDING_UP
        assert r.confidence == 0.85

    def test_with_adjacent_states(self) -> None:
        r = MarketStateResult(
            state=MarketState.RANGING,
            confidence=0.60,
            indicators={"adx": 22.0, "atr_pct": 0.75},
            adjacent_states=[MarketState.HIGH_VOL],
            adjacent_weights=[0.3],
        )
        assert len(r.adjacent_states) == 1
        assert r.adjacent_weights == [0.3]


class TestStateProfile:
    def test_construction(self) -> None:
        profile = StateProfile(
            state=MarketState.TRENDING_UP,
            profile_id="trending_up_spot",
            market_type=MarketType.SPOT,
            biases=[
                StateWeightBias(
                    factor_name="trend_strength",
                    base_weight=7.0,
                    bias_multiplier=1.5,
                    reason="趋势市场技术面因子更有效",
                ),
                StateWeightBias(
                    factor_name="spot_trade_inflow",
                    base_weight=7.0,
                    bias_multiplier=1.0,
                ),
            ],
        )
        assert len(profile.biases) == 2
        assert profile.biases[0].bias_multiplier == 1.5
