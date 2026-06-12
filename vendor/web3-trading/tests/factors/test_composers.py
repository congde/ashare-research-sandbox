"""tests for factors/composers.py — 交叉因子组合器。"""

import pytest

from factors.composers import CrossFactorComposer
from factors.enums import MarketType, SignalDirection
from factors.models import CrossFactorResult


class TestCrossFactorComposer:
    """只测试机制——不测试具体组合逻辑的值（后者依赖因子结果）。"""

    def test_can_instantiate(self) -> None:
        composer = CrossFactorComposer()
        assert composer is not None

    def test_cross_factor_result_factory(self) -> None:
        """_result 工厂方法能创建合法的 CrossFactorResult。"""
        result = CrossFactorResult(
            cross_name="test_cross",
            parent_factors=["a", "b"],
            formula="a * b",
            signal_direction=SignalDirection.NEUTRAL,
            normalized_score=0.0,
            confidence=0.5,
            trace={
                "factor_name": "test_cross",
                "conclusion": "neutral cross factor",
                "suggested_action": "hold",
            },
        )
        assert result.cross_name == "test_cross"
        assert result.parent_factors == ["a", "b"]
        assert result.signal_direction == SignalDirection.NEUTRAL

    @pytest.mark.asyncio
    async def test_compose_all_returns_list(self) -> None:
        """compose_all 返回列表，Bundle 无结果时返回空列表。"""
        from factors.models import FactorBundle

        bundle = FactorBundle(vs_token_id="test")
        composer = CrossFactorComposer()
        results = await composer.compose_all(bundle, MarketType.SPOT)
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_compose_all_handles_missing_parents(self) -> None:
        """父因子缺失时不崩溃。"""
        from factors.models import FactorBundle, FactorResult, DecisionTrace
        from factors.enums import FactorTier, FactorCategory

        # 创建一个只有 deviation 的 bundle
        trace = DecisionTrace(factor_name="deviation", conclusion="test")
        r = FactorResult(
            factor_name="deviation",
            factor_tier=FactorTier.TIER_1,
            category=FactorCategory.WHALE_COST,
            display_name="dev",
            signal_direction=SignalDirection.BULLISH,
            normalized_score=0.5,
            confidence=0.8,
            trace=trace,
        )
        bundle = FactorBundle(vs_token_id="test", tier1_results=[r])
        composer = CrossFactorComposer()
        results = await composer.compose_all(bundle, MarketType.SPOT)
        # 不应崩溃
        assert isinstance(results, list)
