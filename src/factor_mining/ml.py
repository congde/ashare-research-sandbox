"""ML-style factor mining — univariate screen + greedy linear combo."""

from __future__ import annotations

from typing import Any

from factor_mining.evaluate import FactorMetrics, evaluate_factor, spearman
from factor_mining.stats import zscore_series


def _metrics_dict(metrics: FactorMetrics | None) -> dict[str, Any]:
    if metrics is None:
        return {"ic_mean": 0.0, "ic_std": 0.0, "ir": 0.0, "hit_rate": 0.0, "sample_count": 0}
    return {
        "ic_mean": metrics.ic_mean,
        "ic_std": metrics.ic_std,
        "ir": metrics.ir,
        "hit_rate": metrics.hit_rate,
        "sample_count": metrics.sample_count,
    }


def _combine_linear(
    features: dict[str, list[float | None]],
    weights: dict[str, float],
) -> list[float | None]:
    if not weights:
        return [None] * max(len(v) for v in features.values())
    n = max(len(features[name]) for name in weights)
    out: list[float | None] = [None] * n
    for i in range(n):
        total = 0.0
        used = False
        for name, weight in weights.items():
            row = features.get(name)
            if row is None or i >= len(row) or row[i] is None:
                continue
            total += weight * float(row[i])
            used = True
        out[i] = total if used else None
    return out


def _normalize_features(features: dict[str, list[float | None]]) -> dict[str, list[float | None]]:
    return {name: zscore_series(series) for name, series in features.items()}


def run_ml_search(
    features: dict[str, list[float | None]],
    labels: list[float | None],
    feature_names: list[str],
    *,
    max_features: int = 4,
    min_samples: int = 20,
) -> dict[str, Any]:
    normalized = _normalize_features(features)

    univariate: list[dict[str, Any]] = []
    for name in feature_names:
        metrics = evaluate_factor(normalized[name], labels, min_samples=min_samples)
        if metrics is None:
            continue
        univariate.append(
            {
                "feature": name,
                "ic_mean": metrics.ic_mean,
                "ir": metrics.ir,
                "hit_rate": metrics.hit_rate,
                "abs_ic": abs(metrics.ic_mean),
            }
        )
    univariate.sort(key=lambda item: item["abs_ic"], reverse=True)

    selected: list[str] = []
    weights: dict[str, float] = {}
    best_ic = 0.0

    for candidate in [row["feature"] for row in univariate]:
        if len(selected) >= max_features:
            break
        trial_names = selected + [candidate]
        trial_weights = _fit_ols_weights(normalized, labels, trial_names, min_samples=min_samples)
        if not trial_weights:
            continue
        combo = _combine_linear(normalized, trial_weights)
        metrics = evaluate_factor(combo, labels, min_samples=min_samples)
        if metrics is None:
            continue
        if abs(metrics.ic_mean) >= abs(best_ic):
            selected = trial_names
            weights = trial_weights
            best_ic = metrics.ic_mean

    combo_signal = _combine_linear(normalized, weights)
    combo_metrics = evaluate_factor(combo_signal, labels, min_samples=min_samples)

    return {
        "method": "ml",
        "selected_features": selected,
        "weights": {k: round(v, 6) for k, v in weights.items()},
        "formula": _formula_string(weights),
        "univariate_screen": univariate[:8],
        "metrics": _metrics_dict(combo_metrics),
    }


def _formula_string(weights: dict[str, float]) -> str:
    if not weights:
        return "0"
    parts = []
    for name, weight in weights.items():
        sign = "+" if weight >= 0 else "-"
        parts.append(f" {sign} {abs(weight):.4f}*{name}")
    return parts[0].lstrip("+ ").strip() if parts else "0"


def _fit_ols_weights(
    features: dict[str, list[float | None]],
    labels: list[float | None],
    names: list[str],
    *,
    min_samples: int,
) -> dict[str, float]:
    rows: list[list[float]] = []
    ys: list[float] = []
    for i in range(max(len(v) for v in features.values())):
        row: list[float] = []
        ok = True
        for name in names:
            value = features[name][i] if i < len(features[name]) else None
            if value is None:
                ok = False
                break
            row.append(float(value))
        label = labels[i] if i < len(labels) else None
        if not ok or label is None:
            continue
        rows.append(row)
        ys.append(float(label))

    if len(rows) < min_samples or not names:
        return {names[0]: 1.0} if len(names) == 1 else {}

    k = len(names)
    xtx = [[0.0] * k for _ in range(k)]
    xty = [0.0] * k
    for row, y in zip(rows, ys):
        for i in range(k):
            xty[i] += row[i] * y
            for j in range(k):
                xtx[i][j] += row[i] * row[j]

    ridge = 1e-4
    for i in range(k):
        xtx[i][i] += ridge

    solved = _solve_linear(xtx, xty)
    if solved is None:
        fallback = names[0]
        return {fallback: 1.0 if spearman([r[0] for r in rows], ys) >= 0 else -1.0}
    return {name: solved[idx] for idx, name in enumerate(names)}


def _solve_linear(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    n = len(vector)
    aug = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-12:
            return None
        aug[col], aug[pivot] = aug[pivot], aug[col]
        div = aug[col][col]
        for j in range(col, n + 1):
            aug[col][j] /= div
        for row in range(n):
            if row == col:
                continue
            factor = aug[row][col]
            if factor == 0:
                continue
            for j in range(col, n + 1):
                aug[row][j] -= factor * aug[col][j]
    return [aug[i][n] for i in range(n)]
