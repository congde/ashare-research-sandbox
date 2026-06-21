from __future__ import annotations

from dashboard.source_card import source_card_from_manifest, validate_market_row


def test_validate_market_row_requires_source_time_and_positive_close() -> None:
    assert validate_market_row({"source": "fixture", "observed_at": "2026-06-20T00:00:00Z", "close": 100}) == []
    assert validate_market_row({"close": 0}) == [
        "missing source",
        "missing observed_at",
        "invalid close",
    ]


def test_source_card_from_manifest_keeps_limits_visible() -> None:
    manifest = {
        "datasets": {
            "market_tickers": {
                "origin": "snapshot",
                "updated_at": "2026-06-20T02:54:22+00:00",
                "path": "data/dashboard/snapshots/market_tickers.json",
                "complete": True,
                "reason": "",
            }
        }
    }

    card = source_card_from_manifest("market_tickers", manifest)

    assert card.domain == "行情"
    assert card.origin == "snapshot"
    assert card.complete is True
    assert "样本事实" in card.can_answer
    assert "实盘执行指令" in card.cannot_answer
