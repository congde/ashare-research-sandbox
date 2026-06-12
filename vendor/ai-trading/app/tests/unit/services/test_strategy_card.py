"""Tests for the Strategy Card schema + backtest-comparison helper."""

from __future__ import annotations

import pytest

from app.services.strategy_card import (
    ExpectedMetrics,
    backtest_metrics_match,
    parse_card_json,
)

# ── Helpers ─────────────────────────────────────────────────────


def _minimal_card_json() -> dict:
    """Smallest valid card — only required fields + empty defaults."""
    return {
        "name": "Test Strategy",
        "thesis": "BTC reverts to 50-day MA in low-vol regimes.",
        "valid_when": ["low realised vol", "btc above 200d MA"],
        "invalid_when": ["news-driven gaps", "high vol regime"],
        "risk_checklist": ["confirm 0.001 BTC min lot", "wallet > $50 USDT"],
    }


# ── parse_card_json ─────────────────────────────────────────────


def test_parse_minimal_card() -> None:
    card = parse_card_json(_minimal_card_json())
    assert card.name == "Test Strategy"
    assert card.thesis.startswith("BTC reverts")
    assert card.valid_when == ("low realised vol", "btc above 200d MA")
    # Optional fields take defaults.
    assert card.symbol == ""
    assert card.version == 1
    assert card.expected_metrics.pnl_pct_min is None


def test_parse_card_from_json_string() -> None:
    """parse_card_json accepts both dict and JSON string. Pin both."""
    import json

    card = parse_card_json(json.dumps(_minimal_card_json()))
    assert card.name == "Test Strategy"


def test_parse_card_with_full_metrics() -> None:
    raw = _minimal_card_json()
    raw["expected_metrics"] = {
        "pnl_pct_min": 5.0,
        "sharpe_min": 1.2,
        "max_drawdown_pct_max": 12.5,
        "win_rate_min": 0.55,
        "notes": "tuned for 1y BTC backtest",
    }
    card = parse_card_json(raw)
    assert card.expected_metrics.pnl_pct_min == 5.0
    assert card.expected_metrics.sharpe_min == 1.2
    assert card.expected_metrics.max_drawdown_pct_max == 12.5
    assert card.expected_metrics.win_rate_min == 0.55
    assert "1y BTC" in card.expected_metrics.notes


def test_parse_card_missing_required_field_raises() -> None:
    """Pin loud failure on missing required field — LLM
    self-correction depends on this signal."""
    bad = _minimal_card_json()
    del bad["thesis"]
    with pytest.raises(ValueError, match="missing required"):
        parse_card_json(bad)


def test_parse_card_wrong_list_type_raises() -> None:
    bad = _minimal_card_json()
    bad["valid_when"] = "should be a list, not a string"
    with pytest.raises(ValueError, match="must be list"):
        parse_card_json(bad)


def test_parse_card_non_string_in_list_raises() -> None:
    """Pin that valid_when MUST contain strings — otherwise the
    LLM might emit numbers / objects that the UI can't render."""
    bad = _minimal_card_json()
    bad["valid_when"] = ["valid", 42, "another"]
    with pytest.raises(ValueError, match="must contain only strings"):
        parse_card_json(bad)


def test_parse_card_tolerates_empty_string_metric_values() -> None:
    """LLMs sometimes emit "" or "null" instead of leaving a key
    out. Tolerate both."""
    raw = _minimal_card_json()
    raw["expected_metrics"] = {
        "pnl_pct_min": "",
        "sharpe_min": "null",
        "max_drawdown_pct_max": None,
    }
    card = parse_card_json(raw)
    assert card.expected_metrics.pnl_pct_min is None
    assert card.expected_metrics.sharpe_min is None
    assert card.expected_metrics.max_drawdown_pct_max is None


# ── StrategyCard.to_json round-trip ────────────────────────────


def test_card_round_trips_through_json() -> None:
    """Build → to_json → parse_card_json → identical card."""
    original = parse_card_json(_minimal_card_json())
    rebuilt = parse_card_json(original.to_json())
    assert rebuilt == original


def test_card_to_json_is_sorted() -> None:
    """sort_keys for stable diff + audit-chain embedding. Pin via
    a deterministic substring check."""
    card = parse_card_json(_minimal_card_json())
    text = card.to_json()
    # Sorted keys → "invalid_when" comes before "name", "risk_checklist"
    # comes before "thesis", etc. Spot-check one ordering pair.
    assert text.index('"name"') < text.index('"thesis"')


# ── backtest_metrics_match ──────────────────────────────────────


def test_all_metrics_pass_when_actual_meets_or_exceeds() -> None:
    raw = _minimal_card_json()
    raw["expected_metrics"] = {
        "pnl_pct_min": 5.0,
        "sharpe_min": 1.0,
        "max_drawdown_pct_max": 15.0,
        "win_rate_min": 0.5,
    }
    card = parse_card_json(raw)
    report = backtest_metrics_match(
        card, pnl_pct=7.5, sharpe=1.3, max_drawdown_pct=12.0, win_rate=0.6,
    )
    assert report.pnl_pct_pass is True
    assert report.sharpe_pass is True
    assert report.drawdown_pass is True
    assert report.win_rate_pass is True
    assert report.overall_pass is True


def test_pnl_below_expected_fails() -> None:
    """pnl_pct semantics: actual must be >= expected. Pin via
    a -3% actual against a +5% claim."""
    raw = _minimal_card_json()
    raw["expected_metrics"] = {"pnl_pct_min": 5.0}
    card = parse_card_json(raw)
    report = backtest_metrics_match(
        card, pnl_pct=-3.0, sharpe=0.0, max_drawdown_pct=0.0, win_rate=0.0,
    )
    assert report.pnl_pct_pass is False
    assert report.overall_pass is False


def test_drawdown_above_max_fails() -> None:
    """max_drawdown semantics: actual must be <= expected (less DD allowed)."""
    raw = _minimal_card_json()
    raw["expected_metrics"] = {"max_drawdown_pct_max": 10.0}
    card = parse_card_json(raw)
    report = backtest_metrics_match(
        card, pnl_pct=0.0, sharpe=0.0, max_drawdown_pct=20.0, win_rate=0.0,
    )
    assert report.drawdown_pass is False
    assert report.overall_pass is False


def test_unclaimed_metrics_get_none_verdict() -> None:
    """Card with no expected_metrics → all individual verdicts None,
    overall False, notes explain why."""
    card = parse_card_json(_minimal_card_json())  # no expected_metrics
    report = backtest_metrics_match(
        card, pnl_pct=10.0, sharpe=2.0, max_drawdown_pct=5.0, win_rate=0.7,
    )
    assert report.pnl_pct_pass is None
    assert report.sharpe_pass is None
    assert report.drawdown_pass is None
    assert report.win_rate_pass is None
    assert report.overall_pass is False
    assert "no metric claims" in report.notes


def test_partial_claims_only_check_explicit_metrics() -> None:
    """Card claims pnl_pct only — drawdown miss shouldn't fail
    overall, since the card didn't claim it. Pin the partial-claim
    semantics."""
    raw = _minimal_card_json()
    raw["expected_metrics"] = {"pnl_pct_min": 5.0}
    card = parse_card_json(raw)
    report = backtest_metrics_match(
        card,
        pnl_pct=10.0,  # passes
        sharpe=0.0,
        max_drawdown_pct=99.0,  # would fail if claimed, but card didn't claim
        win_rate=0.0,
    )
    assert report.pnl_pct_pass is True
    assert report.drawdown_pass is None
    assert report.overall_pass is True


# ── Field validation properties ────────────────────────────────


def test_card_is_frozen() -> None:
    """Pin immutability — once produced, mutation requires re-parse.
    Useful for audit log integrity."""
    card = parse_card_json(_minimal_card_json())
    with pytest.raises((AttributeError, TypeError)):
        card.name = "Mutated"  # type: ignore[misc]


def test_expected_metrics_is_frozen() -> None:
    em = ExpectedMetrics(pnl_pct_min=5.0)
    with pytest.raises((AttributeError, TypeError)):
        em.pnl_pct_min = 10.0  # type: ignore[misc]
