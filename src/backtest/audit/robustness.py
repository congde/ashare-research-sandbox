"""Parameter sensitivity and robustness checks."""

from __future__ import annotations

import copy
from typing import Any

from backtest.rolling.engine import run_backtest
from backtest.rolling.metrics import compute_metrics
from backtest.rolling.models import BacktestConfig
from backtest.rolling.strategies.base import Strategy


def _is_numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def run_parameter_sensitivity(
    candles: list[dict[str, Any]],
    strategy: Strategy,
    *,
    config: BacktestConfig,
    perturb_pct: float = 0.2,
    max_return_drift_pct: float = 30.0,
) -> dict[str, Any]:
    baseline_params = dict(strategy.default_params())
    trades, equity, _ = run_backtest(candles, strategy, baseline_params, config)
    baseline_metrics = compute_metrics(
        trades=trades,
        equity_curve=equity,
        candles=candles,
        symbol="",
        kline_type=config.kline_type,
        strategy_name=strategy.display_name,
    )
    baseline_return = baseline_metrics.total_return_pct

    rows: list[dict[str, Any]] = []
    stable = 0
    tested = 0

    for key, value in baseline_params.items():
        if not _is_numeric(value):
            continue
        for direction in (-1, 1):
            perturbed = copy.deepcopy(baseline_params)
            delta = float(value) * perturb_pct * direction
            new_value = float(value) + delta
            if isinstance(value, int):
                new_value = max(1, int(round(new_value)))
            perturbed[key] = new_value

            p_trades, p_equity, _ = run_backtest(candles, strategy, perturbed, config)
            metrics = compute_metrics(
                trades=p_trades,
                equity_curve=p_equity,
                candles=candles,
                symbol="",
                kline_type=config.kline_type,
                strategy_name=strategy.display_name,
            )
            if baseline_return == 0:
                drift = abs(metrics.total_return_pct)
            else:
                drift = abs(metrics.total_return_pct - baseline_return) / abs(baseline_return) * 100
            passed = drift <= max_return_drift_pct
            tested += 1
            if passed:
                stable += 1
            rows.append(
                {
                    "param": key,
                    "direction": "down" if direction < 0 else "up",
                    "value": perturbed[key],
                    "total_return_pct": round(metrics.total_return_pct, 2),
                    "return_drift_pct": round(drift, 2),
                    "stable": passed,
                }
            )

    score = stable / tested if tested else 1.0
    return {
        "baseline_return_pct": round(baseline_return, 2),
        "baseline_sharpe": round(baseline_metrics.sharpe_ratio, 2),
        "stability_score": round(score, 4),
        "stable": score >= 0.6,
        "perturbations": rows,
        "tested": tested,
    }
