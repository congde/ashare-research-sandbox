"""tests for factors/enums.py"""

import pytest

from factors.enums import (
    DataGranularity,
    FactorCategory,
    FactorTier,
    GranularityWeight,
    MarketType,
    SignalDirection,
)


class TestFactorTier:
    def test_tier_values(self) -> None:
        assert FactorTier.TIER_1 == "tier_1"
        assert FactorTier.TIER_2 == "tier_2"
        assert FactorTier.TIER_3 == "tier_3"
        assert FactorTier.TIER_4 == "tier_4"
        assert FactorTier.TIER_5 == "tier_5"

    def test_tier_from_string(self) -> None:
        assert FactorTier("tier_1") is FactorTier.TIER_1
        assert FactorTier("tier_5") is FactorTier.TIER_5

    def test_tier_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            FactorTier("tier_6")


class TestSignalDirection:
    def test_all_levels_present(self) -> None:
        expected = {
            "strong_bullish", "bullish", "neutral_bullish", "neutral",
            "neutral_bearish", "bearish", "strong_bearish", "inconclusive",
        }
        actual = {v.value for v in SignalDirection}
        assert actual == expected

    def test_from_string_roundtrip(self) -> None:
        for d in SignalDirection:
            assert SignalDirection(d.value) is d

    @pytest.mark.parametrize("raw", ["buy", "sell", "", "STRONG_BULLISH"])
    def test_invalid_direction_raises(self, raw: str) -> None:
        with pytest.raises(ValueError):
            SignalDirection(raw)


class TestFactorCategory:
    def test_count(self) -> None:
        assert len(FactorCategory) == 10

    def test_key_categories(self) -> None:
        assert FactorCategory.FUND_FLOW == "fund_flow"
        assert FactorCategory.WHALE_COST == "whale_cost"
        assert FactorCategory.AI_COMPOSITE == "ai_composite"
        assert FactorCategory.ONCHAIN == "onchain"
        assert FactorCategory.TECHNICAL == "technical"
        assert FactorCategory.DERIVATIVES == "derivatives"
        assert FactorCategory.META == "meta"


class TestDataGranularity:
    def test_short_granularities(self) -> None:
        assert DataGranularity.M5 == "5m"
        assert DataGranularity.H1 == "1h"
        assert DataGranularity.H24 == "24h"

    def test_long_granularities(self) -> None:
        assert DataGranularity.D7 == "7d"
        assert DataGranularity.D30 == "30d"
        assert DataGranularity.D90 == "90d"
        assert DataGranularity.Y1 == "1y"

    def test_from_string(self) -> None:
        assert DataGranularity("5m") is DataGranularity.M5
        assert DataGranularity("1h") is DataGranularity.H1
        assert DataGranularity("30d") is DataGranularity.D30


class TestMarketType:
    def test_values(self) -> None:
        assert MarketType.SPOT == "spot"
        assert MarketType.CONTRACT == "contract"

    def test_from_string(self) -> None:
        assert MarketType("spot") is MarketType.SPOT
        assert MarketType("contract") is MarketType.CONTRACT

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            MarketType("futures")


class TestGranularityWeight:
    def test_h24_heavier_than_m15(self) -> None:
        # IntEnum 对浮点值有截断，故只测试不同整数的比较
        assert GranularityWeight.H24 > GranularityWeight.M15

    def test_h1_heavier_than_m5(self) -> None:
        assert GranularityWeight.H1 >= GranularityWeight.M5
