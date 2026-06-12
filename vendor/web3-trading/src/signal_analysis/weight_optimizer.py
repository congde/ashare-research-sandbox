# -*- coding: utf-8 -*-
"""
Signal Weight Optimizer — Phase 1.4

Computes adaptive weights for each analysis dimension based on
historical signal accuracy from the SignalTracker.

Dimensions: technical, onchain, news, positioning
Default equal weights: 0.25 each.
Adaptive weights shift toward dimensions with higher recent accuracy.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional

from web.api.signal_schema import DimensionWeight

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DIMENSIONS = ("technical", "onchain", "news", "positioning")
DEFAULT_WEIGHT = 1.0 / len(DIMENSIONS)  # 0.25
MIN_WEIGHT = 0.10          # no dimension drops below 10%
MAX_WEIGHT = 0.50          # no dimension exceeds 50%
MIN_SAMPLES = 10           # need at least N samples before adapting
SMOOTHING_ALPHA = 0.3      # EMA smoothing for accuracy updates


def compute_adaptive_weights(
    per_dimension_accuracy: Dict[str, Dict[str, Any]],
    prior_weights: Optional[Dict[str, float]] = None,
) -> List[DimensionWeight]:
    """
    Compute adaptive weights from per-dimension accuracy stats.

    Args:
        per_dimension_accuracy: Dict from SignalTracker.get_accuracy_stats(),
            format: { "technical": {"total": 50, "correct": 35, "accuracy": 0.7}, ... }
        prior_weights: Previous adaptive weights (for EMA smoothing).

    Returns:
        List of DimensionWeight with updated adaptive weights.
    """
    if prior_weights is None:
        prior_weights = {d: DEFAULT_WEIGHT for d in DIMENSIONS}

    raw_scores: Dict[str, float] = {}
    sample_sizes: Dict[str, int] = {}

    for dim in DIMENSIONS:
        stats = per_dimension_accuracy.get(dim, {})
        accuracy = stats.get("accuracy", 0.5)  # default 50% if unknown
        total = stats.get("total", 0)
        sample_sizes[dim] = total

        if total < MIN_SAMPLES:
            # Not enough data — keep default weight
            raw_scores[dim] = DEFAULT_WEIGHT
        else:
            # Use accuracy as raw score, with a slight boost for high-accuracy dims
            # Apply sigmoid-like scaling to avoid extreme swings
            raw_scores[dim] = _sigmoid_scale(accuracy)

    # Normalize raw scores to sum to 1.0
    total_score = sum(raw_scores.values())
    if total_score <= 0:
        normalized = {d: DEFAULT_WEIGHT for d in DIMENSIONS}
    else:
        normalized = {d: raw_scores[d] / total_score for d in DIMENSIONS}

    # Apply EMA smoothing with prior weights
    smoothed = {}
    for dim in DIMENSIONS:
        prior = prior_weights.get(dim, DEFAULT_WEIGHT)
        target = normalized[dim]
        if sample_sizes[dim] >= MIN_SAMPLES:
            smoothed[dim] = SMOOTHING_ALPHA * target + (1 - SMOOTHING_ALPHA) * prior
        else:
            smoothed[dim] = prior  # no update if insufficient data

    # Clamp to [MIN_WEIGHT, MAX_WEIGHT] and re-normalize
    clamped = {d: max(MIN_WEIGHT, min(MAX_WEIGHT, w)) for d, w in smoothed.items()}
    clamp_total = sum(clamped.values())
    final = {d: clamped[d] / clamp_total for d in DIMENSIONS}

    # Build output
    result = []
    for dim in DIMENSIONS:
        stats = per_dimension_accuracy.get(dim, {})
        result.append(DimensionWeight(
            dimension=dim,
            baseWeight=DEFAULT_WEIGHT,
            adaptiveWeight=round(final[dim], 4),
            recentAccuracy=round(stats.get("accuracy", 0), 4),
            sampleSize=sample_sizes.get(dim, 0),
        ))

    logger.info(
        "Adaptive weights: %s",
        {dw.dimension: dw.adaptiveWeight for dw in result},
    )
    return result


def apply_weighted_score(
    factor_scores: Dict[str, float],
    weights: List[DimensionWeight],
) -> float:
    """
    Compute weighted composite score from dimension scores and adaptive weights.

    Args:
        factor_scores: {"technical": 30.0, "onchain": -10.0, ...}
        weights: List of DimensionWeight

    Returns:
        Weighted composite score (-100 ~ 100).
    """
    weight_map = {dw.dimension: dw.adaptiveWeight for dw in weights}
    total = 0.0
    for dim, score in factor_scores.items():
        w = weight_map.get(dim, DEFAULT_WEIGHT)
        total += score * w

    # Clamp to [-100, 100]
    return max(-100.0, min(100.0, total))


def _sigmoid_scale(accuracy: float) -> float:
    """
    Apply sigmoid-like scaling to accuracy (0~1) for weight computation.
    Maps 0.5 → ~0.25 (neutral), 0.8 → ~0.38, 0.3 → ~0.15

    This prevents extreme weight swings from accuracy fluctuations.
    """
    # Shift so 0.5 accuracy → 0, then apply tanh for smooth scaling
    shifted = (accuracy - 0.5) * 4  # range roughly [-2, 2]
    scaled = (math.tanh(shifted) + 1) / 2  # map to [0, 1]
    return max(0.05, scaled)  # ensure positive