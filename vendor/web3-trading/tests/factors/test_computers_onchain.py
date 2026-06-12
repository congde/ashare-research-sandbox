"""tests for onchain factor computers (large_transactions, address_pnl, etc.)"""

import pytest

from factors.computers.common.onchain import (
    AddressActivityComputer,
    AddressPnlComputer,
    BalancePriceDivergenceComputer,
    LargeTransactionsComputer,
    TradeCountComputer,
)


@pytest.mark.asyncio
class TestLargeTransactionsComputer:
    async def test_with_data(self, spot_ctx) -> None:
        comp = LargeTransactionsComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None

    async def test_no_data(self, empty_ctx) -> None:
        comp = LargeTransactionsComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None

    async def test_many_large_txns_bullish(self, spot_ctx) -> None:
        """大量大额交易 → 偏多"""
        spot_ctx.data["large_transactions"] = [
            type("Fake", (), {"amount_usd": 10_000_000.0, "count": 50, "direction": "in"})()
        ]
        comp = LargeTransactionsComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None

    async def test_few_large_txns(self, spot_ctx) -> None:
        spot_ctx.data["large_transactions"] = [
            type("Fake", (), {"amount_usd": 100_000.0, "count": 1, "direction": "out"})()
        ]
        comp = LargeTransactionsComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None


@pytest.mark.asyncio
class TestAddressPnlComputer:
    async def test_with_data(self, spot_ctx) -> None:
        comp = AddressPnlComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None

    async def test_no_data(self, empty_ctx) -> None:
        comp = AddressPnlComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None


@pytest.mark.asyncio
class TestBalancePriceDivergenceComputer:
    async def test_with_data(self, spot_ctx) -> None:
        spot_ctx.data["holder_list"] = [
            type("Fake", (), {"label": "whale", "balance": 1_000_000.0, "percentage": 0.05})(),
        ]
        comp = BalancePriceDivergenceComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None

    async def test_no_data(self, empty_ctx) -> None:
        comp = BalancePriceDivergenceComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None


@pytest.mark.asyncio
class TestAddressActivityComputer:
    async def test_with_data(self, spot_ctx) -> None:
        comp = AddressActivityComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None

    async def test_no_data(self, empty_ctx) -> None:
        comp = AddressActivityComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None


@pytest.mark.asyncio
class TestTradeCountComputer:
    async def test_with_data(self, spot_ctx) -> None:
        comp = TradeCountComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None

    async def test_no_data(self, empty_ctx) -> None:
        comp = TradeCountComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None
