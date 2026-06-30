from __future__ import annotations

from dashboard.kline_analysis import analyze_candles, kline_verdict, run_kline_analysis


def _sample_candles(count: int = 40) -> list[dict]:
    candles = []
    price = 100.0
    for index in range(count):
        open_price = price
        close = price + (1 if index % 3 else -0.5)
        high = max(open_price, close) + 1
        low = min(open_price, close) - 1
        candles.append(
            {
                "tsSec": 1_700_000_000 + index * 3600,
                "open": open_price,
                "close": close,
                "high": high,
                "low": low,
                "volume": 10 + index,
            }
        )
        price = close
    return candles


def test_analyze_candles_returns_metrics() -> None:
    analysis = analyze_candles(_sample_candles())
    assert analysis is not None
    assert analysis["trend"] in {"bullish", "bearish", "weak_bullish", "weak_bearish", "neutral"}
    assert analysis["rsi"] is not None
    assert analysis["support"] <= analysis["resistance"]


def test_kline_verdict_has_action_label() -> None:
    analysis = analyze_candles(_sample_candles())
    verdict = kline_verdict(analysis)
    assert verdict["actionLabel"]
    assert "score" in verdict
    assert verdict["reasons"]


def test_run_kline_analysis_offline_fixture() -> None:
    payload = run_kline_analysis("BTC-USDT", kline_type="1day", limit=60)
    assert payload.get("ok") is True
    assert payload.get("symbol") == "BTC-USDT"
    assert len(payload.get("candles") or []) >= 20
    assert payload.get("verdict", {}).get("actionLabel")
