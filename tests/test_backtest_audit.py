"""Tests for backtest audit roadmap (DSR, trials, cost presets, robustness)."""

from __future__ import annotations

from backtest.audit.dsr import deflated_sharpe_ratio, probabilistic_sharpe_ratio
from backtest.cost_presets import resolve_cost_options
from backtest.rolling.service import execute_backtest, run_robustness_audit, run_walk_forward
from backtest.trials import get_ledger, reset_ledger_for_tests
from data.pit import pit_teaching_summary


def test_cost_presets_differ() -> None:
    teaching = execute_backtest(strategy_name="ma_crossover", limit=120, cost_preset="teaching")
    realistic = execute_backtest(strategy_name="ma_crossover", limit=120, cost_preset="realistic")
    assert teaching["cost_preset"] == "teaching"
    assert realistic["cost_preset"] == "realistic"
    assert realistic["slippage_pct"] > teaching["slippage_pct"]


def test_walk_forward_includes_dsr_and_trials() -> None:
    reset_ledger_for_tests()
    payload = run_walk_forward(strategy_name="ma_crossover", num_windows=2, limit=120)
    assert payload["ok"] is True
    assert "dsr" in payload
    assert payload.get("num_trials", 0) >= 1


def test_robustness_audit_returns_pbo_and_sensitivity() -> None:
    payload = run_robustness_audit(strategy_name="ma_crossover", limit=120)
    assert payload["ok"] is True
    assert "parameter_sensitivity" in payload
    assert "pbo" in payload
    assert payload["parameter_sensitivity"]["tested"] >= 1


def test_trial_ledger_records_execute_backtest() -> None:
    reset_ledger_for_tests()
    execute_backtest(strategy_name="buy_and_hold", limit=120)
    summary = get_ledger().summary()
    assert summary["num_trials"] >= 1


def test_dsr_decreases_with_more_trials() -> None:
    low = deflated_sharpe_ratio(1.5, sample_length=120, num_trials=1)
    high = deflated_sharpe_ratio(1.5, sample_length=120, num_trials=100)
    assert high["dsr"] <= low["dsr"]


def test_psr_in_valid_range() -> None:
    psr = probabilistic_sharpe_ratio(1.0, 0.0, 252)
    assert 0.0 <= psr <= 1.0


def test_pit_teaching_sample_has_no_interval_errors() -> None:
    payload = pit_teaching_summary()
    assert payload["ok"] is True
    assert payload["validation_errors"] == []


def test_resolve_cost_preset_realistic() -> None:
    cost = resolve_cost_options(preset="realistic")
    assert cost["dynamic_slippage"] is True
    assert cost["slippage_pct"] > 0
