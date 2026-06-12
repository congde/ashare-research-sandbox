"""tests for factors/ranking/profile.py and factors/ranking/presets.py"""

import pytest

from factors.enums import FactorTier, MarketType
from factors.ranking import (
    CONTRACT_DEFAULT_PROFILE,
    SPOT_DEFAULT_PROFILE,
    FactorEntry,
    RankingProfile,
)


class TestFactorEntry:
    def test_create(self) -> None:
        entry = FactorEntry(
            factor_name="spot_trade_inflow", rank=1, weight=7.0, tier=FactorTier.TIER_1
        )
        assert entry.factor_name == "spot_trade_inflow"
        assert entry.rank == 1
        assert entry.weight == 7.0
        assert entry.tier == FactorTier.TIER_1

    def test_rank_must_be_positive(self) -> None:
        with pytest.raises(Exception):
            FactorEntry(factor_name="x", rank=0, weight=1.0, tier=FactorTier.TIER_1)

    def test_weight_non_negative(self) -> None:
        with pytest.raises(Exception):
            FactorEntry(factor_name="x", rank=1, weight=-0.1, tier=FactorTier.TIER_1)

    def test_immutable(self) -> None:
        entry = FactorEntry(factor_name="x", rank=1, weight=1.0, tier=FactorTier.TIER_1)
        with pytest.raises(Exception):
            entry.weight = 2.0  # type: ignore


class TestRankingProfile:
    @pytest.fixture
    def profile(self) -> RankingProfile:
        return RankingProfile(
            profile_id="test",
            market_type=MarketType.SPOT,
            description="test profile",
            factors=[
                FactorEntry(factor_name="f1", rank=1, weight=7.0, tier=FactorTier.TIER_1),
                FactorEntry(factor_name="f2", rank=2, weight=4.0, tier=FactorTier.TIER_2),
                FactorEntry(factor_name="f3", rank=3, weight=0.0, tier=FactorTier.TIER_5),
            ],
        )

    def test_get_entry_found(self, profile) -> None:
        entry = profile.get_entry("f1")
        assert entry is not None
        assert entry.weight == 7.0

    def test_get_entry_not_found(self, profile) -> None:
        assert profile.get_entry("nonexistent") is None

    def test_get_weight(self, profile) -> None:
        assert profile.get_weight("f1") == 7.0
        assert profile.get_weight("missing") == 0.0

    def test_get_rank(self, profile) -> None:
        assert profile.get_rank("f2") == 2
        assert profile.get_rank("missing") == 999

    def test_get_tier(self, profile) -> None:
        assert profile.get_tier("f3") == FactorTier.TIER_5
        assert profile.get_tier("missing") is None

    def test_active_factors_filters_zero_weight(self, profile) -> None:
        active = profile.active_factors()
        assert "f1" in active
        assert "f2" in active
        assert "f3" not in active  # weight=0

    def test_top_n(self, profile) -> None:
        top = profile.top_n(2)
        assert len(top) == 2
        assert top[0] == "f1"
        assert top[1] == "f2"

    def test_factor_names_sorted_by_rank(self, profile) -> None:
        names = profile.factor_names()
        assert names == ["f1", "f2", "f3"]

    def test_as_weight_map(self, profile) -> None:
        wm = profile.as_weight_map()
        assert wm["f1"] == 7.0
        assert wm["f3"] == 0.0

    def test_profile_id_field(self) -> None:
        profile = RankingProfile(
            profile_id="test", market_type=MarketType.SPOT, factors=[]
        )
        assert profile.profile_id == "test"
        # profile_id 是不可变的 frozen 字段
        with pytest.raises(Exception):
            profile.profile_id = "changed"  # type: ignore


class TestPresetProfiles:
    """验证两个默认 Profile 的基本结构。"""

    def test_spot_profile_id(self) -> None:
        assert SPOT_DEFAULT_PROFILE.profile_id == "spot_default"
        assert SPOT_DEFAULT_PROFILE.market_type == MarketType.SPOT

    def test_contract_profile_id(self) -> None:
        assert CONTRACT_DEFAULT_PROFILE.profile_id == "contract_default"
        assert CONTRACT_DEFAULT_PROFILE.market_type == MarketType.CONTRACT

    def test_spot_profile_has_41_factors(self) -> None:
        # 31 fundamental + 10 K-line
        assert len(SPOT_DEFAULT_PROFILE.factors) == 41

    def test_contract_profile_has_44_factors(self) -> None:
        # 31 fundamental + 13 K-line
        assert len(CONTRACT_DEFAULT_PROFILE.factors) == 44

    def test_all_spot_factors_have_positive_weight(self) -> None:
        for f in SPOT_DEFAULT_PROFILE.factors:
            assert f.weight > 0

    def test_all_contract_factors_have_positive_weight(self) -> None:
        for f in CONTRACT_DEFAULT_PROFILE.factors:
            assert f.weight > 0

    def test_spot_tier1_weight_is_7(self) -> None:
        for f in SPOT_DEFAULT_PROFILE.factors:
            if f.tier == FactorTier.TIER_1:
                assert f.weight == pytest.approx(7.0)

    def test_contract_tier1_weight_is_6(self) -> None:
        for f in CONTRACT_DEFAULT_PROFILE.factors:
            if f.tier == FactorTier.TIER_1:
                assert f.weight == pytest.approx(6.0)

    def test_profile_ranks_are_sequential(self) -> None:
        ranks = [f.rank for f in SPOT_DEFAULT_PROFILE.factors]
        assert ranks == sorted(ranks)
        assert len(set(ranks)) == len(ranks)
