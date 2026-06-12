# -*- coding: utf-8 -*-
"""ConfidenceCalibrator 单元测试。"""

from factors.backtest.models import EvalMetrics
from factors.calibration import (
    CalibrationRecord,
    ConfidenceCalibrator,
    PerFactorCalibration,
)


class TestBayesianSmooth:
    def test_strong_signal(self) -> None:
        """大量样本 + 高胜率 → 平滑后接近原始值。"""
        result = ConfidenceCalibrator.bayesian_smooth(0.80, 500)
        assert 0.78 < result < 0.82

    def test_weak_signal(self) -> None:
        """中等胜率 → 轻微向 0.5 靠拢。"""
        result = ConfidenceCalibrator.bayesian_smooth(0.55, 200)
        assert 0.53 < result < 0.57

    def test_small_sample_pulls_toward_prior(self) -> None:
        """小样本高胜率 → 被先验强力拉向 0.5。"""
        result = ConfidenceCalibrator.bayesian_smooth(0.90, 10)
        # (9 + 2) / (10 + 4) = 11/14 ≈ 0.786
        assert 0.75 < result < 0.85

    def test_large_sample_overwhelms_prior(self) -> None:
        """大样本 → 先验影响可忽略。"""
        result = ConfidenceCalibrator.bayesian_smooth(0.75, 10000)
        assert abs(result - 0.75) < 0.02

    def test_zero_hit_rate(self) -> None:
        """零胜率 → 被先验抬高。"""
        result = ConfidenceCalibrator.bayesian_smooth(0.0, 500)
        assert 0.0 <= result <= 0.01

    def test_perfect_hit_rate_smoothed_down(self) -> None:
        """完美胜率 → 被先验拉低。"""
        result = ConfidenceCalibrator.bayesian_smooth(1.0, 100)
        assert result < 1.0

    def test_prior_is_beta_uniform(self) -> None:
        """alpha=2, beta=2 时，先验均值为 0.5。"""
        result = ConfidenceCalibrator.bayesian_smooth(0.50, 0)
        # (0 + 2) / (0 + 4) = 0.5
        assert result == 0.50


class TestApplyFloor:
    def test_above_floor_unchanged(self) -> None:
        assert ConfidenceCalibrator.apply_floor(0.75) == 0.75

    def test_below_floor_raised(self) -> None:
        assert ConfidenceCalibrator.apply_floor(0.15, floor=0.30) == 0.30

    def test_exact_floor(self) -> None:
        assert ConfidenceCalibrator.apply_floor(0.30) == 0.30

    def test_default_floor(self) -> None:
        assert ConfidenceCalibrator.apply_floor(0.10) == 0.30


class TestShouldCalibrate:
    def test_insufficient_samples(self) -> None:
        cal = ConfidenceCalibrator(min_samples=100)
        assert cal.should_calibrate(50) is False

    def test_sufficient_samples(self) -> None:
        cal = ConfidenceCalibrator(min_samples=100)
        assert cal.should_calibrate(150) is True

    def test_exact_threshold(self) -> None:
        cal = ConfidenceCalibrator(min_samples=100)
        assert cal.should_calibrate(100) is True


class TestSelectBestMetrics:
    def test_picks_max_sample_count(self) -> None:
        metrics = [
            EvalMetrics(factor_name="alpha", horizon="1h", hit_rate=0.7, sample_count=50),
            EvalMetrics(factor_name="alpha", horizon="4h", hit_rate=0.6, sample_count=200),
            EvalMetrics(factor_name="beta", horizon="1h", hit_rate=0.8, sample_count=80),
        ]
        result = ConfidenceCalibrator._select_best_metrics(metrics)
        assert result["alpha"].sample_count == 200
        assert result["alpha"].horizon == "4h"
        assert result["beta"].sample_count == 80
        assert len(result) == 2

    def test_empty_list(self) -> None:
        result = ConfidenceCalibrator._select_best_metrics([])
        assert result == {}

    def test_single_factor(self) -> None:
        metrics = [EvalMetrics(factor_name="alpha", horizon="1d", hit_rate=0.6, sample_count=30)]
        result = ConfidenceCalibrator._select_best_metrics(metrics)
        assert len(result) == 1
        assert result["alpha"].horizon == "1d"


class TestModels:
    def test_per_factor_calibration_fields(self) -> None:
        c = PerFactorCalibration(
            factor_name="momentum",
            raw_hit_rate=0.65,
            sample_count=200,
            calibrated_confidence=0.63,
            cold_start=False,
        )
        assert len(c.factor_name) > 0
        assert 0.0 <= c.calibrated_confidence <= 1.0
        assert c.smoothing_params["alpha"] == 2.0
        assert c.smoothing_params["beta"] == 2.0

    def test_calibration_record_id_is_unique(self) -> None:
        r1 = CalibrationRecord(backtest_report_id="abc")
        r2 = CalibrationRecord(backtest_report_id="abc")
        assert r1.id != r2.id
        assert len(r1.id) == 32

    def test_calibration_record_defaults(self) -> None:
        r = CalibrationRecord(backtest_report_id="xyz")
        assert r.market_type == "spot"
        assert r.calibrations == []
        assert r.created_at_ms > 0


class TestPipelineInjection:
    """验证 confidence_overrides 通过 _inject_profile_metadata 生效。"""

    @staticmethod
    def _make_result(name, score, confidence, tier=None, category=None):
        from factors.enums import FactorCategory, FactorTier, SignalDirection
        from factors.models import DecisionTrace, FactorResult

        trace = DecisionTrace(factor_name=name, conclusion="test")
        return FactorResult(
            factor_name=name,
            factor_tier=tier or FactorTier.TIER_1,
            category=category or FactorCategory.FUND_FLOW,
            signal_direction=SignalDirection.BULLISH if score > 0 else SignalDirection.BEARISH,
            normalized_score=score,
            confidence=confidence,
            trace=trace,
        )

    def test_overrides_confidence_when_in_map(self) -> None:
        from factors import FactorPipeline
        from factors.ranking import RankingProfile

        profile = RankingProfile(
            profile_id="test", market_type="spot", description="",
            factors=[],
        )
        results = [self._make_result("alpha", 0.75, 0.85)]
        overrides = {"alpha": 0.42}
        updated = FactorPipeline._inject_profile_metadata(results, profile, overrides)
        assert updated[0].confidence == 0.42

    def test_keeps_hardcoded_when_not_in_map(self) -> None:
        from factors import FactorPipeline
        from factors.ranking import RankingProfile

        profile = RankingProfile(
            profile_id="test", market_type="spot", description="",
            factors=[],
        )
        results = [self._make_result("alpha", 0.75, 0.85)]
        updated = FactorPipeline._inject_profile_metadata(results, profile, confidence_overrides={})
        assert updated[0].confidence == 0.85

    def test_empty_overrides_no_change(self) -> None:
        from factors import FactorPipeline
        from factors.ranking import RankingProfile

        profile = RankingProfile(
            profile_id="test", market_type="spot", description="",
            factors=[],
        )
        results = [self._make_result("alpha", 0.75, 0.85)]
        updated = FactorPipeline._inject_profile_metadata(results, profile)
        assert updated[0].confidence == 0.85

    def test_partial_overrides(self) -> None:
        from factors import FactorPipeline
        from factors.enums import FactorCategory, FactorTier
        from factors.ranking import RankingProfile

        profile = RankingProfile(
            profile_id="test", market_type="spot", description="",
            factors=[],
        )
        results = [
            self._make_result("alpha", 0.75, 0.85),
            self._make_result("beta", -0.50, 0.70, FactorTier.TIER_2, FactorCategory.TECHNICAL),
        ]
        overrides = {"alpha": 0.42}  # only alpha gets override
        updated = FactorPipeline._inject_profile_metadata(results, profile, overrides)
        assert updated[0].confidence == 0.42
        assert updated[1].confidence == 0.70  # beta unchanged

    def test_also_injects_rank_weight_tier(self) -> None:
        from factors import FactorPipeline
        from factors.enums import FactorTier
        from factors.ranking import FactorEntry, RankingProfile

        entry = FactorEntry(factor_name="alpha", rank=3, tier=FactorTier.TIER_2, weight=4.0)
        profile = RankingProfile(
            profile_id="test", market_type="spot", description="",
            factors=[entry],
        )
        results = [self._make_result("alpha", 0.75, 0.85)]
        overrides = {"alpha": 0.42}
        updated = FactorPipeline._inject_profile_metadata(results, profile, overrides)
        r = updated[0]
        assert r.confidence == 0.42
        assert r.factor_index == 3
        assert r.factor_tier == FactorTier.TIER_2
        assert r.weight == 4.0
