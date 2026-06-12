"""tests for DeviationComputer — 主力成本偏离度因子"""

import pytest

from factors.computers.common.deviation import DeviationComputer
from factors.enums import FactorCategory, SignalDirection


@pytest.mark.asyncio
class TestDeviationComputer:
    async def test_bullish_price_below_cost(self, spot_ctx) -> None:
        """价格低于主力成本超过 20% → STRONG_BULLISH"""
        spot_ctx.current_price = 70.0
        spot_ctx.data["whale_cost"] = [type("Fake", (), {"cost": 100.0, "price": 70.0})]
        spot_ctx.data["ai_chance"] = None

        comp = DeviationComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None
        assert result.signal_direction == SignalDirection.STRONG_BULLISH
        assert result.normalized_score > 0
        assert result.trace.conclusion != ""
        assert result.trace.suggested_action != ""

    async def test_bearish_price_above_cost(self, spot_ctx) -> None:
        """价格高于主力成本超过 30% → STRONG_BEARISH"""
        spot_ctx.current_price = 140.0
        spot_ctx.data["whale_cost"] = [type("Fake", (), {"cost": 100.0, "price": 140.0})]
        spot_ctx.data["ai_chance"] = None

        comp = DeviationComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None
        assert result.signal_direction == SignalDirection.STRONG_BEARISH
        assert result.normalized_score < 0

    async def test_neutral(self, spot_ctx) -> None:
        """偏离度在 ±5% 内 → NEUTRAL"""
        spot_ctx.current_price = 102.0
        spot_ctx.data["whale_cost"] = [type("Fake", (), {"cost": 100.0, "price": 102.0})]
        spot_ctx.data["ai_chance"] = None

        comp = DeviationComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None
        assert result.signal_direction == SignalDirection.NEUTRAL

    async def test_inconclusive_no_data(self, empty_ctx) -> None:
        """无 whale_cost 数据 → INCONCLUSIVE"""
        comp = DeviationComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None  # prerequisite check fails

    async def test_inconclusive_explicit(self, spot_ctx) -> None:
        """compute 在无数据时返回 INCONCLUSIVE"""
        spot_ctx.data["whale_cost"] = []
        spot_ctx.data["ai_chance"] = None
        spot_ctx.current_price = 0.0

        comp = DeviationComputer()
        result = await comp.compute(spot_ctx)
        assert result.signal_direction == SignalDirection.INCONCLUSIVE
        assert result.confidence == 0.0

    async def test_uses_ai_deviation_if_available(self, spot_ctx) -> None:
        """优先使用 AI chance 中的偏离度"""
        spot_ctx.data["ai_chance"] = type(
            "Fake", (), {"deviation": -15.0}
        )()
        spot_ctx.data["whale_cost"] = [type("Fake", (), {"cost": 100.0, "price": 95.0})]

        comp = DeviationComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None
        assert result.raw_value == pytest.approx(-15.0)

    async def test_metadata(self, spot_ctx) -> None:
        """验证因子元数据"""
        comp = DeviationComputer()
        meta = comp.meta()
        assert meta.factor_name == "deviation"
        assert meta.category == FactorCategory.WHALE_COST
        assert "whale_cost" in meta.requires_data

    async def test_check_prerequisites(self, spot_ctx, empty_ctx) -> None:
        comp = DeviationComputer()
        assert comp.check_prerequisites(spot_ctx) is True
        assert comp.check_prerequisites(empty_ctx) is False

    async def test_with_contract_ctx(self, contract_ctx) -> None:
        """合约市场也适用"""
        comp = DeviationComputer()
        result = await comp.compute_if_available(contract_ctx)
        assert result is not None
