"""tests for spot-specific factor computers (consistency, inflow, market_cap_ratio, etc.)"""

import pytest

from factors.computers.spot.consistency import SpotConsistencyComputer
from factors.computers.spot.inflow import SpotTradeInflowComputer
from factors.computers.spot.market_cap_ratio import SpotMarketCapRatioComputer
from factors.computers.spot.max_inflow import SpotMaxInflowComputer
from factors.computers.spot.persistence import SpotPersistenceComputer
from factors.computers.spot.snapshot import SpotFundSnapshotComputer


@pytest.mark.asyncio
class TestSpotConsistencyComputer:
    async def test_with_data(self, spot_ctx) -> None:
        comp = SpotConsistencyComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None

    async def test_no_data(self, empty_ctx) -> None:
        comp = SpotConsistencyComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None

    async def test_contract_ctx_computes(self, contract_ctx) -> None:
        """现货专用因子在合约市场仍可通过 prereq（realtime_fund 存在且为对象）"""
        comp = SpotConsistencyComputer()
        result = await comp.compute_if_available(contract_ctx)
        # spot goods_list 可能为空，但 prereq 通过，compute 会产出结果
        assert result is not None


@pytest.mark.asyncio
class TestSpotTradeInflowComputer:
    async def test_with_data(self, spot_ctx) -> None:
        comp = SpotTradeInflowComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None

    async def test_no_data(self, empty_ctx) -> None:
        comp = SpotTradeInflowComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None


@pytest.mark.asyncio
class TestSpotMarketCapRatioComputer:
    async def test_with_data(self, spot_ctx) -> None:
        comp = SpotMarketCapRatioComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None

    async def test_no_data(self, empty_ctx) -> None:
        comp = SpotMarketCapRatioComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None


@pytest.mark.asyncio
class TestSpotMaxInflowComputer:
    async def test_with_data(self, spot_ctx) -> None:
        comp = SpotMaxInflowComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None

    async def test_no_data(self, empty_ctx) -> None:
        comp = SpotMaxInflowComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None


@pytest.mark.asyncio
class TestSpotPersistenceComputer:
    async def test_with_data(self, spot_ctx) -> None:
        comp = SpotPersistenceComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None

    async def test_no_data(self, empty_ctx) -> None:
        comp = SpotPersistenceComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None


@pytest.mark.asyncio
class TestSpotFundSnapshotComputer:
    async def test_with_data(self, spot_ctx) -> None:
        comp = SpotFundSnapshotComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None

    async def test_no_data(self, empty_ctx) -> None:
        comp = SpotFundSnapshotComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None
