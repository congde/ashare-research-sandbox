"""tests for factors/models.py"""

import numpy as np
import pytest

from factors.enums import DataGranularity, FactorCategory, FactorTier, SignalDirection
from factors.models import (
    CrossFactorResult,
    DecisionTrace,
    DerivativesSnapshot,
    EvidenceLink,
    FactorBundle,
    FactorMeta,
    FactorResult,
    FundingRateData,
    GranularityValue,
    KlineFrame,
    KlineSnapshot,
    OpenInterestData,
)


# ---------------------------------------------------------------------------
# EvidenceLink
# ---------------------------------------------------------------------------


class TestEvidenceLink:
    def test_create_valid(self) -> None:
        link = EvidenceLink(
            data_point="净流入: +1.2M",
            interpretation="资金持续流入",
            implication="可能出现上涨",
            confidence=0.8,
        )
        assert link.data_point == "净流入: +1.2M"
        assert link.confidence == 0.8

    def test_confidence_bounds(self) -> None:
        with pytest.raises(Exception):
            EvidenceLink(data_point="x", interpretation="y", implication="z", confidence=1.5)
        with pytest.raises(Exception):
            EvidenceLink(data_point="x", interpretation="y", implication="z", confidence=-0.1)

    def test_immutable(self) -> None:
        link = EvidenceLink(data_point="x", interpretation="y", implication="z", confidence=0.5)
        with pytest.raises(Exception):
            link.confidence = 0.9  # type: ignore


# ---------------------------------------------------------------------------
# DecisionTrace
# ---------------------------------------------------------------------------


class TestDecisionTrace:
    def test_minimal_trace(self) -> None:
        trace = DecisionTrace(factor_name="test", conclusion="中性信号")
        assert trace.factor_name == "test"
        assert trace.evidence_chain == []
        assert trace.raw_inputs == {}
        assert trace.suggested_action == ""
        assert trace.limitations == []

    def test_full_trace(self, sample_evidence) -> None:
        trace = DecisionTrace(
            factor_name="deviation",
            raw_inputs={"price": 95.0},
            evidence_chain=[sample_evidence],
            conclusion="看多",
            suggested_action="买入",
            limitations=["数据延迟"],
            counter_argument="主力可能已离场",
        )
        assert len(trace.evidence_chain) == 1
        assert trace.counter_argument != ""

    def test_list_is_copyable(self) -> None:
        trace = DecisionTrace(factor_name="test", conclusion="neutral")
        trace.evidence_chain.append(EvidenceLink(
            data_point="x", interpretation="y", implication="z", confidence=0.5
        ))
        assert len(trace.evidence_chain) == 1


# ---------------------------------------------------------------------------
# FactorMeta
# ---------------------------------------------------------------------------


class TestFactorMeta:
    def test_create(self) -> None:
        meta = FactorMeta(
            factor_name="deviation",
            category=FactorCategory.WHALE_COST,
            display_name="主力成本偏离度",
            description="计算主力成本偏离",
            requires_data=["whale_cost"],
        )
        assert meta.factor_name == "deviation"
        assert meta.category is FactorCategory.WHALE_COST
        assert meta.display_name == "主力成本偏离度"


# ---------------------------------------------------------------------------
# GranularityValue
# ---------------------------------------------------------------------------


class TestGranularityValue:
    def test_create(self) -> None:
        gv = GranularityValue(granularity=DataGranularity.H1, value=0.5, weight=0.8)
        assert gv.value == 0.5
        assert gv.weight == 0.8

    def test_weight_default(self) -> None:
        gv = GranularityValue(granularity=DataGranularity.H24, value=-0.3)
        assert gv.weight == 1.0


# ---------------------------------------------------------------------------
# FactorResult
# ---------------------------------------------------------------------------


class TestFactorResult:
    def test_immutable(self, sample_result) -> None:
        with pytest.raises(Exception):
            sample_result.normalized_score = 0.9  # type: ignore

    def test_model_copy_update(self, sample_result) -> None:
        updated = sample_result.model_copy(update={"normalized_score": 0.9})
        assert updated.normalized_score == 0.9
        assert sample_result.normalized_score == 0.6  # 原实例不变

    def test_score_bounds(self, sample_trace) -> None:
        with pytest.raises(Exception):
            FactorResult(
                factor_name="bad", factor_tier=FactorTier.TIER_1,
                category=FactorCategory.META, display_name="bad",
                signal_direction=SignalDirection.NEUTRAL,
                normalized_score=5.0, confidence=0.5, trace=sample_trace,
            )

    def test_granularity_breakdown_optional(self, sample_result) -> None:
        assert sample_result.granularity_breakdown is None


# ---------------------------------------------------------------------------
# CrossFactorResult
# ---------------------------------------------------------------------------


class TestCrossFactorResult:
    def test_create(self, sample_trace) -> None:
        cr = CrossFactorResult(
            cross_name="deviation_x_trade_inflow",
            parent_factors=["deviation", "spot_trade_inflow"],
            formula="deviation * sign(inflow)",
            signal_direction=SignalDirection.BULLISH,
            normalized_score=0.5,
            confidence=0.7,
            trace=sample_trace,
        )
        assert cr.cross_name == "deviation_x_trade_inflow"
        assert len(cr.parent_factors) == 2


# ---------------------------------------------------------------------------
# FactorBundle
# ---------------------------------------------------------------------------


class TestFactorBundle:
    def test_empty_bundle(self) -> None:
        bundle = FactorBundle(vs_token_id="token_001")
        assert bundle.all_results == []
        assert bundle.aggregate_score == 0.0
        assert bundle.overall_completeness == 0.0

    def test_tier_partitioning(self, sample_result) -> None:
        t1_result = sample_result.model_copy(update={"factor_tier": FactorTier.TIER_1})
        t2_result = sample_result.model_copy(update={"factor_tier": FactorTier.TIER_2})
        bundle = FactorBundle(
            vs_token_id="token_001",
            tier1_results=[t1_result],
            tier2_results=[t2_result],
        )
        assert len(bundle.tier1_results) == 1
        assert len(bundle.tier2_results) == 1
        assert len(bundle.all_results) == 2

    def test_aggregate_score_weighted(self, sample_trace) -> None:
        r1 = FactorResult(
            factor_name="f1", factor_tier=FactorTier.TIER_1,
            category=FactorCategory.FUND_FLOW, display_name="f1",
            signal_direction=SignalDirection.BULLISH,
            normalized_score=0.8, confidence=0.9, weight=7.0, trace=sample_trace,
        )
        r2 = FactorResult(
            factor_name="f2", factor_tier=FactorTier.TIER_2,
            category=FactorCategory.TECHNICAL, display_name="f2",
            signal_direction=SignalDirection.BEARISH,
            normalized_score=-0.4, confidence=0.8, weight=4.0, trace=sample_trace,
        )
        bundle = FactorBundle(
            vs_token_id="token_001",
            tier1_results=[r1],
            tier2_results=[r2],
        )
        # weighted: (0.8*7 + (-0.4)*4) / (7+4) = (5.6 - 1.6) / 11 = 4.0/11 ≈ 0.364
        expected = (0.8 * 7.0 + (-0.4) * 4.0) / 11.0
        assert bundle.aggregate_score == pytest.approx(expected)

    def test_aggregate_excludes_zero_confidence(self, sample_trace) -> None:
        r = FactorResult(
            factor_name="no_conf", factor_tier=FactorTier.TIER_1,
            category=FactorCategory.META, display_name="nc",
            signal_direction=SignalDirection.INCONCLUSIVE,
            normalized_score=0.9, confidence=0.0, weight=7.0, trace=sample_trace,
        )
        bundle = FactorBundle(vs_token_id="t", tier1_results=[r])
        assert bundle.aggregate_score == 0.0

    def test_cross_factors_contribute(self, sample_trace) -> None:
        cr = CrossFactorResult(
            cross_name="test_x", parent_factors=["a", "b"],
            formula="a * b",
            signal_direction=SignalDirection.BULLISH,
            normalized_score=0.9, confidence=0.8, trace=sample_trace,
        )
        bundle = FactorBundle(vs_token_id="t", cross_factors=[cr])
        assert bundle.aggregate_score == 0.9  # 1.5 weight solo

    def test_completeness(self) -> None:
        bundle = FactorBundle(vs_token_id="t", overall_completeness=0.85)
        assert bundle.overall_completeness == 0.85

    def test_errors_collected(self) -> None:
        bundle = FactorBundle(vs_token_id="t", errors=["timeout: factor_x"])
        assert len(bundle.errors) == 1

    def test_immutable(self) -> None:
        bundle = FactorBundle(vs_token_id="token_001")
        with pytest.raises(Exception):
            bundle.tier1_results.append(MagicMock())  # type: ignore


# ---------------------------------------------------------------------------
# KlineFrame
# ---------------------------------------------------------------------------


class TestKlineFrame:
    def test_create(self) -> None:
        close = np.array([100.0, 101.0, 102.0])
        high = np.array([102.0, 103.0, 104.0])
        low = np.array([99.0, 100.0, 101.0])
        volume = np.array([1000.0, 1100.0, 900.0])
        frame = KlineFrame(close=close, high=high, low=low, volume=volume)
        assert len(frame.close) == 3
        assert frame.close[0] == 100.0

    def test_immutable(self) -> None:
        frame = KlineFrame(
            close=np.array([1.0]), high=np.array([1.0]),
            low=np.array([1.0]), volume=np.array([1.0]),
        )
        with pytest.raises(Exception):
            frame.close = np.array([2.0])  # type: ignore


# ---------------------------------------------------------------------------
# KlineSnapshot
# ---------------------------------------------------------------------------


class TestKlineSnapshot:
    def test_empty_snapshot(self) -> None:
        snap = KlineSnapshot()
        assert snap.is_empty
        assert snap.tf_1h is None

    def test_partial_snapshot(self, kline_frame_1h) -> None:
        snap = KlineSnapshot(tf_1h=kline_frame_1h)
        assert not snap.is_empty
        assert snap.tf_1d is None

    def test_immutable(self) -> None:
        snap = KlineSnapshot()
        with pytest.raises(Exception):
            snap.tf_1h = None  # type: ignore


# ---------------------------------------------------------------------------
# FundingRateData / OpenInterestData / DerivativesSnapshot
# ---------------------------------------------------------------------------


class TestFundingRateData:
    def test_current(self) -> None:
        fr = FundingRateData(values=[0.001, 0.002, 0.0015])
        assert fr.current == 0.0015

    def test_current_empty(self) -> None:
        fr = FundingRateData(values=[])
        assert fr.current is None

    def test_values_are_readable(self) -> None:
        fr = FundingRateData(values=[0.001, 0.002])
        assert fr.values == [0.001, 0.002]
        assert fr.current == 0.002


class TestOpenInterestData:
    def test_current(self) -> None:
        oi = OpenInterestData(values=[1_000_000, 1_100_000])
        assert oi.current == 1_100_000


class TestDerivativesSnapshot:
    def test_empty(self) -> None:
        snap = DerivativesSnapshot()
        assert snap.is_empty

    def test_partial(self) -> None:
        snap = DerivativesSnapshot(funding_rate=FundingRateData(values=[0.001]))
        assert not snap.is_empty
