"""Curated formula-alpha candidates for the factor mining sandbox."""

from __future__ import annotations

from typing import Any

from factor_mining.evaluate import evaluate_factor
from factor_mining.expressions import Expr, eval_series, stringify
from factor_mining.serialize import expr_to_dict


def _t(name: str) -> Expr:
    return Expr(op="terminal", terminal=name)


def _u(op: str, child: Expr) -> Expr:
    return Expr(op=op, left=child)


def _b(op: str, left: Expr, right: Expr) -> Expr:
    return Expr(op=op, left=left, right=right)


def template_expressions() -> list[tuple[str, Expr, str]]:
    """Small WorldQuant-style formula set using only lag-safe local features."""
    return [
        (
            "momentum_volume_confirmation",
            _b("mul", _u("rank", _t("ret_10")), _u("rank", _t("volume_z20"))),
            "Momentum confirmed by unusual volume.",
        ),
        (
            "short_reversal_liquidity",
            _b("mul", _u("rank", _t("ret_5_reversal")), _u("rank", _t("volume_z20"))),
            "Short-term reversal weighted by liquidity shock.",
        ),
        (
            "trend_quality_breakout",
            _b("add", _u("rank", _t("sma20_sma60_spread")), _u("rank", _t("range_pos"))),
            "Trend filter plus close location inside the candle range.",
        ),
        (
            "volatility_compression",
            _b("sub", _u("rank", _t("bb_centered")), _u("rank", _t("atr_z20"))),
            "Price strength after lower recent volatility.",
        ),
        (
            "macd_reversal_blend",
            _b("sub", _u("rank", _t("macd_hist")), _u("rank", _t("ret_20"))),
            "MACD impulse adjusted for crowded medium-term momentum.",
        ),
        (
            "adx_di_trend",
            _b("mul", _u("rank", _t("plus_minus_di")), _u("rank", _t("adx_norm"))),
            "Directional movement confirmed by ADX trend strength.",
        ),
        (
            "support_bounce",
            _b("add", _u("rank", _t("distance_low_20")), _u("rank", _t("lower_shadow_reversal"))),
            "Price holding above recent lows with lower-shadow rejection.",
        ),
        (
            "resistance_fade",
            _b("sub", _u("rank", _t("upper_shadow_reversal")), _u("rank", _t("distance_high_20"))),
            "Upper-shadow rejection near recent highs.",
        ),
        (
            "liquidity_breakout",
            _b("mul", _u("rank", _t("momentum_dollar_volume")), _u("rank", _t("close_to_high"))),
            "Dollar-volume breakout closing near the bar high.",
        ),
        (
            "volatility_risk_premium",
            _b("sub", _u("rank", _t("ret_vol_20")), _u("rank", _t("bb_width_z20"))),
            "Realized volatility pressure adjusted by Bollinger width expansion.",
        ),
        (
            "trend_efficiency",
            _b("add", _u("rank", _t("efficiency_20")), _u("rank", _t("trend_strength"))),
            "Directional efficiency and EMA/ADX trend confirmation.",
        ),
        (
            "overnight_gap_reversal",
            _b("sub", _u("rank", _t("intrabar_return")), _u("rank", _t("overnight_gap"))),
            "Intrabar follow-through after an overnight gap.",
        ),
        (
            "range_volume_pressure",
            _b("mul", _u("rank", _t("range_z20")), _u("rank", _t("volume_z20"))),
            "Wide range with volume pressure.",
        ),
    ]


def run_template_search(
    features: dict[str, list[float | None]],
    train_labels: list[float | None],
    test_features: dict[str, list[float | None]],
    test_labels: list[float | None],
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for name, expr, rationale in template_expressions():
        train_signal = eval_series(expr, features)
        train_metrics = evaluate_factor(train_signal, train_labels, min_samples=15)
        if train_metrics is None:
            continue
        test_signal = eval_series(expr, test_features)
        test_metrics = evaluate_factor(test_signal, test_labels, min_samples=10)
        candidates.append(
            {
                "name": name,
                "method": "template",
                "expression": stringify(expr),
                "expr": expr,
                "rationale": rationale,
                "train": train_metrics,
                "test": test_metrics,
            }
        )

    if not candidates:
        return {
            "method": "template",
            "expression": "0",
            "rationale": "No template candidate had enough samples.",
            "metrics": _empty_metrics(),
            "test": _empty_metrics(),
            "candidates": [],
        }

    candidates.sort(key=lambda row: abs(row["test"].ic_mean if row["test"] else 0.0), reverse=True)
    best = candidates[0]
    return {
        "method": "template",
        "expression": best["expression"],
        "expr": best["expr"],
        "rationale": best["rationale"],
        "metrics": _metrics_dict(best["train"]),
        "test": _metrics_dict(best["test"]),
        "candidates": [
            {
                "name": row["name"],
                "expression": row["expression"],
                "rationale": row["rationale"],
                "train_ic": row["train"].ic_mean if row["train"] else 0.0,
                "test_ic": row["test"].ic_mean if row["test"] else 0.0,
            }
            for row in candidates[:6]
        ],
        "factor_spec": {
            "factor_source": "template",
            "label": best["expression"],
            "expr": expr_to_dict(best["expr"]),
        },
    }


def _metrics_dict(metrics: Any) -> dict[str, Any]:
    if metrics is None:
        return _empty_metrics()
    return {
        "ic_mean": metrics.ic_mean,
        "ic_std": metrics.ic_std,
        "ir": metrics.ir,
        "hit_rate": metrics.hit_rate,
        "sample_count": metrics.sample_count,
        "quintile_spread": metrics.quintile_spread,
        "turnover_rate": metrics.turnover_rate,
        "top_quintile_return": metrics.top_quintile_return,
        "bottom_quintile_return": metrics.bottom_quintile_return,
        "t_stat": metrics.t_stat,
        "p_value": metrics.p_value,
        "rank_autocorr": metrics.rank_autocorr,
        "quantile_returns": list(metrics.quantile_returns),
    }


def _empty_metrics() -> dict[str, Any]:
    return {
        "ic_mean": 0.0,
        "ic_std": 0.0,
        "ir": 0.0,
        "hit_rate": 0.0,
        "sample_count": 0,
        "quintile_spread": 0.0,
        "turnover_rate": 0.0,
        "top_quintile_return": 0.0,
        "bottom_quintile_return": 0.0,
        "t_stat": 0.0,
        "p_value": 1.0,
        "rank_autocorr": 0.0,
        "quantile_returns": [0.0, 0.0, 0.0, 0.0, 0.0],
    }
