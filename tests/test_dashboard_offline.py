from __future__ import annotations

from dashboard.catalog import completeness_detail, is_complete, offline_status
from dashboard.fixture_builder import rebuild_incomplete_fixtures
from dashboard.snapshot import load_fixture, load_offline, load_snapshot


def test_opportunity_fixture_is_complete() -> None:
    rebuild_incomplete_fixtures()
    payload = load_fixture("opportunity_scan")
    assert is_complete("opportunity_scan", payload)


def test_market_candles_fixture_is_complete() -> None:
    rebuild_incomplete_fixtures()
    payload = load_fixture("market_candles")
    assert is_complete("market_candles", payload)
    assert len(payload.get("curve") or []) >= 5


def test_load_offline_skips_incomplete_snapshot() -> None:
    snapshot = load_snapshot("opportunity_scan")
    if snapshot and not is_complete("opportunity_scan", snapshot):
        payload = load_offline("opportunity_scan")
        assert is_complete("opportunity_scan", payload)
        assert payload.get("source") in {"fixture", "snapshot", "live"}


def test_load_offline_can_force_fixture(monkeypatch) -> None:
    monkeypatch.setenv("DASHBOARD_OFFLINE_SOURCE", "fixture")
    payload = load_offline("market_tickers")
    assert is_complete("market_tickers", payload)
    assert payload.get("source") == "fixture"


def test_offline_status_reports_datasets() -> None:
    status = offline_status()
    assert status["ok"] is True
    assert status["total_count"] >= 8
    assert "ai_picks" in status["datasets"]
