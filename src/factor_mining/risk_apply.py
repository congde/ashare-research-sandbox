"""Apply mined risk factors to teaching position-scale previews."""

from __future__ import annotations

import math
from typing import Any

from factor_mining.expressions import eval_series
from factor_mining.features import build_feature_matrix
from factor_mining.ml import _combine_linear, _normalize_features
from factor_mining.serialize import expr_from_dict


def _zscore_series(values: list[float | None]) -> list[float | None]:
    paired = [float(v) for v in values if v is not None and math.isfinite(v)]
    if len(paired) < 3:
        return [None] * len(values)
    mean = sum(paired) / len(paired)
    var = sum((v - mean) ** 2 for v in paired) / (len(paired) - 1)
    std = math.sqrt(var) if var > 1e-12 else 1.0
    out: list[float | None] = []
    for value in values:
        if value is None or not math.isfinite(value):
            out.append(None)
            continue
        out.append((float(value) - mean) / std)
    return out


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
    zscores = _zscore_series(raw)
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
