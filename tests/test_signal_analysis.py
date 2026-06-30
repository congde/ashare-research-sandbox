from __future__ import annotations

from dashboard.signal_analysis import run_signal_analysis


def test_run_signal_analysis_shape() -> None:
    payload = run_signal_analysis("BTC")
    assert payload.get("ok") is True
    assert payload.get("symbol") == "BTC"
    assert payload.get("signalLabel")
    assert payload.get("tradePlan", {}).get("target1") is not None
    assert "1hour" in (payload.get("kline") or {})
    assert len(payload.get("logicFlow") or []) == 4
