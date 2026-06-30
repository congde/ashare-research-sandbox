"""Apply mined risk factors to teaching position-scale previews."""

from __future__ import annotations

from typing import Any

from factor_mining.expressions import eval_series
from factor_mining.features import build_feature_matrix
from factor_mining.ml import _combine_linear, _normalize_features
from factor_mining.serialize import expr_from_dict
from factor_mining.stats import zscore_series


def risk_factor_series(
    *,
    risk_spec: dict[str, Any],
    candles: list[dict[str, Any]],
    horizon: int = 1,
) -> list[float | None]:
    features, _, _ = build_feature_matrix(candles, horizon=horizon, target="return")
    source = str(risk_spec.get("factor_source") or "gp")
    if source == "ml":
        normalized = _normalize_features(features)
        weights = dict(risk_spec.get("weights") or {})
        return _combine_linear(normalized, weights)
    expr_payload = risk_spec.get("expr")
    if not expr_payload:
        return [None] * len(candles)
    return eval_series(expr_from_dict(expr_payload), features)


def preview_position_scales(
    *,
    risk_spec: dict[str, Any],
    candles: list[dict[str, Any]],
    horizon: int = 1,
    base_size: float = 1.0,
    tail: int = 8,
) -> dict[str, Any]:
    """Map predicted risk z-score to inverse position scale (teaching demo only)."""
    raw = risk_factor_series(risk_spec=risk_spec, candles=candles, horizon=horizon)
    zscores = zscore_series(
        raw,
        min_samples=3,
        require_finite=True,
        on_insufficient="none",
        on_zero_std="unit",
    )
    rows: list[dict[str, Any]] = []
    for idx, z in enumerate(zscores):
        if z is None:
            continue
        scale = round(base_size / (1.0 + max(0.0, z)), 4)
        rows.append({"idx": idx, "risk_z": round(z, 4), "position_scale": scale})
    sample = rows[-tail:] if rows else []
    scales = [row["position_scale"] for row in rows]
    mean_scale = round(sum(scales) / len(scales), 4) if scales else 0.0
    return {
        "method": "inverse_risk_z_scale",
        "base_size": base_size,
        "sample_tail": sample,
        "mean_position_scale": mean_scale,
        "note": "Teaching demo: higher predicted risk -> lower scale; not live sizing advice.",
    }
