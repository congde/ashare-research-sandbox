"""Normalize backtest metrics across legacy and rolling engines."""

from __future__ import annotations

from typing import Any


CORE_KEYS = (
    "total_return_pct",
    "max_drawdown_pct",
    "sharpe_ratio",
    "total_trades",
    "win_rate",
)


def from_legacy_report(report: dict[str, Any]) -> dict[str, Any]:
    """Map strategy_engine runner output to rolling-style core metrics."""
    metrics = report.get("metrics") or {}
    return {
        "engine": report.get("engine", "strategy_engine"),
        "total_return_pct": metrics.get("strategy_return_pct", 0.0),
        "max_drawdown_pct": abs(metrics.get("maximum_drawdown_pct", 0.0)),
        "sharpe_ratio": metrics.get("sharpe_ratio", 0.0),
        "total_trades": metrics.get("trade_count", 0),
        "win_rate": metrics.get("win_rate", 0.0),
    }


def from_rolling_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Extract core metrics from execute_backtest payload."""
    return {
        "engine": payload.get("engine", "rolling"),
        "total_return_pct": payload.get("total_return_pct", 0.0),
        "max_drawdown_pct": payload.get("max_drawdown_pct", 0.0),
        "sharpe_ratio": payload.get("sharpe_ratio", 0.0),
        "total_trades": payload.get("total_trades", 0),
        "win_rate": payload.get("win_rate", 0.0),
    }


def compare_engines(
    legacy: dict[str, Any],
    rolling: dict[str, Any],
) -> dict[str, Any]:
    """Side-by-side core metrics for chapter 34 / engine unification."""
    left = from_legacy_report(legacy)
    right = from_rolling_payload(rolling)
    deltas = {
        key: round(float(right.get(key, 0.0)) - float(left.get(key, 0.0)), 4)
        for key in CORE_KEYS
    }
    return {"legacy": left, "rolling": right, "delta_rolling_minus_legacy": deltas}
