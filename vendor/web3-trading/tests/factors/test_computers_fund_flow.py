"""tests for fund-flow factor computers (trade_inflow_change, trade_ratio, etc.)"""

import pytest

from factors.computers.common.trade_inflow_change import TradeInflowChangeComputer
from factors.computers.common.trade_ratio import TradeRatioComputer
from factors.enums import SignalDirection


# ---------------------------------------------------------------------------
# TradeInflowChangeComputer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTradeInflowChangeComputer:
    async def test_with_token_flow(self, spot_ctx) -> None:
        comp = TradeInflowChangeComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None

    async def test_inconclusive_no_data(self, empty_ctx) -> None:
        comp = TradeInflowChangeComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None

    async def test_strong_inflow(self, spot_ctx) -> None:
        """多粒度高流入 → 看涨"""
        spot_ctx.data["token_flow"] = [
            type("Fake", (), {"time_particle_enum": 5, "trade_inflow": 100_000.0})(),
            type("Fake", (), {"time_particle_enum": 15, "trade_inflow": 300_000.0})(),
            type("Fake", (), {"time_particle_enum": 101, "trade_inflow": 1_000_000.0})(),
            type("Fake", (), {"time_particle_enum": 124, "trade_inflow": 5_000_000.0})(),
        ]
        comp = TradeInflowChangeComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None

    async def test_contract_context(self, contract_ctx) -> None:
        comp = TradeInflowChangeComputer()
        result = await comp.compute_if_available(contract_ctx)
        assert result is not None


# ---------------------------------------------------------------------------
# TradeRatioComputer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTradeRatioComputer:
    async def test_with_realtime_fund(self, spot_ctx) -> None:
        comp = TradeRatioComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None

    async def test_inconclusive_no_data(self, empty_ctx) -> None:
        comp = TradeRatioComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None

    async def test_high_inflow_ratio(self, spot_ctx) -> None:
        """inflow 远大于 outflow → BULLISH"""
        from tests.factors.conftest import FakeRealtimeFund, FakeTradeDataItem

        spot_ctx.data["realtime_fund"] = FakeRealtimeFund(
            spot_goods_list=[
                FakeTradeDataItem(
                    time_particle_enum=101,
                    trade_inflow=5_000_000.0,
                    total_trade=6_000_000.0,
                    trade_in=5_000_000.0,
                    trade_out=1_000_000.0,
                )
            ]
        )
        comp = TradeRatioComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None

    async def test_contract_context(self, contract_ctx) -> None:
        comp = TradeRatioComputer()
        result = await comp.compute_if_available(contract_ctx)
        assert result is not None
