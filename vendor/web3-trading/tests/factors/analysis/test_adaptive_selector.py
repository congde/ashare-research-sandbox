# -*- coding: utf-8 -*-
"""自适应 Profile 选择与合成单元测试。"""

import pytest

from factors.analysis.adaptive_selector import AdaptiveProfileSelector, ProfileComposer
from factors.analysis.models import MarketState, MarketStateResult
from factors.enums import FactorTier, MarketType
from factors.ranking.profile import FactorEntry, RankingProfile
from factors.ranking.profiles import build_state_profile


def _make_simple_profile() -> RankingProfile:
    """构造简化的测试用 RankingProfile。"""
    return RankingProfile(
        profile_id="test_profile",
        market_type=MarketType.SPOT,
        factors=[
            FactorEntry(factor_name="trend_strength", rank=1, weight=7.0, tier=FactorTier.TIER_1),
            FactorEntry(factor_name="spot_trade_inflow", rank=2, weight=7.0, tier=FactorTier.TIER_1),
            FactorEntry(factor_name="sentiment_ratio", rank=3, weight=4.0, tier=FactorTier.TIER_2),
            FactorEntry(factor_name="rsi_extreme", rank=4, weight=4.0, tier=FactorTier.TIER_2),
        ],
    )


class TestAdaptiveProfileSelector:
    def test_select_returns_state_profile(self) -> None:
        selector = AdaptiveProfileSelector(_make_simple_profile())
        state_result = MarketStateResult(
            state=MarketState.TRENDING_UP,
            confidence=0.85,
        )
        sp = selector.select(state_result)
        assert sp.state == MarketState.TRENDING_UP
        assert len(sp.biases) > 0

    def test_caches_state_profiles(self) -> None:
        selector = AdaptiveProfileSelector(_make_simple_profile())
        state_result = MarketStateResult(state=MarketState.RANGING, confidence=0.7)
        sp1 = selector.get_state_profile(MarketState.RANGING)
        sp2 = selector.get_state_profile(MarketState.RANGING)
        assert sp1 is sp2  # same instance (cached)

    def test_get_all_relevant_profiles(self) -> None:
        selector = AdaptiveProfileSelector(_make_simple_profile())
        state_result = MarketStateResult(
            state=MarketState.TRENDING_UP,
            confidence=0.85,
            adjacent_states=[MarketState.RANGING],
            adjacent_weights=[0.15],
        )
        profiles = selector.get_all_relevant_profiles(state_result)
        assert MarketState.TRENDING_UP in profiles
        assert MarketState.RANGING in profiles


class TestProfileComposer:
    def test_compose_single_state_no_bias_change(self) -> None:
        """单状态且 bias=1.0 时权重不变。"""
        base = _make_simple_profile()
        # 构造所有 bias=1.0 的 state profile
        state_result = MarketStateResult(state=MarketState.RANGING, confidence=0.7)

        # Use the actual build_state_profile to get real StateProfile
        sp = build_state_profile(MarketState.RANGING)
        # Override all biases to 1.0
        sp = sp.model_copy(update={
            "biases": [
                b.model_copy(update={"bias_multiplier": 1.0})
                for b in sp.biases
            ],
        })

        composed = ProfileComposer.compose(
            base, state_result, {MarketState.RANGING: sp},
        )
        for e in composed.factors:
            orig = next(f for f in base.factors if f.factor_name == e.factor_name)
            assert e.weight == pytest.approx(orig.weight, abs=0.01)

    def test_compose_trending_up_boosts_technical(self) -> None:
        """TRENDING_UP 状态应提升技术面因子权重。"""
        base = _make_simple_profile()
        state_result = MarketStateResult(state=MarketState.TRENDING_UP, confidence=0.85)
        sp = build_state_profile(MarketState.TRENDING_UP)
        composed = ProfileComposer.compose(
            base, state_result, {MarketState.TRENDING_UP: sp},
        )
        # trend_strength (TECHNICAL) should have higher weight than spot_trade_inflow (FUND_FLOW) after normalization
        ts_w = next(e for e in composed.factors if e.factor_name == "trend_strength").weight
        sti_w = next(e for e in composed.factors if e.factor_name == "spot_trade_inflow").weight
        # Both were originally 7.0, but technical gets ×1.5, fund_flow gets ×1.0
        assert ts_w > sti_w

    def test_compose_two_states_interpolation(self) -> None:
        """两个状态的混合应正确插值。"""
        base = _make_simple_profile()
        state_result = MarketStateResult(
            state=MarketState.TRENDING_UP,
            confidence=0.85,
            adjacent_states=[MarketState.RANGING],
            adjacent_weights=[0.2],
        )
        sp_trending = build_state_profile(MarketState.TRENDING_UP)
        sp_ranging = build_state_profile(MarketState.RANGING)
        composed = ProfileComposer.compose(
            base, state_result,
            {MarketState.TRENDING_UP: sp_trending, MarketState.RANGING: sp_ranging},
        )
        assert composed.profile_id.endswith("_adaptive")
        assert composed.market_type == MarketType.SPOT

    def test_compose_preserves_factor_count(self) -> None:
        """合成后因子数量不变。"""
        base = _make_simple_profile()
        state_result = MarketStateResult(state=MarketState.RANGING, confidence=0.7)
        sp = build_state_profile(MarketState.RANGING)
        composed = ProfileComposer.compose(
            base, state_result, {MarketState.RANGING: sp},
        )
        assert len(composed.factors) == len(base.factors)

    def test_empty_adjacent_states(self) -> None:
        """无相邻状态时不抛异常。"""
        base = _make_simple_profile()
        state_result = MarketStateResult(state=MarketState.RANGING, confidence=0.7)
        sp = build_state_profile(MarketState.RANGING)
        composed = ProfileComposer.compose(
            base, state_result, {MarketState.RANGING: sp},
        )
        assert composed is not None
