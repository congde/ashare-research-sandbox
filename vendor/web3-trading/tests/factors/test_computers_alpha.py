"""tests for AlphaComputer — Alpha 信号因子"""

import pytest

from factors.computers.common.alpha import AlphaComputer
from factors.enums import SignalDirection


@pytest.mark.asyncio
class TestAlphaComputer:
    async def test_bullish_with_alpha_chance(self, spot_ctx) -> None:
        spot_ctx.data["ai_chance"] = type("Fake", (), {"alpha": True})()
        spot_ctx.data["ai_risk"] = type("Fake", (), {"alpha": False})()
        spot_ctx.data["ai_funds"] = type("Fake", (), {"alpha": False})()

        comp = AlphaComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None
        assert result.signal_direction == SignalDirection.STRONG_BULLISH

    async def test_bearish_with_alpha_risk(self, spot_ctx) -> None:
        spot_ctx.data["ai_chance"] = type("Fake", (), {"alpha": False})()
        spot_ctx.data["ai_risk"] = type("Fake", (), {"alpha": True})()
        spot_ctx.data["ai_funds"] = type("Fake", (), {"alpha": False})()

        comp = AlphaComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None
        assert result.signal_direction == SignalDirection.STRONG_BEARISH

    async def test_inconclusive_no_data(self, empty_ctx) -> None:
        comp = AlphaComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None
