"""End-to-end research path for chapter 34."""

from __future__ import annotations

from typing import Any

from backtest.bridge import compare_engines
from backtest.metrics_explain import explain_metrics
from backtest.rolling.service import (
    execute_backtest,
    get_trial_audit,
    run_robustness_audit,
    run_walk_forward,
)
from backtest.runner import load_prices, run_backtest as run_legacy_backtest
from backtest.trace import run_ma_crossover_trace
from data.pit import pit_teaching_summary
from factor_mining.service import run_factor_mining, run_mined_factor_backtest
from paths import DATA_DIR
from research.report import build_report
from risk import evaluate_backtest_risk


def run_research_path(
    *,
    short: int = 3,
    long: int = 7,
    strategy: str = "ma_crossover",
    include_factor_mine: bool = False,
    include_audit: bool = True,
) -> dict[str, Any]:
    """Signal → event-driven backtest → rolling backtest → risk review."""
    report = build_report(short=short, long=long)
    event_trace = run_ma_crossover_trace(short=short, long=long)
    rolling = execute_backtest(strategy_name=strategy, cost_preset="teaching")
    rolling_realistic = execute_backtest(strategy_name=strategy, cost_preset="realistic")
    legacy_bt = run_legacy_backtest(load_prices(DATA_DIR / "prices.csv"), short=short, long=long)
    unified = compare_engines(legacy_bt, rolling)
    metrics_view = explain_metrics()
    risk_findings = evaluate_backtest_risk(report["backtest"])

    path: list[dict[str, Any]] = [
        {"step": 1, "name": "research_report", "engine": report["backtest"]["engine"]},
        {"step": 2, "name": "event_trace", "trades": len(event_trace["trail"])},
        {"step": 3, "name": "rolling_backtest", "engine": rolling["engine"], "strategy": rolling["strategy"]},
        {
            "step": 4,
            "name": "realistic_cost_backtest",
            "total_return_pct": rolling_realistic.get("total_return_pct"),
            "cost_preset": rolling_realistic.get("cost_preset"),
        },
        {"step": 5, "name": "metrics_explain", "highest_return": metrics_view["highest_return"]},
        {"step": 6, "name": "risk_review", "findings": len(risk_findings)},
    ]

    audit_summary: dict[str, Any] | None = None
    if include_audit:
        wfo = run_walk_forward(strategy_name=strategy, num_windows=2, limit=120)
        robustness = run_robustness_audit(strategy_name=strategy, limit=120)
        trials = get_trial_audit(strategy_key=strategy)
        pit = pit_teaching_summary()
        path.extend(
            [
                {
                    "step": 7,
                    "name": "walk_forward_audit",
                    "dsr": wfo.get("dsr"),
                    "overfit_warning": wfo.get("overfit_warning"),
                },
                {
                    "step": 8,
                    "name": "robustness_audit",
                    "pbo": robustness.get("pbo", {}).get("pbo"),
                    "stability_score": robustness.get("parameter_sensitivity", {}).get("stability_score"),
                },
                {"step": 9, "name": "trial_ledger", "num_trials": trials.get("num_trials")},
                {"step": 10, "name": "pit_teaching", "validation_errors": len(pit.get("validation_errors", []))},
            ]
        )
        audit_summary = {
            "dsr": wfo.get("dsr"),
            "num_trials": trials.get("num_trials"),
            "pbo": robustness.get("pbo", {}).get("pbo"),
            "stability_score": robustness.get("parameter_sensitivity", {}).get("stability_score"),
        }

    factor_summary: dict[str, Any] | None = None
    if include_factor_mine:
        mined = run_factor_mining(
            mode="ml",
            symbol="WEB3-DEMO/USDT",
            limit=120,
            gp_generations=4,
            gp_population=8,
            seed=7,
        )
        spec = (mined.get("leader") or {}).get("backtest_spec")
        mined_bt: dict[str, Any] | None = None
        if spec:
            mined_bt = run_mined_factor_backtest(backtest_spec=spec, symbol="WEB3-DEMO/USDT", limit=120)
        path.append(
            {
                "step": 11,
                "name": "factor_mine",
                "leader": mined.get("leader", {}).get("method"),
                "test_ic": (mined.get("leader") or {}).get("test_ic"),
            }
        )
        if mined_bt:
            path.append(
                {
                    "step": 12,
                    "name": "mined_factor_backtest",
                    "strategy": mined_bt.get("strategy"),
                    "total_return_pct": mined_bt.get("total_return_pct"),
                }
            )
        factor_summary = {
            "leader_method": mined.get("leader", {}).get("method"),
            "test_ic": mined.get("leader", {}).get("test_ic"),
            "mined_return_pct": mined_bt.get("total_return_pct") if mined_bt else None,
        }

    payload: dict[str, Any] = {
        "ok": True,
        "path": path,
        "report_summary": {
            "company": report["research"]["company"],
            "strategy_return_pct": report["backtest"]["metrics"]["strategy_return_pct"],
            "maximum_drawdown_pct": report["backtest"]["metrics"]["maximum_drawdown_pct"],
            "trade_count": report["backtest"]["metrics"]["trade_count"],
            "risk_rejections": len(report["backtest"].get("risk_rejections", [])),
        },
        "rolling_summary": {
            "strategy": rolling["strategy"],
            "total_return_pct": rolling["total_return_pct"],
            "max_drawdown_pct": rolling["max_drawdown_pct"],
            "total_trades": rolling["total_trades"],
        },
        "realistic_cost_summary": {
            "total_return_pct": rolling_realistic.get("total_return_pct"),
            "sharpe_ratio": rolling_realistic.get("sharpe_ratio"),
        },
        "unified_metrics": unified,
        "risk_findings": risk_findings,
        "warnings": report["warnings"],
        "assumptions": [
            "Teaching sandbox only — no live orders.",
            "Event-driven and rolling engines use the same sample with different fidelity.",
            "Risk findings combine runtime rejections and post-backtest review rules.",
            "Audit path adds DSR/PBO/stability checks when include_audit=True.",
        ],
    }
    if audit_summary:
        payload["audit_summary"] = audit_summary
    if factor_summary:
        payload["factor_mining_summary"] = factor_summary
        payload["assumptions"].append(
            "Optional factor mine uses ML-only fast path; see chapter 21.0.1 for full GP/ML flow."
        )
    return payload
