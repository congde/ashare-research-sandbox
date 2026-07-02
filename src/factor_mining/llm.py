"""LLM-assisted factor proposal generation with deterministic fallback."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from dashboard.http_client import http_post
from dashboard.llm_signal import llm_configured, resolve_model
from factor_mining.evaluate import evaluate_factor
from factor_mining.ml import _combine_linear, _normalize_features


def run_llm_factor_search(
    features: dict[str, list[float | None]],
    train_labels: list[float | None],
    test_features: dict[str, list[float | None]],
    test_labels: list[float | None],
    feature_names: list[str],
    *,
    target: str,
    horizon: int,
    symbol: str,
    model: str | None = None,
) -> dict[str, Any]:
    normalized_train = _normalize_features(features)
    normalized_test = _normalize_features(test_features)
    proposals = _fallback_proposals(target)
    source = "fallback_templates"
    error: str | None = None

    if llm_configured():
        try:
            proposals = _call_llm_for_proposals(
                feature_names=feature_names,
                target=target,
                horizon=horizon,
                symbol=symbol,
                model=resolve_model(model),
            )
            source = "llm"
        except Exception as exc:  # pragma: no cover - network/provider dependent
            error = str(exc)

    scored: list[dict[str, Any]] = []
    for proposal in proposals:
        weights = _sanitize_weights(proposal.get("weights"), feature_names)
        if not weights:
            continue
        train_signal = _combine_linear(normalized_train, weights)
        train_metrics = evaluate_factor(train_signal, train_labels, min_samples=15)
        test_signal = _combine_linear(normalized_test, weights)
        test_metrics = evaluate_factor(test_signal, test_labels, min_samples=10)
        if train_metrics is None and test_metrics is None:
            continue
        scored.append(
            {
                "name": str(proposal.get("name") or "llm_factor"),
                "rationale": str(proposal.get("rationale") or ""),
                "weights": weights,
                "train": _metrics_dict(train_metrics),
                "test": _metrics_dict(test_metrics),
            }
        )

    if not scored:
        scored = [
            {
                "name": "empty_llm_fallback",
                "rationale": "No valid proposal had enough samples.",
                "weights": {},
                "train": _empty_metrics(),
                "test": _empty_metrics(),
            }
        ]

    scored.sort(key=lambda row: abs(row["test"].get("ic_mean", 0.0)), reverse=True)
    best = scored[0]
    return {
        "method": "llm",
        "proposal_source": source,
        "model": resolve_model(model) if llm_configured() else None,
        "formula": _formula_string(best["weights"]),
        "rationale": best["rationale"],
        "weights": best["weights"],
        "metrics": best["train"],
        "test": best["test"],
        "proposals": [
            {
                "name": row["name"],
                "rationale": row["rationale"],
                "weights": row["weights"],
                "train_ic": row["train"].get("ic_mean", 0.0),
                "test_ic": row["test"].get("ic_mean", 0.0),
            }
            for row in scored[:6]
        ],
        "llm_error": error,
    }


def _call_llm_for_proposals(
    *,
    feature_names: list[str],
    target: str,
    horizon: int,
    symbol: str,
    model: str,
) -> list[dict[str, Any]]:
    prompt = (
        "You are designing quantitative alpha factor candidates. "
        "Return only JSON with a candidates array. Each candidate must have "
        "name, rationale, and weights. Weights is an object using only the "
        "provided feature names, with numeric values between -3 and 3. "
        "Do not invent fields and do not include markdown.\n\n"
        f"symbol={symbol}\n"
        f"target={target}\n"
        f"horizon_bars={horizon}\n"
        f"features={json.dumps(feature_names, ensure_ascii=False)}"
    )
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": "Return valid JSON only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.35,
            "response_format": {"type": "json_object"},
        },
        ensure_ascii=False,
    )
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    base = os.environ.get("OPENAI_API_BASE", "https://api.deepseek.com").strip().rstrip("/")
    url = f"{base}/chat/completions" if base.endswith("/v1") else f"{base}/v1/chat/completions"
    payload = http_post(
        url,
        body,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=float(os.environ.get("OPENAI_API_TIMEOUT", "90")),
    )
    content = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or "{}"
    parsed = _extract_json(content)
    candidates = parsed.get("candidates") if isinstance(parsed, dict) else None
    return candidates if isinstance(candidates, list) else []


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    payload = json.loads(cleaned)
    return payload if isinstance(payload, dict) else {}


def _fallback_proposals(target: str) -> list[dict[str, Any]]:
    if target == "risk":
        return [
            {
                "name": "llm_volatility_pressure",
                "rationale": "Volume and ATR shocks often precede higher realized volatility.",
                "weights": {"atr_z20": 1.2, "volume_z20": 0.8, "intraday_range": 0.6},
            },
            {
                "name": "llm_crowded_trend_risk",
                "rationale": "Extended trend and high range position can signal crowding risk.",
                "weights": {"ret_20": 0.7, "range_pos": 0.6, "vol_breakout": 1.0},
            },
            {
                "name": "llm_liquidity_gap_risk",
                "rationale": "Large gaps with dollar-volume pressure can indicate unstable liquidity.",
                "weights": {"overnight_gap": 0.8, "dollar_volume_z20": 0.6, "vol_of_vol": 1.0},
            },
            {
                "name": "llm_shadow_reversal_risk",
                "rationale": "Long shadows and high range expansion often occur around liquidation events.",
                "weights": {"upper_shadow": 0.6, "lower_shadow": 0.6, "range_volume_pressure": 1.1},
            },
        ]
    return [
        {
            "name": "llm_momentum_quality",
            "rationale": "Prefer medium-term momentum confirmed by volume and trend quality.",
            "weights": {"ret_10": 0.9, "momentum_volume": 0.8, "trend_quality": 0.5},
        },
        {
            "name": "llm_reversal_after_stretch",
            "rationale": "Fade short-term stretched moves when volume shock suggests exhaustion.",
            "weights": {"ret_5_reversal": 1.0, "reversal_volume": 0.7, "rsi_centered": -0.4},
        },
        {
            "name": "llm_trend_efficiency",
            "rationale": "Favor efficient trends with ADX/DI confirmation rather than noisy drift.",
            "weights": {"efficiency_20": 0.8, "trend_strength": 0.9, "di_trend_quality": 0.5},
        },
        {
            "name": "llm_support_bounce",
            "rationale": "Lower-shadow rejection near support may signal mean reversion.",
            "weights": {"distance_low_20": 0.5, "lower_shadow_reversal": 1.0, "ret_3": -0.3},
        },
        {
            "name": "llm_liquidity_breakout",
            "rationale": "Breakouts are more credible when dollar volume confirms the move.",
            "weights": {"momentum_dollar_volume": 1.0, "close_to_high": 0.5, "volume_trend_5_20": 0.4},
        },
    ]


def _sanitize_weights(raw: Any, feature_names: list[str]) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    allowed = set(feature_names)
    weights: dict[str, float] = {}
    for name, value in raw.items():
        if name not in allowed:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if not -3.0 <= numeric <= 3.0:
            numeric = max(-3.0, min(3.0, numeric))
        if abs(numeric) >= 1e-9:
            weights[str(name)] = round(numeric, 6)
    return dict(list(weights.items())[:6])


def _formula_string(weights: dict[str, float]) -> str:
    if not weights:
        return "0"
    parts = []
    for name, weight in weights.items():
        sign = "+" if weight >= 0 else "-"
        parts.append(f" {sign} {abs(weight):.4f}*{name}")
    return parts[0].lstrip("+ ").strip()


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
