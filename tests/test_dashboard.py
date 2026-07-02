import shutil

from dashboard import api as dashboard_api
from dashboard.snapshot import history_dir, load_offline, save_snapshot, snapshot_path


def _cleanup_test_dataset(name: str) -> None:
    snapshot_path(name).unlink(missing_ok=True)
    hist = history_dir(name)
    if hist.is_dir():
        shutil.rmtree(hist)


def test_dashboard_ai_picks_fixture() -> None:
    payload = dashboard_api.ai_picks()
    assert payload["ok"] is True
    assert "chance" in payload
    assert payload.get("source") in {"fixture", "live", "snapshot", "web3-trading-upstream"}


def test_snapshot_roundtrip() -> None:
    name = "test_ai_picks"
    _cleanup_test_dataset(name)
    sample = {"ok": True, "chance": [{"symbol": "BTC"}], "risk": [], "funds": []}
    path = save_snapshot(name, sample, origin="test")
    assert path.is_file()
    cached = load_offline(name)
    assert cached["source"] == "snapshot"
    assert cached["chance"][0]["symbol"] == "BTC"
    _cleanup_test_dataset(name)


def test_opportunity_scan_offline_shape() -> None:
    payload = dashboard_api.opportunity_scan(top_k=3, max_symbols=5)
    assert payload["ok"] is True
    assert "opportunities" in payload


def test_runtime_config_shape() -> None:
    payload = dashboard_api.runtime_config()
    assert payload["ok"] is True
    assert "upstream" in payload
    assert "symbols" in payload
    assert "dashboard_url" in payload["upstream"]


def test_market_candles_shape() -> None:
    payload = dashboard_api.market_candles(short=3, long=7)
    assert payload["ok"] is True
    assert "curve" in payload or "candles" in payload


def test_dashboard_onchain_has_fear_greed() -> None:
    payload = dashboard_api.onchain("BTC")
    assert payload["ok"] is True
    fear = (payload.get("marketSentiment") or {}).get("fearGreed") or {}
    assert "value" in fear


def test_market_tickers_fixture_shape() -> None:
    payload = dashboard_api.market_tickers(limit=5)
    assert payload["ok"] is True
    assert isinstance(payload.get("tickers"), list)


def test_web3_news_fixture_shape() -> None:
    payload = dashboard_api.web3_news(limit=5)
    assert payload["ok"] is True
    assert isinstance(payload.get("items"), list)
    assert payload["metrics"]["article_count"] >= 1
    assert "news_heat_24h" in payload["factor_signals"]
