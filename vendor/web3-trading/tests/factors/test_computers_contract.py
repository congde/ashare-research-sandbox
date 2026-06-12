"""tests for contract-specific factor computers (consistency, inflow, OI change, etc.)"""

import pytest

from factors.computers.contract.consistency import ContractConsistencyComputer
from factors.computers.contract.inflow import ContractTradeInflowComputer
from factors.computers.contract.long_short_extreme import LongShortExtremeComputer
from factors.computers.contract.market_cap_ratio import ContractMarketCapRatioComputer
from factors.computers.contract.max_inflow import ContractMaxInflowComputer
from factors.computers.contract.oi_change_rate import OIChangeRateComputer
from factors.computers.contract.persistence import ContractPersistenceComputer
from factors.computers.contract.snapshot import ContractFundSnapshotComputer


@pytest.mark.asyncio
class TestContractConsistencyComputer:
    async def test_with_data(self, contract_ctx) -> None:
        comp = ContractConsistencyComputer()
        result = await comp.compute_if_available(contract_ctx)
        assert result is not None

    async def test_no_data(self, empty_ctx) -> None:
        comp = ContractConsistencyComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None

    async def test_with_spot_context(self, spot_ctx) -> None:
        """合约专用因子在现货上下文中仍可计算（realtime_fund 包含 contract_list）"""
        comp = ContractConsistencyComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None


@pytest.mark.asyncio
class TestContractTradeInflowComputer:
    async def test_with_data(self, contract_ctx) -> None:
        comp = ContractTradeInflowComputer()
        result = await comp.compute_if_available(contract_ctx)
        assert result is not None

    async def test_no_data(self, empty_ctx) -> None:
        comp = ContractTradeInflowComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None


@pytest.mark.asyncio
class TestLongShortExtremeComputer:
    async def test_with_data(self, contract_ctx) -> None:
        comp = LongShortExtremeComputer()
        result = await comp.compute_if_available(contract_ctx)
        assert result is not None

    async def test_no_data(self, empty_ctx) -> None:
        comp = LongShortExtremeComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None


@pytest.mark.asyncio
class TestContractMarketCapRatioComputer:
    async def test_with_data(self, contract_ctx) -> None:
        comp = ContractMarketCapRatioComputer()
        result = await comp.compute_if_available(contract_ctx)
        assert result is not None

    async def test_no_data(self, empty_ctx) -> None:
        comp = ContractMarketCapRatioComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None


@pytest.mark.asyncio
class TestContractMaxInflowComputer:
    async def test_with_data(self, contract_ctx) -> None:
        comp = ContractMaxInflowComputer()
        result = await comp.compute_if_available(contract_ctx)
        assert result is not None

    async def test_no_data(self, empty_ctx) -> None:
        comp = ContractMaxInflowComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None


@pytest.mark.asyncio
class TestOIChangeRateComputer:
    async def test_with_data(self, contract_ctx) -> None:
        comp = OIChangeRateComputer()
        result = await comp.compute_if_available(contract_ctx)
        assert result is not None

    async def test_no_data(self, empty_ctx) -> None:
        comp = OIChangeRateComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None


@pytest.mark.asyncio
class TestContractPersistenceComputer:
    async def test_with_data(self, contract_ctx) -> None:
        comp = ContractPersistenceComputer()
        result = await comp.compute_if_available(contract_ctx)
        assert result is not None

    async def test_no_data(self, empty_ctx) -> None:
        comp = ContractPersistenceComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None


@pytest.mark.asyncio
class TestContractFundSnapshotComputer:
    async def test_with_data(self, contract_ctx) -> None:
        comp = ContractFundSnapshotComputer()
        result = await comp.compute_if_available(contract_ctx)
        assert result is not None

    async def test_no_data(self, empty_ctx) -> None:
        comp = ContractFundSnapshotComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None
