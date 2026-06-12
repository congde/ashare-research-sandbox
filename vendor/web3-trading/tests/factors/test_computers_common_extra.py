"""tests for remaining common factor computers (fomo, grade, score, balance, etc.)"""

import pytest

from factors.computers.common.balance import BalanceTrendComputer
from factors.computers.common.fomo import FomoComputer
from factors.computers.common.grade import GradeComputer
from factors.computers.common.score import ScoreAndChangeComputer
from factors.enums import SignalDirection


@pytest.mark.asyncio
class TestFomoComputer:
    async def test_fomo_true(self, spot_ctx) -> None:
        spot_ctx.data["ai_chance"] = type("Fake", (), {"fomo": True})()
        comp = FomoComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None
        # FOMO is bearish (overheating warning)
        assert result.signal_direction in (
            SignalDirection.BEARISH,
            SignalDirection.STRONG_BEARISH,
            SignalDirection.NEUTRAL_BEARISH,
        )

    async def test_fomo_false(self, spot_ctx) -> None:
        spot_ctx.data["ai_chance"] = type("Fake", (), {"fomo": False})()
        comp = FomoComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None

    async def test_inconclusive_no_data(self, empty_ctx) -> None:
        comp = FomoComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None


@pytest.mark.asyncio
class TestGradeComputer:
    async def test_grade_1(self, spot_ctx) -> None:
        spot_ctx.data["ai_chance"] = type("Fake", (), {"grade": 1})()
        comp = GradeComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None

    async def test_grade_3(self, spot_ctx) -> None:
        spot_ctx.data["ai_chance"] = type("Fake", (), {"grade": 3})()
        comp = GradeComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None

    async def test_inconclusive_no_data(self, empty_ctx) -> None:
        comp = GradeComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None


@pytest.mark.asyncio
class TestScoreAndChangeComputer:
    async def test_high_score_positive_change(self, spot_ctx) -> None:
        spot_ctx.data["ai_chance"] = type(
            "Fake", (), {"score": 80.0, "score_change": 5.0}
        )()
        comp = ScoreAndChangeComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None

    async def test_low_score_negative_change(self, spot_ctx) -> None:
        spot_ctx.data["ai_chance"] = type(
            "Fake", (), {"score": 30.0, "score_change": -5.0}
        )()
        comp = ScoreAndChangeComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None

    async def test_inconclusive_no_data(self, empty_ctx) -> None:
        comp = ScoreAndChangeComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None


@pytest.mark.asyncio
class TestBalanceTrendComputer:
    async def test_with_holder_data(self, spot_ctx) -> None:
        spot_ctx.data["holder_list"] = [
            type("Fake", (), {"label": "whale", "balance": 1_000_000.0, "percentage": 0.05})(),
            type("Fake", (), {"label": "exchange", "balance": 500_000.0, "percentage": 0.02})(),
        ]
        spot_ctx.data["whale_cost"] = [
            type("Fake", (), {"cost": 100.0, "price": 95.0})()
        ]
        comp = BalanceTrendComputer()
        result = await comp.compute_if_available(spot_ctx)
        assert result is not None

    async def test_inconclusive_no_data(self, empty_ctx) -> None:
        comp = BalanceTrendComputer()
        result = await comp.compute_if_available(empty_ctx)
        assert result is None
