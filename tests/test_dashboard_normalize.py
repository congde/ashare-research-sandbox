from __future__ import annotations

from dashboard import api
from dashboard.normalize import normalize_ai_picks, normalize_token_fund
from dashboard.snapshot import load_offline


def test_normalize_ai_picks_adds_display_fields() -> None:
    raw = load_offline("ai_picks")
    payload = normalize_ai_picks(raw)
    sample = (payload.get("chance") or [])[0]
    assert sample.get("title")
    assert sample.get("summary")


def test_normalize_token_fund_adds_display_fields() -> None:
    raw = load_offline("token_fund")
    payload = normalize_token_fund(raw)
    fund = payload.get("fund") or {}
    assert fund.get("netInflow24h") is not None
    assert (payload.get("sentiment") or {}).get("score") is not None
    assert (payload.get("fundMarketCapRatio") or {}).get("ratio") is not None


def test_api_ai_picks_returns_normalized_shape() -> None:
    payload = api.ai_picks()
    assert payload["ok"] is True
    sample = (payload.get("chance") or [])[0]
    assert sample.get("title")
    assert sample.get("summary")
