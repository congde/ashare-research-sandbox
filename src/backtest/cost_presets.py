"""Execution-cost presets for rolling backtests."""

from __future__ import annotations

from typing import Any

PRESETS: dict[str, dict[str, Any]] = {
    "teaching": {
        "label": "教学（零滑点）",
        "slippage_pct": 0.0,
        "dynamic_slippage": False,
        "dynamic_slippage_factor": 0.5,
        "funding_rate_pct": 0.0,
        "commission_pct": 0.1,
    },
    "realistic": {
        "label": "现实（5bps + 动态滑点）",
        "slippage_pct": 0.05,
        "dynamic_slippage": True,
        "dynamic_slippage_factor": 0.5,
        "funding_rate_pct": 0.0,
        "commission_pct": 0.1,
    },
    "perp": {
        "label": "永续（滑点 + 资金费率）",
        "slippage_pct": 0.05,
        "dynamic_slippage": True,
        "dynamic_slippage_factor": 0.5,
        "funding_rate_pct": 0.01,
        "commission_pct": 0.1,
    },
}


def resolve_cost_options(
    *,
    preset: str | None = None,
    slippage_bps: float | None = None,
    dynamic_slippage: bool | None = None,
    funding_rate_pct: float | None = None,
    commission_pct: float | None = None,
) -> dict[str, Any]:
    """Merge preset defaults with explicit overrides."""
    key = (preset or "teaching").strip().lower()
    base = dict(PRESETS.get(key, PRESETS["teaching"]))
    base["preset"] = key if key in PRESETS else "teaching"

    if slippage_bps is not None:
        base["slippage_pct"] = max(0.0, min(200.0, slippage_bps)) / 100.0
    if dynamic_slippage is not None:
        base["dynamic_slippage"] = bool(dynamic_slippage)
    if funding_rate_pct is not None:
        base["funding_rate_pct"] = max(-1.0, min(1.0, funding_rate_pct))
    if commission_pct is not None:
        base["commission_pct"] = max(0.0, min(2.0, commission_pct))

    return base


def infer_funding_rate_pct(meta: dict[str, Any] | None) -> float | None:
    """Read average funding from dashboard fixture metadata when present."""
    if not meta:
        return None
    for key in ("avgFundingRatePct", "funding_rate_pct", "fundingRatePct"):
        raw = meta.get(key)
        if raw is not None:
            try:
                return float(raw)
            except (TypeError, ValueError):
                continue
    return None


def cost_assumptions(cost: dict[str, Any]) -> list[str]:
    preset = cost.get("preset", "teaching")
    label = PRESETS.get(preset, PRESETS["teaching"]).get("label", preset)
    lines = [
        f"Cost preset: {label} ({preset}).",
        f"Commission {cost.get('commission_pct', 0.1):.2f}% per side.",
    ]
    slip = float(cost.get("slippage_pct", 0.0))
    if slip > 0 or cost.get("dynamic_slippage"):
        dyn = "on" if cost.get("dynamic_slippage") else "off"
        lines.append(f"Slippage base {slip:.3f}% · dynamic {dyn}.")
    else:
        lines.append("Slippage disabled.")
    funding = float(cost.get("funding_rate_pct", 0.0))
    if funding != 0.0:
        lines.append(f"Funding rate {funding:.4f}% per 8h (longs pay when positive).")
    return lines
