"""tests for factors/utils.py"""

import math

import pytest

from factors.enums import DataGranularity, SignalDirection
from factors.utils import (
    TIME_PARTICLE_TO_GRANULARITY,
    clamp_score,
    compute_change_rate,
    directional_consensus,
    extract_inflows,
    gran_to_tpe,
    normalize_to_bipolar,
    score_to_direction,
)


class FakeTradeRecord:
    def __init__(self, tpe: int, inflow: float):
        self.time_particle_enum = tpe
        self.trade_inflow = inflow


# ---------------------------------------------------------------------------
# normalize_to_bipolar
# ---------------------------------------------------------------------------


class TestNormalizeToBipolar:
    def test_zero_value_zero_center(self) -> None:
        assert normalize_to_bipolar(0.0, center=0.0, scale=1.0) == pytest.approx(0.0)

    def test_positive_value(self) -> None:
        result = normalize_to_bipolar(1.0, center=0.0, scale=1.0)
        assert result > 0.5  # tanh(1) ≈ 0.76

    def test_negative_value(self) -> None:
        result = normalize_to_bipolar(-1.0, center=0.0, scale=1.0)
        assert result < -0.5  # tanh(-1) ≈ -0.76

    def test_bounded_by_one(self) -> None:
        result = normalize_to_bipolar(100.0, center=0.0, scale=1.0)
        assert -1.0 <= result <= 1.0

    def test_center_shifts_midpoint(self) -> None:
        # 值等于 center 时 result ≈ 0
        assert normalize_to_bipolar(50.0, center=50.0, scale=10.0) == pytest.approx(0.0)

    def test_scale_compresses(self) -> None:
        small = normalize_to_bipolar(10.0, center=0.0, scale=100.0)
        large = normalize_to_bipolar(10.0, center=0.0, scale=1.0)
        assert abs(small) < abs(large)

    def test_zero_scale_returns_zero(self) -> None:
        assert normalize_to_bipolar(5.0, center=0.0, scale=0.0) == 0.0
        assert normalize_to_bipolar(5.0, center=0.0, scale=-1.0) == 0.0

    def test_monotonic(self) -> None:
        a = normalize_to_bipolar(-10.0, center=0.0, scale=10.0)
        b = normalize_to_bipolar(0.0, center=0.0, scale=10.0)
        c = normalize_to_bipolar(10.0, center=0.0, scale=10.0)
        assert a < b < c


# ---------------------------------------------------------------------------
# clamp_score
# ---------------------------------------------------------------------------


class TestClampScore:
    def test_within_range(self) -> None:
        assert clamp_score(0.5) == 0.5

    def test_above_upper(self) -> None:
        assert clamp_score(1.5) == 1.0

    def test_below_lower(self) -> None:
        assert clamp_score(-2.0) == -1.0

    def test_custom_bounds(self) -> None:
        assert clamp_score(10.0, low=0.0, high=5.0) == 5.0

    def test_boundary_values(self) -> None:
        assert clamp_score(1.0) == 1.0
        assert clamp_score(-1.0) == -1.0


# ---------------------------------------------------------------------------
# extract_inflows
# ---------------------------------------------------------------------------


class TestExtractInflows:
    def test_single_record_matching(self) -> None:
        records = [FakeTradeRecord(tpe=101, inflow=500_000.0)]
        result = extract_inflows(records, [DataGranularity.H1])
        assert result[DataGranularity.H1] == 500_000.0

    def test_accumulates_same_granularity(self) -> None:
        records = [
            FakeTradeRecord(tpe=101, inflow=100_000.0),
            FakeTradeRecord(tpe=101, inflow=200_000.0),
        ]
        result = extract_inflows(records, [DataGranularity.H1])
        assert result[DataGranularity.H1] == 300_000.0

    def test_multiple_granularities(self) -> None:
        records = [
            FakeTradeRecord(tpe=5, inflow=10_000.0),
            FakeTradeRecord(tpe=15, inflow=20_000.0),
            FakeTradeRecord(tpe=101, inflow=50_000.0),
            FakeTradeRecord(tpe=124, inflow=100_000.0),
        ]
        result = extract_inflows(
            records, [DataGranularity.M5, DataGranularity.M15, DataGranularity.H1, DataGranularity.H24]
        )
        assert result[DataGranularity.M5] == 10_000.0
        assert result[DataGranularity.M15] == 20_000.0
        assert result[DataGranularity.H1] == 50_000.0
        assert result[DataGranularity.H24] == 100_000.0

    def test_empty_records(self) -> None:
        result = extract_inflows([], [DataGranularity.H1])
        assert result[DataGranularity.H1] == 0.0

    def test_none_records(self) -> None:
        result = extract_inflows(None, [DataGranularity.H1])
        assert result[DataGranularity.H1] == 0.0

    def test_unknown_time_particle_ignored(self) -> None:
        records = [FakeTradeRecord(tpe=999, inflow=50_000.0)]
        result = extract_inflows(records, [DataGranularity.H1])
        assert result[DataGranularity.H1] == 0.0

    def test_zero_initialized_for_all_requested(self) -> None:
        result = extract_inflows([], [DataGranularity.H1, DataGranularity.H24, DataGranularity.D7])
        assert len(result) == 3
        assert all(v == 0.0 for v in result.values())


# ---------------------------------------------------------------------------
# compute_change_rate
# ---------------------------------------------------------------------------


class TestComputeChangeRate:
    def test_positive_change(self) -> None:
        assert compute_change_rate(120.0, 100.0) == pytest.approx(0.2)

    def test_negative_change(self) -> None:
        assert compute_change_rate(80.0, 100.0) == pytest.approx(-0.2)

    def test_zero_previous_zero_current(self) -> None:
        assert compute_change_rate(0.0, 0.0) == 0.0

    def test_zero_previous_positive_current(self) -> None:
        assert compute_change_rate(100.0, 0.0) == 1.0

    def test_zero_previous_negative_current(self) -> None:
        assert compute_change_rate(-100.0, 0.0) == -1.0

    def test_negative_previous(self) -> None:
        # current=-80, previous=-100 → change = (-80 - (-100)) / 100 = 0.2
        assert compute_change_rate(-80.0, -100.0) == pytest.approx(0.2)


# ---------------------------------------------------------------------------
# directional_consensus
# ---------------------------------------------------------------------------


class TestDirectionalConsensus:
    def test_all_positive(self) -> None:
        assert directional_consensus([0.5, 0.3, 0.8]) == pytest.approx(1.0)

    def test_all_negative(self) -> None:
        assert directional_consensus([-0.5, -0.3, -0.8]) == pytest.approx(-1.0)

    def test_mixed(self) -> None:
        result = directional_consensus([0.5, -0.5])
        assert result == pytest.approx(0.0)

    def test_mostly_positive(self) -> None:
        result = directional_consensus([0.3, 0.2, -0.1])
        assert result > 0

    def test_empty_list(self) -> None:
        assert directional_consensus([]) == 0.0

    def test_all_neutral_within_threshold(self) -> None:
        assert directional_consensus([0.01, -0.02, 0.03]) == 0.0

    def test_custom_threshold(self) -> None:
        # 0.15 应当被 filter
        assert directional_consensus([0.15], threshold=0.2) == 0.0
        assert directional_consensus([0.15], threshold=0.1) == 1.0


# ---------------------------------------------------------------------------
# score_to_direction
# ---------------------------------------------------------------------------


class TestScoreToDirection:
    def test_strong_bullish(self) -> None:
        assert score_to_direction(0.6) is SignalDirection.STRONG_BULLISH
        assert score_to_direction(0.51) is SignalDirection.STRONG_BULLISH

    def test_bullish(self) -> None:
        assert score_to_direction(0.3) is SignalDirection.BULLISH
        assert score_to_direction(0.16) is SignalDirection.BULLISH

    def test_neutral_bullish(self) -> None:
        assert score_to_direction(0.1) is SignalDirection.NEUTRAL_BULLISH
        assert score_to_direction(0.04) is SignalDirection.NEUTRAL_BULLISH

    def test_neutral(self) -> None:
        assert score_to_direction(0.0) is SignalDirection.NEUTRAL
        assert score_to_direction(0.02) is SignalDirection.NEUTRAL
        assert score_to_direction(-0.02) is SignalDirection.NEUTRAL

    def test_neutral_bearish(self) -> None:
        assert score_to_direction(-0.1) is SignalDirection.NEUTRAL_BEARISH
        assert score_to_direction(-0.04) is SignalDirection.NEUTRAL_BEARISH

    def test_bearish(self) -> None:
        assert score_to_direction(-0.3) is SignalDirection.BEARISH
        assert score_to_direction(-0.16) is SignalDirection.BEARISH

    def test_strong_bearish(self) -> None:
        assert score_to_direction(-0.6) is SignalDirection.STRONG_BEARISH
        assert score_to_direction(-0.51) is SignalDirection.STRONG_BEARISH

    def test_boundary_exact(self) -> None:
        assert score_to_direction(0.5) is SignalDirection.BULLISH  # not > 0.5
        assert score_to_direction(0.15) is SignalDirection.NEUTRAL_BULLISH  # not > 0.15
        assert score_to_direction(0.03) is SignalDirection.NEUTRAL  # not > 0.03
        assert score_to_direction(-0.03) is SignalDirection.NEUTRAL
        assert score_to_direction(-0.15) is SignalDirection.NEUTRAL_BEARISH  # >= -0.15
        assert score_to_direction(-0.5) is SignalDirection.BEARISH  # >= -0.5


# ---------------------------------------------------------------------------
# gran_to_tpe
# ---------------------------------------------------------------------------


class TestGranToTpe:
    def test_known_mappings(self) -> None:
        assert gran_to_tpe(DataGranularity.M5) == 5
        assert gran_to_tpe(DataGranularity.M15) == 15
        assert gran_to_tpe(DataGranularity.M30) == 30
        assert gran_to_tpe(DataGranularity.H1) == 101
        assert gran_to_tpe(DataGranularity.H8) == 108
        assert gran_to_tpe(DataGranularity.H24) == 124

    def test_unknown_returns_zero(self) -> None:
        assert gran_to_tpe(DataGranularity.D7) == 0


# ---------------------------------------------------------------------------
# TIME_PARTICLE_TO_GRANULARITY table
# ---------------------------------------------------------------------------


class TestTimeParticleToGranularity:
    def test_known_keys(self) -> None:
        assert TIME_PARTICLE_TO_GRANULARITY[5] is DataGranularity.M5
        assert TIME_PARTICLE_TO_GRANULARITY[15] is DataGranularity.M15
        assert TIME_PARTICLE_TO_GRANULARITY[101] is DataGranularity.H1
        assert TIME_PARTICLE_TO_GRANULARITY[124] is DataGranularity.H24

    def test_roundtrip_with_gran_to_tpe(self) -> None:
        for tpe, gran in TIME_PARTICLE_TO_GRANULARITY.items():
            assert gran_to_tpe(gran) == tpe
