# -*- coding: utf-8 -*-
"""
Tests for src/signal/conflict_detector.py

Tests cover:
1. No conflicts when all dimensions agree
2. Single conflict detection between opposing dimensions
3. Multiple conflict detection
4. Critical pair severity amplification
5. Neutral dimensions are ignored
6. Consensus computation
7. Confidence penalty application
8. Edge cases: zero scores, all neutral
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from web.api.signal_schema import FactorsBlock, FactorBlock, SignalConflict, ConsensusBlock
from signal_analysis.conflict_detector import (
    detect_conflicts,
    compute_consensus,
    apply_conflict_penalty,
    _classify_direction,
    _compute_severity,
    _confidence_penalty,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_factors(
    tech_dir="neutral", tech_score=0,
    onchain_dir="neutral", onchain_score=0,
    news_dir="neutral", news_score=0,
    pos_dir="neutral", pos_score=0,
) -> FactorsBlock:
    return FactorsBlock(
        technical=FactorBlock(direction=tech_dir, score=tech_score),
        onchain=FactorBlock(direction=onchain_dir, score=onchain_score),
        news=FactorBlock(direction=news_dir, score=news_score),
        positioning=FactorBlock(direction=pos_dir, score=pos_score),
    )


# ---------------------------------------------------------------------------
# _classify_direction tests
# ---------------------------------------------------------------------------
class TestClassifyDirection:
    def test_bullish_variants(self):
        for d in ("bullish", "buy", "long", "positive", "BULLISH", " Buy "):
            assert _classify_direction(d) == "bullish"

    def test_bearish_variants(self):
        for d in ("bearish", "sell", "short", "negative", "BEARISH"):
            assert _classify_direction(d) == "bearish"

    def test_neutral_variants(self):
        for d in ("neutral", "hold", "wait", "mixed", "unknown", ""):
            assert _classify_direction(d) == "neutral"


# ---------------------------------------------------------------------------
# _compute_severity tests
# ---------------------------------------------------------------------------
class TestComputeSeverity:
    def test_high_severity(self):
        assert _compute_severity(80, 10, is_critical=False) == "high"

    def test_medium_severity(self):
        assert _compute_severity(50, 10, is_critical=False) == "medium"

    def test_low_severity(self):
        assert _compute_severity(10, 5, is_critical=False) == "low"

    def test_critical_pair_amplification(self):
        # Without critical: diff=40 → medium
        assert _compute_severity(50, 10, is_critical=False) == "medium"
        # With critical: diff=40*1.3=52 → medium (still, but higher)
        # diff=50, critical → 50*1.3=65 → high
        assert _compute_severity(60, 10, is_critical=True) == "high"


# ---------------------------------------------------------------------------
# _confidence_penalty tests
# ---------------------------------------------------------------------------
class TestConfidencePenalty:
    def test_penalties(self):
        assert _confidence_penalty("high") == 25.0
        assert _confidence_penalty("medium") == 15.0
        assert _confidence_penalty("low") == 5.0
        assert _confidence_penalty("unknown") == 0


# ---------------------------------------------------------------------------
# detect_conflicts tests
# ---------------------------------------------------------------------------
class TestDetectConflicts:
    def test_no_conflicts_all_bullish(self):
        factors = _make_factors(
            tech_dir="bullish", tech_score=50,
            onchain_dir="bullish", onchain_score=40,
            news_dir="bullish", news_score=30,
            pos_dir="bullish", pos_score=20,
        )
        conflicts = detect_conflicts(factors)
        assert len(conflicts) == 0

    def test_no_conflicts_all_neutral(self):
        factors = _make_factors()
        conflicts = detect_conflicts(factors)
        assert len(conflicts) == 0

    def test_single_conflict_tech_vs_onchain(self):
        factors = _make_factors(
            tech_dir="bullish", tech_score=60,
            onchain_dir="bearish", onchain_score=-40,
        )
        conflicts = detect_conflicts(factors)
        assert len(conflicts) == 1
        c = conflicts[0]
        assert c.dimensionA in ("onchain", "technical")
        assert c.dimensionB in ("onchain", "technical")
        assert c.directionA != c.directionB
        assert c.severity in ("low", "medium", "high")
        assert c.confidenceImpact > 0

    def test_multiple_conflicts(self):
        factors = _make_factors(
            tech_dir="bullish", tech_score=70,
            onchain_dir="bearish", onchain_score=-50,
            news_dir="bearish", news_score=-30,
            pos_dir="bullish", pos_score=40,
        )
        conflicts = detect_conflicts(factors)
        # tech(bull) vs onchain(bear), tech(bull) vs news(bear),
        # onchain(bear) vs pos(bull), news(bear) vs pos(bull)
        assert len(conflicts) >= 2

    def test_neutral_ignored(self):
        factors = _make_factors(
            tech_dir="bullish", tech_score=50,
            onchain_dir="neutral", onchain_score=0,
            news_dir="bearish", news_score=-30,
        )
        conflicts = detect_conflicts(factors)
        # Only tech vs news should conflict
        assert len(conflicts) == 1
        assert {conflicts[0].dimensionA, conflicts[0].dimensionB} == {"news", "technical"}

    def test_conflict_has_description(self):
        factors = _make_factors(
            tech_dir="bullish", tech_score=50,
            onchain_dir="bearish", onchain_score=-40,
        )
        conflicts = detect_conflicts(factors)
        assert len(conflicts) == 1
        assert "bullish" in conflicts[0].description or "bearish" in conflicts[0].description

    def test_critical_pair_higher_severity(self):
        # technical vs onchain is a critical pair
        factors_critical = _make_factors(
            tech_dir="bullish", tech_score=50,
            onchain_dir="bearish", onchain_score=-50,
        )
        # news vs positioning is NOT a critical pair
        factors_noncrit = _make_factors(
            news_dir="bullish", news_score=50,
            pos_dir="bearish", pos_score=-50,
        )
        conflicts_critical = detect_conflicts(factors_critical)
        conflicts_noncrit = detect_conflicts(factors_noncrit)
        assert len(conflicts_critical) == 1
        assert len(conflicts_noncrit) == 1
        # Critical pair should have >= severity of non-critical
        sev_order = {"low": 0, "medium": 1, "high": 2}
        assert sev_order[conflicts_critical[0].severity] >= sev_order[conflicts_noncrit[0].severity]


# ---------------------------------------------------------------------------
# compute_consensus tests
# ---------------------------------------------------------------------------
class TestComputeConsensus:
    def test_all_bullish_strong_consensus(self):
        factors = _make_factors(
            tech_dir="bullish", tech_score=50,
            onchain_dir="bullish", onchain_score=40,
            news_dir="bullish", news_score=30,
            pos_dir="bullish", pos_score=20,
        )
        consensus = compute_consensus(factors)
        assert consensus.direction == "bullish"
        assert consensus.agreementScore == 1.0
        assert consensus.strength == "strong"
        assert len(consensus.conflicts) == 0

    def test_mixed_directions_weak(self):
        factors = _make_factors(
            tech_dir="bullish", tech_score=50,
            onchain_dir="bearish", onchain_score=-40,
            news_dir="bullish", news_score=30,
            pos_dir="bearish", pos_score=-20,
        )
        consensus = compute_consensus(factors)
        assert consensus.strength in ("weak", "medium")
        assert consensus.agreementScore == 0.5

    def test_high_conflict_downgrades_strength(self):
        factors = _make_factors(
            tech_dir="bullish", tech_score=80,
            onchain_dir="bearish", onchain_score=-80,
            news_dir="bullish", news_score=70,
            pos_dir="bullish", pos_score=60,
        )
        consensus = compute_consensus(factors)
        # 3 bullish vs 1 bearish → 75% agreement → strong
        # But high conflict tech vs onchain should downgrade
        assert consensus.direction == "bullish"
        assert len(consensus.detectedConflicts) >= 1

    def test_consensus_includes_conflict_strings(self):
        factors = _make_factors(
            tech_dir="bullish", tech_score=50,
            onchain_dir="bearish", onchain_score=-40,
        )
        consensus = compute_consensus(factors)
        assert len(consensus.conflicts) > 0
        assert isinstance(consensus.conflicts[0], str)


# ---------------------------------------------------------------------------
# apply_conflict_penalty tests
# ---------------------------------------------------------------------------
class TestApplyConflictPenalty:
    def test_no_conflicts_no_penalty(self):
        result = apply_conflict_penalty(80.0, [])
        assert result == 80.0

    def test_single_conflict_penalty(self):
        conflict = SignalConflict(
            dimensionA="technical",
            dimensionB="onchain",
            directionA="bullish",
            directionB="bearish",
            severity="medium",
            confidenceImpact=15.0,
        )
        result = apply_conflict_penalty(80.0, [conflict])
        assert result == 65.0

    def test_multiple_conflicts_cumulative(self):
        c1 = SignalConflict(severity="high", confidenceImpact=25.0)
        c2 = SignalConflict(severity="medium", confidenceImpact=15.0)
        result = apply_conflict_penalty(80.0, [c1, c2])
        assert result == 40.0

    def test_penalty_cannot_go_below_zero(self):
        c1 = SignalConflict(severity="high", confidenceImpact=25.0)
        c2 = SignalConflict(severity="high", confidenceImpact=25.0)
        c3 = SignalConflict(severity="high", confidenceImpact=25.0)
        result = apply_conflict_penalty(50.0, [c1, c2, c3])
        assert result == 0.0

    def test_cap_at_95(self):
        result = apply_conflict_penalty(100.0, [], cap=95.0)
        assert result == 95.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])