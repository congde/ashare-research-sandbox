"""Tests for Qbot-ported rolling strategies."""

from __future__ import annotations

from backtest.rolling.engine import run_backtest
from backtest.rolling.indicators import IndicatorSeries, compute_all_indicators
from backtest.rolling.models import BacktestConfig
from backtest.rolling.registry import get_strategy, list_strategies
from backtest.rolling.strategies.adx_macd_trend import ADXMacdTrendStrategy
from backtest.rolling.service import execute_backtest


def _synthetic_candles(closes: list[float]) -> list[dict]:
    candles: list[dict] = []
    for idx, close in enumerate(closes):
        candles.append(
            {
                "tsSec": 1_700_000_000 + idx * 86_400,
                "date": f"2024-01-{idx + 1:02d}",
                "open": close,
                "close": close,
                "high": round(close * 1.01, 6),
                "low": round(close * 0.99, 6),
                "volume": 1000.0,
                "turnover": close * 1000,
            }
        )
    return candles


def test_qbot_strategies_are_registered() -> None:
    names = {item["name"] for item in list_strategies()}
    assert "ma_crossover" in names
    assert "boll_mean_reversion" in names
    assert "macd_crossover" in names
    assert "adx_macd_trend" in names


def test_ma_crossover_runs_on_teaching_sample() -> None:
    payload = execute_backtest(strategy_name="ma_crossover", limit=35)
    assert payload["ok"] is True
    assert payload["strategy_key"] == "ma_crossover"
    assert payload["total_candles"] >= 20


def test_adx_macd_trend_applies_hold_bars_override() -> None:
    payload = execute_backtest(strategy_name="adx_macd_trend", limit=120)
    assert payload["ok"] is True
    assert payload["strategy_key"] == "adx_macd_trend"
    assert payload["max_hold_bars"] == 3


def test_boll_mean_reversion_enters_on_low_band_touch() -> None:
    base = [100.0] * 25
    dip = [92.0, 91.0, 90.0, 91.5, 93.0, 94.0, 95.0]
    candles = _synthetic_candles(base + dip)
    strategy = get_strategy("boll_mean_reversion")
    params = strategy.default_params()
    config = BacktestConfig(min_context=20, commission_pct=0.1)

    trades, _equity, signals = run_backtest(candles, strategy, params, config)
    long_signals = [s for s in signals if s["action"] == "LONG"]
    assert long_signals, "expected at least one long entry after lower-band touch"
    assert trades, "expected at least one completed or open trade path"


def test_ma_crossover_golden_cross_produces_long_signal() -> None:
    closes = [100 - i * 0.5 for i in range(25)] + [88 + i * 1.2 for i in range(20)]
    candles = _synthetic_candles(closes)
    strategy = get_strategy("ma_crossover")
    params = {"fast_period": 5, "slow_period": 10, "entry_threshold": 25}
    config = BacktestConfig(min_context=15, commission_pct=0.1)

    _trades, _equity, signals = run_backtest(candles, strategy, params, config)
    assert any(s["action"] == "LONG" and s["score"] >= 25 for s in signals)


def test_macd_crossover_golden_cross_produces_long_signal() -> None:
    closes = [100 - i * 0.4 for i in range(40)] + [84 + i * 1.5 for i in range(40)]
    candles = _synthetic_candles(closes)
    strategy = get_strategy("macd_crossover")
    params = strategy.default_params()
    config = BacktestConfig(min_context=35, commission_pct=0.1)

    _trades, _equity, signals = run_backtest(candles, strategy, params, config)
    assert any(s["action"] == "LONG" and s["score"] >= 25 for s in signals)


def test_adx_indicator_series_populated() -> None:
    closes = [100 + i * 0.3 for i in range(120)]
    candles = _synthetic_candles(closes)
    indicators = compute_all_indicators(candles)
    assert len(indicators.adx) == len(candles)
    assert indicators.adx[-1] is not None
    assert indicators.ema13[-1] is not None
    assert indicators.ema89[-1] is not None


def test_adx_macd_trend_buy_when_qbot_conditions_met() -> None:
    """Unit test for Qbot entry rule without relying on ADX<=25 in strong trends."""
    strategy = ADXMacdTrendStrategy()
    params = strategy.default_params()
    candles = _synthetic_candles([100.0] * 100)
    indicators = IndicatorSeries(
        adx=[None] * 98 + [23.0, 24.0],
        ema13=[None] * 99 + [105.0],
        ema55=[None] * 99 + [103.0],
        ema89=[None] * 99 + [101.0],
        macd_histogram=[None] * 98 + [0.10, 0.20],
    )

    signal = strategy.generate_signal(candles, 99, params, indicators)
    assert signal.action == "LONG"
    assert signal.score >= 25
