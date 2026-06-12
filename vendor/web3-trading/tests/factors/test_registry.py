"""tests for factors/registry.py"""

from factors.enums import FactorCategory, MarketType
from factors.registry import FactorRegistry
from factors.ranking import SPOT_DEFAULT_PROFILE, CONTRACT_DEFAULT_PROFILE


class TestFactorRegistry:
    def test_loads_all_computers(self) -> None:
        registry = FactorRegistry()
        names = registry.list_factor_names()
        assert len(names) >= 39  # should find all 39

    def test_get_computer_by_name(self) -> None:
        registry = FactorRegistry()
        dev = registry.get_computer("deviation")
        assert dev is not None
        assert dev.factor_name == "deviation"

    def test_get_nonexistent(self) -> None:
        registry = FactorRegistry()
        assert registry.get_computer("nonexistent_factor") is None

    def test_filter_by_market_spot(self) -> None:
        registry = FactorRegistry()
        spot_computers = registry.get_computers(market_type=MarketType.SPOT)
        for c in spot_computers:
            assert MarketType.SPOT in c.supported_markets

    def test_filter_by_market_contract(self) -> None:
        registry = FactorRegistry()
        contract_computers = registry.get_computers(market_type=MarketType.CONTRACT)
        for c in contract_computers:
            assert MarketType.CONTRACT in c.supported_markets

    def test_filter_by_category(self) -> None:
        registry = FactorRegistry()
        fund_flow = registry.get_computers(
            categories={FactorCategory.FUND_FLOW}, market_type=MarketType.SPOT
        )
        assert len(fund_flow) > 0
        for c in fund_flow:
            assert c.category == FactorCategory.FUND_FLOW

    def test_get_by_spot_profile(self) -> None:
        registry = FactorRegistry()
        computers = registry.get_computers_by_profile(SPOT_DEFAULT_PROFILE)
        assert len(computers) > 0
        # all returned computers should support SPOT
        for c in computers:
            assert MarketType.SPOT in c.supported_markets

    def test_get_by_contract_profile(self) -> None:
        registry = FactorRegistry()
        computers = registry.get_computers_by_profile(CONTRACT_DEFAULT_PROFILE)
        assert len(computers) > 0
        for c in computers:
            assert MarketType.CONTRACT in c.supported_markets

    def test_summary(self) -> None:
        registry = FactorRegistry()
        summary = registry.summary()
        assert "FactorRegistry" in summary
        assert "loaded" in summary

    def test_cache_is_reused(self) -> None:
        r1 = FactorRegistry()
        r2 = FactorRegistry()
        assert r1.list_factor_names() == r2.list_factor_names()

    def test_spot_specific_factors_present(self) -> None:
        registry = FactorRegistry()
        spot_factors = [
            c.factor_name
            for c in registry.get_computers(market_type=MarketType.SPOT)
        ]
        assert "spot_trade_inflow" in spot_factors
        assert "spot_consistency" in spot_factors

    def test_contract_specific_factors_present(self) -> None:
        registry = FactorRegistry()
        contract_factors = [
            c.factor_name
            for c in registry.get_computers(market_type=MarketType.CONTRACT)
        ]
        assert "contract_trade_inflow" in contract_factors
        assert "funding_rate_zscore" in contract_factors

    def test_common_factors_visible_to_both(self) -> None:
        registry = FactorRegistry()
        spot = set(c.factor_name for c in registry.get_computers(market_type=MarketType.SPOT))
        contract = set(c.factor_name for c in registry.get_computers(market_type=MarketType.CONTRACT))
        common = spot & contract
        assert "deviation" in common
        assert "sentiment_ratio" in common
        assert "trend_strength" in common
