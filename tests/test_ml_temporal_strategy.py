from __future__ import annotations

from backtest.rolling.service import execute_backtest, list_backtest_strategies


def test_ml_temporal_strategy_is_registered() -> None:
    strategies = {item["name"]: item for item in list_backtest_strategies()}
    assert "ml_temporal" in strategies
    assert "ML" in strategies["ml_temporal"]["displayName"]


def test_ml_temporal_strategy_runs_without_lookahead() -> None:
    payload = execute_backtest(
        strategy_name="ml_temporal",
        symbol="WEB3-DEMO/USDT",
        limit=120,
        stop_loss_pct=3,
        take_profit_pct=5,
    )
    assert payload["ok"] is True
    assert payload["strategy_key"] == "ml_temporal"
    assert payload["engine"] == "web3-trading/rolling-window"
    assert "alpha_pct" in payload
