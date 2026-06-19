"""Tests for backtest teaching helpers."""

from __future__ import annotations

from backtest.metrics_explain import explain_metrics
from backtest.pollution import run_pollution_checks
from backtest.research_path import run_research_path
from backtest.trace import run_ma_crossover_trace, run_teaching_scenario
from backtest.rolling.service import compare_strategies, compare_windows


def test_ma_crossover_trace_is_auditable() -> None:
    payload = run_ma_crossover_trace()
    assert payload["ok"] is True
    assert payload["trail"]
    assert payload["metrics"]["trade_count"] > 0
    assert payload["what_it_proves"]


def test_teaching_scenario_covers_fill_pending_and_risk_block() -> None:
    payload = run_teaching_scenario()
    assert payload["ok"] is True
    assert payload["trades"]
    assert payload["pending_at_end"]
    assert payload["risk_rejections"]
    assert payload["risk_rejections"][0]["rule_id"] == "MAX_POSITION_PCT"


def test_compare_strategies_returns_five_rows() -> None:
    payload = compare_strategies(limit=120)
    assert payload["ok"] is True
    assert len(payload["strategies"]) == 5
    assert payload["leader"]
    assert payload["laggard"]


def test_compare_windows_splits_sample() -> None:
    payload = compare_windows(strategy_name="ma_crossover", num_windows=3, limit=120)
    assert payload["ok"] is True
    assert len(payload["windows"]) == 3
    assert "stable" in payload


def test_explain_metrics_ranks_return_and_drawdown() -> None:
    payload = explain_metrics(limit=120)
    assert payload["ok"] is True
    assert payload["highest_return"]
    assert payload["lowest_drawdown"]
    assert payload["guidance"]


def test_pollution_checks_cover_three_cases() -> None:
    payload = run_pollution_checks()
    by_label = {item["label"]: item for item in payload["cases"]}
    assert by_label["safe_noop"]["backtest_ready"] is True
    assert by_label["unsafe_import"]["dsl_valid"] is False
    assert by_label["lookahead_shift"]["dsl_valid"] is True
    assert by_label["lookahead_shift"]["lookahead_clean"] is False


def test_research_path_chains_modules() -> None:
    payload = run_research_path(include_audit=True)
    assert payload["ok"] is True
    assert len(payload["path"]) == 10
    assert payload["report_summary"]["trade_count"] > 0
    assert payload["rolling_summary"]["total_trades"] >= 0
    assert "audit_summary" in payload
    assert "realistic_cost_summary" in payload
