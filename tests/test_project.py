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
    assert any("不构成投资建议" in warning for warning in report["warnings"])
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
    assert len(report["backtest"]["curve"]) == 35
    assert report["backtest"]["engine"] == "ai-trading/event-driven"
    assert isinstance(report["risk_checks"], list)
    assert report["fusion"]["product_shape"] == "web3-trading"


def test_invalid_windows_are_rejected() -> None:
    prices = load_prices(DATA_DIR / "prices.csv")
    with pytest.raises(ValueError, match="short < long"):
        run_backtest(prices, short=7, long=3)


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
    }
    findings = evaluate_backtest_risk(backtest)
    rule_ids = {item["rule_id"] for item in findings}
    assert "MAX_DAILY_LOSS_PCT" in rule_ids
    assert "STRATEGY_UNDERPERFORM" in rule_ids


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


def test_src_layout_matches_web3_trading_shape() -> None:
    src = ROOT / "src"
    for relative in (
        "backtest/runner.py",
        "research/report.py",
        "strategy_engine/backtest/engine.py",
        "strategy_engine/dsl/validator.py",
        "web/package.json",
        "web/static/index.html",
    ):
        assert (src / relative).is_file()
