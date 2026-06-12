"""tests for SentimentRatioComputer — 社交情绪比率因子"""

import pytest

from factors.computers.common.sentiment import SentimentRatioComputer
from factors.enums import SignalDirection


@pytest.mark.asyncio
class TestSentimentRatioComputer:
    async def test_bullish_high_bull_ratio(self, spot_ctx) -> None:
        spot_ctx.data["social_sentiment"] = type(
            "Fake", (), {"bullish_ratio": 0.8, "bearish_ratio": 0.2}
        )()

        comp = SentimentRatioComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None
        assert result.signal_direction == SignalDirection.BEARISH  # contrarian

    async def test_bearish_high_bear_ratio(self, spot_ctx) -> None:
        spot_ctx.data["social_sentiment"] = type(
            "Fake", (), {"bullish_ratio": 0.2, "bearish_ratio": 0.8}
        )()

        comp = SentimentRatioComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None
        assert result.signal_direction == SignalDirection.BULLISH  # contrarian

    async def test_neutral_balanced(self, spot_ctx) -> None:
        spot_ctx.data["social_sentiment"] = type(
            "Fake", (), {"bullish_ratio": 0.5, "bearish_ratio": 0.5}
        )()

        comp = SentimentRatioComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None

    async def test_inconclusive_no_data(self, empty_ctx) -> None:
        comp = SentimentRatioComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None


@pytest.mark.asyncio
class TestSentimentRatioComputerContract:
    """合约市场也支持情绪因子。"""

    async def test_with_contract_ctx(self, contract_ctx) -> None:
        comp = SentimentRatioComputer()
        result = await comp.compute_if_available(contract_ctx)
        assert result is not None
