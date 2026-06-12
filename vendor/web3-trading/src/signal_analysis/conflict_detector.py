# -*- coding: utf-8 -*-
"""
Signal Conflict Detector — Phase 1.1

Detects contradictions between analysis dimensions (technical, onchain,
news, positioning) and computes confidence penalties.

Example conflicts:
  - Technical bullish + On-chain bearish (large outflows)
  - News bullish + Positioning bearish (heavy short interest)
  - On-chain bullish (whale accumulation) + News bearish (regulatory FUD)
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from web.api.signal_schema import (
    FactorsBlock,
    SignalConflict,
    ConsensusBlock,
)

logger = logging.getLogger(__name__)

# Direction mapping for comparison
_BULLISH_DIRECTIONS = {"bullish", "buy", "long", "positive"}
_BEARISH_DIRECTIONS = {"bearish", "sell", "short", "negative"}
_NEUTRAL_DIRECTIONS = {"neutral", "hold", "wait", "mixed"}

# Severity thresholds: (score_diff_threshold, severity_label)
_SEVERITY_THRESHOLDS = [
    (60, "high"),    # score diff >= 60 → high severity
    (30, "medium"),  # score diff >= 30 → medium severity
    (0, "low"),      # anything else → low severity
]

# Dimension pairs with known significance
_CRITICAL_PAIRS = {
    ("technical", "onchain"),      # price vs money flow
    ("onchain", "news"),           # money flow vs sentiment
    ("technical", "positioning"),   # price trend vs market positioning
}


def _classify_direction(direction: str) -> str:
    """Normalize direction string to bullish/bearish/neutral."""
    d = direction.strip().lower()
    if d in _BULLISH_DIRECTIONS:
        return "bullish"
    if d in _BEARISH_DIRECTIONS:
        return "bearish"
    return "neutral"


def _compute_severity(score_a: float, score_b: float, is_critical: bool) -> str:
    """Compute conflict severity based on score divergence."""
    diff = abs(score_a - score_b)
    if is_critical:
        diff *= 1.3  # critical pairs amplify severity
    for threshold, label in _SEVERITY_THRESHOLDS:
        if diff >= threshold:
            return label
    return "low"


def _confidence_penalty(severity: str) -> float:
    """Return confidence penalty for a given severity level."""
    return {"high": 25.0, "medium": 15.0, "low": 5.0}.get(severity, 0)


def detect_conflicts(factors: FactorsBlock) -> List[SignalConflict]:
    """
    Detect conflicts between analysis dimensions.

    Args:
        factors: FactorsBlock with technical/onchain/news/positioning scores.

    Returns:
        List of detected SignalConflict instances.
    """
    dims = {
        "technical": factors.technical,
        "onchain": factors.onchain,
        "news": factors.news,
        "positioning": factors.positioning,
    }

    conflicts: List[SignalConflict] = []
    checked = set()

    for name_a, factor_a in dims.items():
        for name_b, factor_b in dims.items():
            if name_a >= name_b:
                continue
            pair_key = (name_a, name_b)
            if pair_key in checked:
                continue
            checked.add(pair_key)

            dir_a = _classify_direction(factor_a.direction)
            dir_b = _classify_direction(factor_b.direction)

            # Only flag if directions genuinely oppose
            if dir_a == "neutral" or dir_b == "neutral":
                continue
            if dir_a == dir_b:
                continue

            # Opposing directions detected
            is_critical = pair_key in _CRITICAL_PAIRS or (
                (name_b, name_a) in _CRITICAL_PAIRS
            )
            severity = _compute_severity(
                factor_a.score, factor_b.score, is_critical
            )
            penalty = _confidence_penalty(severity)

            conflict = SignalConflict(
                dimensionA=name_a,
                dimensionB=name_b,
                directionA=dir_a,
                directionB=dir_b,
                severity=severity,
                description=(
                    f"{name_a}面{dir_a}(score={factor_a.score:.1f}) "
                    f"与 {name_b}面{dir_b}(score={factor_b.score:.1f}) 方向矛盾"
                ),
                confidenceImpact=penalty,
            )
            conflicts.append(conflict)
            logger.info(
                "Signal conflict detected: %s(%s) vs %s(%s), severity=%s",
                name_a, dir_a, name_b, dir_b, severity,
            )

    return conflicts


def compute_consensus(
    factors: FactorsBlock,
    conflicts: Optional[List[SignalConflict]] = None,
) -> ConsensusBlock:
    """
    Compute consensus from factor directions, accounting for conflicts.

    Returns an updated ConsensusBlock with agreement score and conflict info.
    """
    if conflicts is None:
        conflicts = detect_conflicts(factors)

    dims = {
        "technical": factors.technical,
        "onchain": factors.onchain,
        "news": factors.news,
        "positioning": factors.positioning,
    }

    # Count direction votes
    votes = {"bullish": 0, "bearish": 0, "neutral": 0}
    for factor in dims.values():
        d = _classify_direction(factor.direction)
        votes[d] = votes.get(d, 0) + 1

    total_dims = len(dims)
    max_vote = max(votes.values())
    agreement = max_vote / total_dims if total_dims > 0 else 0

    # Determine consensus direction
    if votes["bullish"] > votes["bearish"]:
        direction = "bullish"
    elif votes["bearish"] > votes["bullish"]:
        direction = "bearish"
    else:
        direction = "neutral"

    # Compute strength
    if agreement >= 0.75:
        strength = "strong"
    elif agreement >= 0.5:
        strength = "medium"
    else:
        strength = "weak"

    # If conflicts exist, downgrade strength
    high_conflicts = sum(1 for c in conflicts if c.severity == "high")
    if high_conflicts > 0 and strength == "strong":
        strength = "medium"
    if high_conflicts > 1:
        strength = "weak"

    # Build conflict description strings for legacy field
    conflict_strs = [c.description for c in conflicts]

    return ConsensusBlock(
        direction=direction,
        agreementScore=round(agreement, 3),
        strength=strength,
        conflicts=conflict_strs,
        detectedConflicts=conflicts,
    )


def apply_conflict_penalty(
    base_confidence: float,
    conflicts: List[SignalConflict],
    cap: float = 95.0,
) -> float:
    """
    Apply confidence penalty from detected conflicts.

    Args:
        base_confidence: Original confidence score (0~95).
        conflicts: Detected conflicts.
        cap: Maximum confidence cap.

    Returns:
        Adjusted confidence after penalty.
    """
    total_penalty = sum(c.confidenceImpact for c in conflicts)
    adjusted = max(0, base_confidence - total_penalty)
    return min(adjusted, cap)