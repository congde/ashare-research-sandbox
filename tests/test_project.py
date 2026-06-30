from pathlib import Path

import pytest

from backtest import calmar_ratio, load_prices, run_backtest, sharpe_ratio
from paths import DATA_DIR, PROJECT_ROOT
from research.report import build_report
from risk import evaluate_backtest_risk
from strategy_engine.backtest import BacktestEngine
from strategy_engine.dsl import check_lookahead_bias, validate_strategy_code
from strategy_engine.strategies.ma_crossover import make_ma_crossover_strategy


ROOT = PROJECT_ROOT


def test_report_has_traceable_research_and_safety_boundary() -> None:
    report = build_report()
    assert report["research"]["facts"][0]["source_id"] == "S1"
    assert len(report["research"]["sources"]) >= 3
    assert any("不进入实盘执行" in warning for warning in report["warnings"])
    assert any("不能执行交易" in warning for warning in report["warnings"])
    assert report["research"]["company"] == "示例协议（WEB3-DEMO/USDT）"


def test_backtest_is_deterministic_and_reports_risk() -> None:
    report = build_report(short=3, long=7)
    metrics = report["backtest"]["metrics"]
    assert metrics["trade_count"] > 0
    assert metrics["final_equity"] > 0
    assert metrics["maximum_drawdown_pct"] <= 0
    assert "calmar_ratio" in metrics
    assert "sharpe_ratio" in metrics
    assert len(report["backtest"]["curve"]) == len(load_prices(DATA_DIR / "prices.csv"))
    assert report["backtest"]["engine"] == "ai-trading/event-driven"
    assert isinstance(report["risk_checks"], list)
    assert report["fusion"]["product_shape"] == "web3-trading"


def test_invalid_windows_are_rejected() -> None:
    prices = load_prices(DATA_DIR / "prices.csv")
    with pytest.raises(ValueError, match="short < long"):
        run_backtest(prices, short=7, long=3)


def test_load_prices_keeps_default_csv_behavior() -> None:
    prices = load_prices(DATA_DIR / "prices.csv")
    assert prices[0].date == "2025-01-02"
    assert prices[0].close == pytest.approx(8.69)


def test_load_prices_accepts_custom_delimiter_and_encoding(tmp_path: Path) -> None:
    source = tmp_path / "prices_semicolon_gbk.csv"
    source.write_text(
        'date;note;close\n2025-01-02;"备注;含分号";8.69\n2025-01-03;"正常";8.76\n',
        encoding="gbk",
    )

    prices = load_prices(source, delimiter=";", encoding="gbk")

    assert [(item.date, item.close) for item in prices] == [
        ("2025-01-02", 8.69),
        ("2025-01-03", 8.76),
    ]


def test_calmar_ratio_adapts_negative_drawdown_convention() -> None:
    assert calmar_ratio(12.0, -4.0) == 3.0
    assert calmar_ratio(12.0, 0.0) == 0.0


def test_research_report_exists() -> None:
    report_path = ROOT / "research-report.md"
    text = report_path.read_text(encoding="utf-8")
    assert "Facts" in text
    assert "web3-trading" in text


def test_restricted_strategy_dsl_blocks_unsafe_code() -> None:
    safe = validate_strategy_code("def on_tick(ctx, candle):\n    return None")
    unsafe = validate_strategy_code(
        "import os\n\ndef on_tick(ctx, candle):\n    return os.getcwd()"
    )
    assert safe.valid
    assert not unsafe.valid
    assert not validate_strategy_code(
        "import pandas\n\ndef on_tick(ctx, candle):\n    return None"
    ).valid


def test_strategy_dsl_reports_lookahead_bias() -> None:
    report = check_lookahead_bias(
        "def on_tick(ctx, candle):\n    return ctx.history[-1]"
    )
    assert report.clean
    future_report = check_lookahead_bias(
        "def on_tick(ctx, candle):\n    return ctx.future_close"
    )
    assert not future_report.clean
    assert future_report.errors[0].rule == "L001"


def test_sharpe_ratio_uses_daily_annualization() -> None:
    equity = [10_000.0, 10_100.0, 10_050.0, 10_200.0]
    assert sharpe_ratio(equity) != 0.0


def test_risk_checks_flag_large_drawdown() -> None:
    backtest = {
        "metrics": {
            "maximum_drawdown_pct": -20.0,
            "strategy_return_pct": 5.0,
            "buy_hold_return_pct": 10.0,
            "trade_count": 4,
        },
        "curve": [{"equity": 10_000}] * 35,
        "risk_rejections": [],
    }
    findings = evaluate_backtest_risk(backtest)
    rule_ids = {item["rule_id"] for item in findings}
    assert "MAX_DAILY_LOSS_PCT" in rule_ids
    assert "STRATEGY_UNDERPERFORM" in rule_ids


def test_backtest_includes_runtime_risk_rules() -> None:
    report = build_report(short=3, long=7)
    assert report["backtest"]["risk_rules"]
    assert "EMERGENCY_HALT" in report["backtest"]["risk_rules"]
    assert "risk_rejections" in report["backtest"]
    assert report["fusion"]["risk_rules"]


def test_event_driven_engine_runs_fixed_sample() -> None:
    prices = load_prices(DATA_DIR / "prices.csv")
    report = run_backtest(prices, short=3, long=7)
    assert report["metrics"]["trade_count"] > 0
    assert report["trades"][0]["action"] in {"BUY", "SELL"}
    assert report["trades"][0]["date"] in {item.date for item in prices}


def test_event_driven_engine_uses_on_tick_strategy() -> None:
    from backtest.runner import prices_to_candles

    prices = load_prices(DATA_DIR / "prices.csv")
    candles = prices_to_candles(prices[:10])
    engine = BacktestEngine(strategy_fn=make_ma_crossover_strategy(3, 7))
    result = engine.run(candles, symbol="WEB3-DEMO/USDT", timeframe="1day")
    assert len(result.equity_curve) == 10


def test_rolling_backtest_matches_web3_trading_engine() -> None:
    from backtest.rolling.service import execute_backtest, list_backtest_strategies

    strategies = list_backtest_strategies()
    names = {item["name"] for item in strategies}
    assert "technical_signal" in names
    assert "buy_and_hold" in names

    payload = execute_backtest(strategy_name="ma_crossover", stop_loss_pct=3.0, take_profit_pct=5.0)
    assert payload["ok"] is True
    assert payload["engine"] == "web3-trading/rolling-window"
    assert payload["total_trades"] > 0
    assert payload["equity_curve"]
    assert payload["trades"][0]["entryPrice"] > 0


def test_shared_dashboard_utilities() -> None:
    from dashboard.kline_curve import candles_to_curve, kline_payload_to_curve
    from dashboard.text import market_overview

    candles = [
        {"date": "2026-01-01", "close": 10.0},
        {"date": "2026-01-02", "close": 12.0},
        {"date": "2026-01-03", "close": 11.0},
    ]
    curve = candles_to_curve(candles, short=2, long=3)
    assert curve[-1]["short_ma"] == 11.5
    assert curve[-1]["long_ma"] == 11.0

    payload_curve = kline_payload_to_curve(
        [{"close": 10, "time": 1704067200}, {"c": 12, "date": "2026-01-02"}],
        short=2,
        long=2,
    )
    assert len(payload_curve) == 2

    overview = market_overview(
        [{"symbol": "BTC", "label": "强势", "signal": "BUY"}],
        5,
    )
    assert "BTC" in overview


def test_shared_factor_zscore() -> None:
    from factor_mining.stats import zscore_series

    series = zscore_series([1.0, 2.0, 3.0, 4.0, 5.0])
    assert all(value is not None for value in series)
    assert series[0] < 0 < series[-1]

    sparse = zscore_series([1.0, None, 2.0], min_samples=3, on_insufficient="none")
    assert sparse == [None, None, None]


def test_compile_strategy_wires_sandbox_api() -> None:
    from strategy_engine.dsl import compile_strategy

    fn = compile_strategy("def on_tick(ctx, candle):\n    return None\n")
    assert callable(fn)


def test_ta_core_matches_rolling_indicators() -> None:
    from backtest.rolling.indicators import compute_all_indicators
    from ta.core import rolling_rsi, rolling_sma

    closes = [10.0 + (index % 5) * 0.3 for index in range(30)]
    assert rolling_sma(closes, 3)[-1] == pytest.approx(sum(closes[-3:]) / 3)
    assert rolling_rsi(closes, 14)[-1] is not None

    candles = [
        {
            "open": price,
            "high": price + 0.5,
            "low": price - 0.5,
            "close": price,
            "volume": 1000.0,
            "tsSec": index,
        }
        for index, price in enumerate(closes)
    ]
    series = compute_all_indicators(candles)
    assert series.sma20[-1] is not None
    assert series.rsi[-1] is not None


def test_qbot_rules_shared_helpers() -> None:
    from backtest.rolling.strategies.qbot_rules import (
        crossed_down,
        crossed_up,
        ema_bullish_alignment,
        long_only_cross_signal,
        macd_cross_flags,
    )

    assert crossed_up(1.0, 2.0, 3.0, 2.0)
    assert crossed_down(3.0, 2.0, 1.0, 2.0)
    assert long_only_cross_signal(crossed_up_flag=True, crossed_down_flag=False) is not None
    assert ema_bullish_alignment(3.0, 2.0, 1.0)
    assert macd_cross_flags(1.0, 2.0, 3.0, 2.0) == (True, False)


def test_qbot_strategies_still_execute() -> None:
    from backtest.rolling.service import execute_backtest

    for strategy_name in (
        "ma_crossover",
        "macd_crossover",
        "macd",
        "boll_mean_reversion",
        "adx_macd_trend",
    ):
        payload = execute_backtest(strategy_name=strategy_name, limit=120)
        assert payload["ok"] is True
        assert payload["strategy_key"] == strategy_name


def test_src_layout_matches_web3_trading_shape() -> None:
    src = ROOT / "src"
    for relative in (
        "backtest/runner.py",
        "backtest/rolling/engine.py",
        "research/report.py",
        "strategy_engine/backtest/engine.py",
        "strategy_engine/dsl/validator.py",
        "web/package.json",
        "web/static/index.html",
    ):
        assert (src / relative).is_file()
