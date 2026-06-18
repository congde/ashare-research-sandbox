"""Tests for quant upgrade: walk-forward, portfolio, factor validation, bridge."""

from __future__ import annotations

from backtest.bridge import compare_engines, from_legacy_report, from_rolling_payload
from backtest.research_path import run_research_path
from backtest.rolling.portfolio import compare_portfolio
from backtest.rolling.service import run_walk_forward
from factor_mining.evaluate import evaluate_factor


def test_walk_forward_returns_best_params() -> None:
    payload = run_walk_forward(strategy_name="ma_crossover", num_windows=2, limit=120)
    assert payload["ok"] is True
    assert payload["num_windows"] >= 1
    assert isinstance(payload["best_params"], dict)
    assert "in_sample_sharpe" in payload
    assert "out_of_sample_sharpe" in payload


def test_portfolio_compare_three_legs() -> None:
    payload = compare_portfolio(strategy_name="ma_crossover", limit=120)
    assert payload["ok"] is True
    assert len(payload["legs"]) == 3
    assert len(payload["pair_correlations"]) == 3
    assert payload["equal_weight_leg_avg_return_pct"] is not None


def test_factor_validation_includes_quintile_and_turnover() -> None:
    signal = [float(i % 5 - 2) for i in range(60)]
    labels = [float((i % 7) - 3) * 0.01 for i in range(60)]
    metrics = evaluate_factor(signal, labels, min_samples=20)
    assert metrics is not None
    assert hasattr(metrics, "quintile_spread")
    assert hasattr(metrics, "turnover_rate")
    assert metrics.sample_count >= 20


def test_bridge_aligns_legacy_and_rolling() -> None:
    legacy = {
        "engine": "strategy_engine",
        "metrics": {
            "strategy_return_pct": 1.5,
            "maximum_drawdown_pct": -2.0,
            "sharpe_ratio": 0.8,
            "trade_count": 3,
            "win_rate": 66.0,
        },
    }
    rolling = {
        "engine": "rolling",
        "total_return_pct": 2.0,
        "max_drawdown_pct": 1.8,
        "sharpe_ratio": 0.9,
        "total_trades": 4,
        "win_rate": 50.0,
    }
    left = from_legacy_report(legacy)
    right = from_rolling_payload(rolling)
    assert left["total_return_pct"] == 1.5
    assert right["total_trades"] == 4
    unified = compare_engines(legacy, rolling)
    assert "delta_rolling_minus_legacy" in unified


def test_research_path_includes_unified_metrics() -> None:
    payload = run_research_path()
    assert payload["ok"] is True
    assert "unified_metrics" in payload
    assert "legacy" in payload["unified_metrics"]
    assert "rolling" in payload["unified_metrics"]
