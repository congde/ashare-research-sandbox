"""tests for price/sector/social/meta factor computers"""

import pytest

from factors.computers.common.meta import HolderLabelsComputer, IdentifiersComputer
from factors.computers.common.price import (
    GainsDeclinesComputer,
    PriceMarketTypeComputer,
    SpotContractDivergenceComputer,
    TradeAmountComputer,
)
from factors.computers.common.sector import (
    CoinSectorRankComputer,
    RotationSpeedComputer,
    SectorRankComputer,
)
from factors.computers.common.social import MessageTypesComputer, SocialContentComputer


# ---------------------------------------------------------------------------
# Price computers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPriceMarketTypeComputer:
    async def test_with_data(self, spot_ctx) -> None:
        comp = PriceMarketTypeComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None

    async def test_no_data(self, empty_ctx) -> None:
        comp = PriceMarketTypeComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None


@pytest.mark.asyncio
class TestGainsDeclinesComputer:
    async def test_with_data(self, spot_ctx) -> None:
        comp = GainsDeclinesComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None

    async def test_no_data(self, empty_ctx) -> None:
        comp = GainsDeclinesComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None


@pytest.mark.asyncio
class TestTradeAmountComputer:
    async def test_with_data(self, spot_ctx) -> None:
        comp = TradeAmountComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None

    async def test_no_data(self, empty_ctx) -> None:
        comp = TradeAmountComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None


@pytest.mark.asyncio
class TestSpotContractDivergenceComputer:
    async def test_with_data(self, spot_ctx) -> None:
        comp = SpotContractDivergenceComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None

    async def test_no_data(self, empty_ctx) -> None:
        comp = SpotContractDivergenceComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None


# ---------------------------------------------------------------------------
# Sector computers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCoinSectorRankComputer:
    async def test_no_data(self, empty_ctx) -> None:
        comp = CoinSectorRankComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None

    async def test_with_sector_coin_list(self, spot_ctx) -> None:
        spot_ctx.data["sector_coin_list"] = [
            type("Fake", (), {
                "symbol": "BTC",
                "trade_inflow": 5_000_000.0,
            })(),
            type("Fake", (), {
                "symbol": "ETH",
                "trade_inflow": 3_000_000.0,
            })(),
        ]
        comp = CoinSectorRankComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None


@pytest.mark.asyncio
class TestSectorRankComputer:
    async def test_no_data(self, empty_ctx) -> None:
        comp = SectorRankComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None

    async def test_with_sector_fund_list(self, spot_ctx) -> None:
        spot_ctx.data["sector_fund_list"] = [
            type("Fake", (), {
                "sector_name": "DeFi",
                "trade_inflow": 10_000_000.0,
                "total_trade": 50_000_000.0,
            })(),
        ]
        comp = SectorRankComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None


@pytest.mark.asyncio
class TestRotationSpeedComputer:
    async def test_no_data(self, empty_ctx) -> None:
        comp = RotationSpeedComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None

    async def test_with_sector_fund_list(self, spot_ctx) -> None:
        spot_ctx.data["sector_fund_list"] = [
            type("Fake", (), {
                "sector_name": "DeFi",
                "trade_inflow": 10_000_000.0,
                "total_trade": 50_000_000.0,
            })(),
            type("Fake", (), {
                "sector_name": "L2",
                "trade_inflow": 5_000_000.0,
                "total_trade": 20_000_000.0,
            })(),
        ]
        comp = RotationSpeedComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None


# ---------------------------------------------------------------------------
# Social computers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSocialContentComputer:
    async def test_with_data(self, spot_ctx) -> None:
        comp = SocialContentComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None

    async def test_no_data(self, empty_ctx) -> None:
        comp = SocialContentComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None


@pytest.mark.asyncio
class TestMessageTypesComputer:
    async def test_with_data(self, spot_ctx) -> None:
        comp = MessageTypesComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None

    async def test_no_data(self, empty_ctx) -> None:
        comp = MessageTypesComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None


# ---------------------------------------------------------------------------
# Meta computers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestIdentifiersComputer:
    async def test_with_data(self, spot_ctx) -> None:
        comp = IdentifiersComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None

    async def test_no_data(self, empty_ctx) -> None:
        comp = IdentifiersComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is not None


@pytest.mark.asyncio
class TestHolderLabelsComputer:
    async def test_with_data(self, spot_ctx) -> None:
        comp = HolderLabelsComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None

    async def test_no_data(self, empty_ctx) -> None:
        comp = HolderLabelsComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None  # 无 holder_list，前提条件不满足

    async def test_with_data(self, spot_ctx) -> None:
        comp = HolderLabelsComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None
