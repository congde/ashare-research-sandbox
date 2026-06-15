from __future__ import annotations

from dashboard.dataset_views import trim_dex_trending, trim_market_tickers
from dashboard.valuescan import configured
from dashboard.valuescan_full import fetch_full_token_data, fetch_global_valuescan_data


def test_trim_market_tickers_from_full_payload() -> None:
    full = {
        "ok": True,
        "tickers": [{"symbol": f"COIN{i}-USDT", "last": 1.0} for i in range(10)],
        "count": 10,
        "full": True,
    }
    view = trim_market_tickers(full, quote="USDT", limit=3)
    assert len(view["tickers"]) == 3
    assert view["view"]["limit"] == 3


def test_trim_market_tickers_pins_majors() -> None:
    full = {
        "ok": True,
        "tickers": [
            {"symbol": "COIN1-USDT", "last": 1.0},
            {"symbol": "BTC-USDT", "last": 60000.0, "changeRate": -0.01},
            {"symbol": "ETH-USDT", "last": 3000.0, "changeRate": 0.02},
            {"symbol": "COIN2-USDT", "last": 2.0},
        ],
    }
    view = trim_market_tickers(full, quote="USDT", limit=2)
    symbols = [item["symbol"] for item in view["tickers"]]
    assert symbols == ["BTC-USDT", "ETH-USDT"]


def test_trim_dex_trending_from_full_payload() -> None:
    full = {
        "ok": True,
        "tokens": [{"symbol": f"T{i}"} for i in range(8)],
        "full": True,
    }
    view = trim_dex_trending(full, limit=2)
    assert len(view["tokens"]) == 2


def test_fetch_full_token_data_without_credentials() -> None:
    if configured():
        return
    payload = fetch_full_token_data("BTC")
    assert payload.get("symbol") == "BTC"
    assert "vsTokenId" not in payload


def test_fetch_global_without_credentials() -> None:
    if configured():
        return
    payload = fetch_global_valuescan_data()
    assert payload.get("ok") is True
    assert payload.get("chance") == []
