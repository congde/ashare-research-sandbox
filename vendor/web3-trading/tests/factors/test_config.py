"""tests for factors/config.py"""

import pytest

from factors.config import PipelineConfig
from factors.enums import MarketType
from factors.ranking import (
    CONTRACT_DEFAULT_PROFILE,
    SPOT_DEFAULT_PROFILE,
    RankingProfile,
)


class TestPipelineConfig:
    def test_default_profile(self) -> None:
        cfg = PipelineConfig()
        assert cfg.market_type == MarketType.SPOT

    def test_for_spot(self) -> None:
        cfg = PipelineConfig.for_spot()
        assert cfg.ranking_profile.profile_id == "spot_default"
        assert cfg.market_type == MarketType.SPOT

    def test_for_contract(self) -> None:
        cfg = PipelineConfig.for_contract()
        assert cfg.ranking_profile.profile_id == "contract_default"
        assert cfg.market_type == MarketType.CONTRACT

    def test_mvp_filters_low_weight(self) -> None:
        cfg = PipelineConfig.mvp()
        for entry in cfg.ranking_profile.factors:
            assert entry.weight > 1.0

    def test_standard_uses_spot(self) -> None:
        cfg = PipelineConfig.standard()
        assert cfg.ranking_profile.profile_id == "spot_default"

    def test_full_uses_spot(self) -> None:
        cfg = PipelineConfig.full()
        assert cfg.ranking_profile.profile_id == "spot_default"

    def test_custom_profile(self) -> None:
        custom = RankingProfile(
            profile_id="test_custom",
            market_type=MarketType.SPOT,
            description="custom test",
            factors=[],
        )
        cfg = PipelineConfig.custom(custom)
        assert cfg.ranking_profile.profile_id == "test_custom"

    def test_timeout_defaults(self) -> None:
        cfg = PipelineConfig()
        assert cfg.compute_timeout_s == 30.0
        assert cfg.single_factor_timeout_s == 10.0

    def test_concurrency_defaults(self) -> None:
        cfg = PipelineConfig()
        assert cfg.max_concurrent_factors == 20
        assert cfg.max_concurrent_tokens == 10

    def test_normalization_defaults(self) -> None:
        cfg = PipelineConfig()
        assert cfg.inflow_normalization_scale == 10_000_000.0
        assert cfg.deviation_normalization_scale == 100.0

    def test_immutable(self) -> None:
        cfg = PipelineConfig()
        with pytest.raises(Exception):
            cfg.compute_timeout_s = 60.0  # type: ignore

    def test_model_copy_update(self) -> None:
        cfg = PipelineConfig()
        updated = cfg.model_copy(update={"compute_timeout_s": 60.0})
        assert updated.compute_timeout_s == 60.0
        assert cfg.compute_timeout_s == 30.0  # unchanged
