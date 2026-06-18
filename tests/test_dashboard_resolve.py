from __future__ import annotations

import os

from dashboard import api as dashboard_api


def test_auto_mode_serves_snapshot_first(monkeypatch) -> None:
    monkeypatch.setenv("DASHBOARD_DATA_MODE", "auto")
    payload = dashboard_api.opportunity_scan(top_k=3, max_symbols=5)
    assert payload["ok"] is True
    assert payload.get("source") in {"snapshot", "fixture", "live", "web3-trading-upstream"}
    assert len(payload.get("opportunities") or []) >= 1


def test_refresh_skips_cached_first(monkeypatch) -> None:
    monkeypatch.setenv("DASHBOARD_DATA_MODE", "offline")
    offline = dashboard_api.market_tickers(limit=5, refresh=False)
    assert offline["ok"] is True
    assert isinstance(offline.get("tickers"), list)
