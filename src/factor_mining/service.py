"""Orchestrate GP / ML factor mining on teaching candle data."""

from __future__ import annotations

from typing import Any, Literal

from backtest.rolling.service import load_candles
from factor_mining.evaluate import (
    chronological_split,
    evaluate_factor,
    slice_series,
)
from factor_mining.expressions import eval_series
from factor_mining.features import MiningTarget, RiskKind, build_feature_matrix
from factor_mining.gp import GPConfig, run_gp_search
from factor_mining.ml import run_ml_search
from backtest.trials import get_ledger
from factor_mining.risk_apply import preview_position_scales
from factor_mining.serialize import expr_to_dict


MiningMode = Literal["gp", "ml", "both"]

_LABEL_META: dict[tuple[MiningTarget, RiskKind], dict[str, str]] = {
    ("return", "abs_ret"): {
        "metric_name": "IC",
        "label_description": "forward return",
        "application": "directional_signal",
    },
    ("risk", "abs_ret"): {
        "metric_name": "RIC",
        "label_description": "forward absolute return (vol proxy)",
        "application": "position_scale",
    },
    ("risk", "realized_vol"): {
        "metric_name": "RIC",
        "label_description": "forward realized volatility",
        "application": "position_scale",
    },
}


def run_factor_mining(
    *,
    mode: MiningMode = "both",
    target: MiningTarget = "return",
    risk_kind: RiskKind = "abs_ret",
    symbol: str | None = None,
    limit: int = 120,
    horizon: int = 1,
    refresh: bool = False,
    gp_generations: int = 12,
    gp_population: int = 24,
    seed: int = 42,
) -> dict[str, Any]:
    pair, kline_type, candles, data_meta = load_candles(
        symbol=symbol,
        limit=max(60, min(1500, limit)),
        refresh=refresh,
    )
    if len(candles) < 30:
        raise ValueError(f"K线数据不足: 需要至少 30 根, 当前 {len(candles)}")

    rk = risk_kind if target == "risk" else "abs_ret"
    features, labels, feature_names = build_feature_matrix(
        candles,
        horizon=max(1, min(10, horizon)),
        target=target,
        risk_kind=rk,
    )
    meta = _LABEL_META[(target, rk if target == "risk" else "abs_ret")]
    n = len(labels)
    train_slice, test_slice = chronological_split(n, train_ratio=0.7)

    train_features = {name: slice_series(series, train_slice) for name, series in features.items()}
    test_features = {name: slice_series(series, test_slice) for name, series in features.items()}
    train_labels = slice_series(labels, train_slice)
    test_labels = slice_series(labels, test_slice)

    baseline = _baseline_screen(features, labels, feature_names)

    engine = "factor-mining/teaching-sandbox"
    if target == "risk":
        engine = "factor-mining/risk-teaching-sandbox"

    payload: dict[str, Any] = {
        "ok": True,
        "engine": engine,
        "mining_target": target,
        "mode": mode,
        "symbol": pair,
        "kline_type": kline_type,
        "horizon_bars": horizon,
        "sample_bars": n,
        "train_bars": len(train_labels),
        "test_bars": len(test_labels),
        "feature_count": len(feature_names),
        "features": feature_names,
        "baseline_univariate": baseline[:6],
        "metric_name": meta["metric_name"],
        "label_description": meta["label_description"],
        "application": meta["application"],
        **data_meta,
    }
    if target == "risk":
        payload["risk_kind"] = rk

    gp_result: dict[str, Any] | None = None
    ml_result: dict[str, Any] | None = None

    if mode in ("gp", "both"):
        raw_gp = run_gp_search(
            train_features,
            train_labels,
            feature_names,
            config=GPConfig(
                population_size=max(8, min(40, gp_population)),
                generations=max(4, min(30, gp_generations)),
                seed=seed,
            ),
        )
        gp_expr = raw_gp.pop("expr")
        gp_result = _public_gp(raw_gp)
        gp_result["train"] = raw_gp.pop("metrics")
        gp_result["test"] = _evaluate_gp_expr(gp_expr, test_features, test_labels)
        gp_result["overfit_gap"] = _overfit_gap(gp_result["train"], gp_result["test"])
        gp_result["factor_spec"] = _build_factor_spec(
            target=target,
            source="gp",
            label=gp_result["expression"],
            horizon=horizon,
            expr=expr_to_dict(gp_expr),
        )
        if target == "return":
            gp_result["backtest_spec"] = gp_result["factor_spec"]
        else:
            gp_result["risk_spec"] = gp_result["factor_spec"]
        payload["gp"] = gp_result

    if mode in ("ml", "both"):
        raw_ml = run_ml_search(train_features, train_labels, feature_names)
        ml_result = dict(raw_ml)
        ml_result["train"] = ml_result.pop("metrics")
        ml_result["test"] = _evaluate_ml_on_split(ml_result, test_features, test_labels)
        ml_result["overfit_gap"] = _overfit_gap(ml_result["train"], ml_result["test"])
        ml_result["factor_spec"] = _build_factor_spec(
            target=target,
            source="ml",
            label=ml_result.get("formula") or "ml_factor",
            horizon=horizon,
            weights=ml_result.get("weights") or {},
        )
        if target == "return":
            ml_result["backtest_spec"] = ml_result["factor_spec"]
        else:
            ml_result["risk_spec"] = ml_result["factor_spec"]
        payload["ml"] = ml_result

    payload["leader"] = _pick_leader(gp_result, ml_result)
    if payload["leader"]:
        source = gp_result if payload["leader"]["method"] == "gp" else ml_result
        if source:
            spec = source.get("factor_spec")
            if target == "return":
                payload["leader"]["backtest_spec"] = spec
            else:
                payload["leader"]["risk_spec"] = spec
            test_metrics = source.get("test") or {}
            payload["leader"]["validation"] = {
                "quintile_spread": test_metrics.get("quintile_spread", 0.0),
                "turnover_rate": test_metrics.get("turnover_rate", 0.0),
                "ic_decay": round(
                    abs((source.get("train") or {}).get("ic_mean", 0.0))
                    - abs(test_metrics.get("ic_mean", 0.0)),
                    6,
                ),
            }
    payload["warnings"] = _warnings(mode, target, gp_result, ml_result)
    payload["what_it_proves"] = _what_it_proves(target, meta["metric_name"])
    if target == "risk" and payload["leader"] and payload["leader"].get("risk_spec"):
        payload["risk_application"] = preview_position_scales(
            risk_spec=payload["leader"]["risk_spec"],
            candles=candles,
            horizon=horizon,
        )

    ledger = get_ledger()
    for label, result in (("gp", gp_result), ("ml", ml_result)):
        if not result:
            continue
        train_ic = float((result.get("train") or {}).get("ic_mean", 0.0))
        test_ic = float((result.get("test") or {}).get("ic_mean", 0.0))
        ledger.record(
            source=f"factor_mining_{label}",
            strategy_key="mined_factor",
            sharpe_ratio=test_ic,
            total_return_pct=train_ic * 100,
            params={"mode": mode, "target": target, "horizon": horizon},
            total_trades=int((result.get("train") or {}).get("sample_count", 0)),
        )
    payload["trial_summary"] = ledger.summary(strategy_key="mined_factor")
    return payload


def run_risk_factor_mining(
    *,
    mode: MiningMode = "both",
    risk_kind: RiskKind = "abs_ret",
    **kwargs: Any,
) -> dict[str, Any]:
    """Convenience wrapper for risk-target GP / ML mining."""
    return run_factor_mining(mode=mode, target="risk", risk_kind=risk_kind, **kwargs)


def _build_factor_spec(
    *,
    target: MiningTarget,
    source: str,
    label: str,
    horizon: int,
    expr: dict[str, Any] | None = None,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "factor_source": source,
        "label": label,
        "horizon": horizon,
        "mining_target": target,
    }
    if target == "risk":
        spec["application"] = "position_scale"
    if source == "ml":
        spec["weights"] = dict(weights or {})
    elif expr is not None:
        spec["expr"] = expr
    return spec


def _public_gp(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        key: raw[key]
        for key in ("method", "expression", "fitness", "complexity", "history")
        if key in raw
    }


def _baseline_screen(
    features: dict[str, list[float | None]],
    labels: list[float | None],
    feature_names: list[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in feature_names:
        metrics = evaluate_factor(features[name], labels, min_samples=20)
        if metrics is None:
            continue
        rows.append(
            {
                "feature": name,
                "ic_mean": metrics.ic_mean,
                "ir": metrics.ir,
                "hit_rate": metrics.hit_rate,
                "sample_count": metrics.sample_count,
            }
        )
    rows.sort(key=lambda item: abs(item["ic_mean"]), reverse=True)
    return rows


def _metrics_payload(metrics: Any) -> dict[str, Any]:
    if metrics is None:
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
        }
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
    }


def _evaluate_gp_expr(expr: Any, features: dict[str, list[float | None]], labels: list[float | None]) -> dict[str, Any]:
    signal = eval_series(expr, features)
    return _metrics_payload(evaluate_factor(signal, labels, min_samples=10))


def _evaluate_ml_on_split(
    ml_result: dict[str, Any],
    features: dict[str, list[float | None]],
    labels: list[float | None],
) -> dict[str, Any]:
    from factor_mining.ml import _combine_linear, _normalize_features

    normalized = _normalize_features(features)
    weights = ml_result.get("weights") or {}
    signal = _combine_linear(normalized, weights)
    return _metrics_payload(evaluate_factor(signal, labels, min_samples=10))


def _overfit_gap(train: dict[str, Any], test: dict[str, Any]) -> float:
    return round(abs(train.get("ic_mean", 0.0)) - abs(test.get("ic_mean", 0.0)), 6)


def _pick_leader(
    gp_result: dict[str, Any] | None,
    ml_result: dict[str, Any] | None,
) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    if gp_result:
        candidates.append(
            {
                "method": "gp",
                "label": gp_result.get("expression"),
                "train_ic": gp_result.get("train", {}).get("ic_mean", 0.0),
                "test_ic": gp_result.get("test", {}).get("ic_mean", 0.0),
            }
        )
    if ml_result:
        candidates.append(
            {
                "method": "ml",
                "label": ml_result.get("formula"),
                "train_ic": ml_result.get("train", {}).get("ic_mean", 0.0),
                "test_ic": ml_result.get("test", {}).get("ic_mean", 0.0),
            }
        )
    if not candidates:
        return None
    return max(candidates, key=lambda item: abs(item["test_ic"]))


def _what_it_proves(target: MiningTarget, metric_name: str) -> list[str]:
    if target == "risk":
        return [
            "GP / ML 搜索能预测未来波动代理（绝对收益或实现波动），RIC 为 Spearman 秩相关。",
            "风险因子用于仓位缩放或加宽止损，不直接给出多空方向。",
            "训练 / 测试按时间切分；RIC 高不代表样本外一定有效。",
        ]
    return [
        "GP 在算子空间里搜索符号表达式，ML 在特征子集上做贪婪线性组合。",
        f"{metric_name} / IR 用 Spearman 秩相关衡量因子对未来收益的排序能力。",
        "训练 / 测试按时间切分，用于演示样本内挖掘与过拟合风险。",
    ]


def _warnings(
    mode: MiningMode,
    target: MiningTarget,
    gp_result: dict[str, Any] | None,
    ml_result: dict[str, Any] | None,
) -> list[str]:
    metric = "RIC" if target == "risk" else "IC"
    warnings = [
        "教学沙箱：单标的时序相关，不是截面多股票因子检验。",
        f"高训练 {metric} + 低测试 {metric} 通常意味着过拟合，不应直接上线。",
    ]
    if target == "risk":
        warnings.append("风险因子挖掘不替代第 22 讲运行时风控否决；仅演示仓位缩放思路。")
        warnings.append("Barra 式截面风险模型未实现；本沙箱为单标的时序波动预测。")
    for label, result in (("GP", gp_result), ("ML", ml_result)):
        if result is None:
            continue
        gap = result.get("overfit_gap", 0.0)
        if gap > 0.15:
            warnings.append(f"{label} 训练/测试 {metric} 差距 {gap:.3f}，疑似过拟合。")
    if mode == "both" and gp_result and ml_result:
        gp_test = abs(gp_result.get("test", {}).get("ic_mean", 0.0))
        ml_test = abs(ml_result.get("test", {}).get("ic_mean", 0.0))
        winner = "GP" if gp_test >= ml_test else "ML"
        warnings.append(f"测试集上 {winner} 表现更好，但仍需滚动窗口复核。")
    return warnings


def run_mined_factor_backtest(
    *,
    backtest_spec: dict[str, Any],
    symbol: str | None = None,
    limit: int = 120,
    stop_loss_pct: float = 3.0,
    take_profit_pct: float = 5.0,
    trailing_stop_pct: float = 0.0,
    max_hold_bars: int = 0,
    refresh: bool = False,
    entry_threshold: float = 0.5,
) -> dict[str, Any]:
    """Run rolling backtest using a mined GP / ML factor spec."""
    from backtest.rolling.service import execute_backtest

    if str(backtest_spec.get("mining_target") or "return") == "risk":
        raise ValueError("风险因子请使用 risk_spec 做仓位缩放预览，不支持 mined_factor 方向回测")

    source = str(backtest_spec.get("factor_source") or "gp")
    strategy_params: dict[str, Any] = {
        "factor_source": source,
        "label": backtest_spec.get("label") or "挖掘因子",
        "horizon": int(backtest_spec.get("horizon") or 1),
        "entry_threshold": entry_threshold,
    }
    if source == "ml":
        strategy_params["weights"] = dict(backtest_spec.get("weights") or {})
    else:
        strategy_params["expr"] = backtest_spec.get("expr")

    payload = execute_backtest(
        strategy_name="mined_factor",
        symbol=symbol,
        limit=limit,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        trailing_stop_pct=trailing_stop_pct,
        max_hold_bars=max_hold_bars,
        refresh=refresh,
        strategy_params=strategy_params,
    )
    payload["factor_source"] = source
    payload["factor_label"] = strategy_params["label"]
    payload["backtest_spec"] = backtest_spec
    assumptions = list(payload.get("assumptions") or [])
    assumptions.append("信号来自 GP/ML 挖掘因子，阈值触发 LONG/SHORT。")
    payload["assumptions"] = assumptions
    return payload
