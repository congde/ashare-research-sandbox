from __future__ import annotations

from backtest.rolling.service import execute_backtest, list_backtest_strategies


def test_ml_temporal_strategy_is_registered() -> None:
    strategies = {item["name"]: item for item in list_backtest_strategies()}
    assert "ml_temporal" in strategies
    assert "ML" in strategies["ml_temporal"]["displayName"]
    assert "ml_temporal_knn" in strategies
    assert "ml_temporal_tree" in strategies
    assert "ml_temporal_boosting" in strategies
    assert "ml_temporal_ensemble" in strategies


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


def test_ml_temporal_model_variants_run() -> None:
    for strategy_name in [
        "ml_temporal_knn",
        "ml_temporal_tree",
        "ml_temporal_boosting",
        "ml_temporal_ensemble",
    ]:
        payload = execute_backtest(
            strategy_name=strategy_name,
            symbol="WEB3-DEMO/USDT",
            limit=120,
            stop_loss_pct=3,
            take_profit_pct=5,
        )
        assert payload["ok"] is True
        assert payload["strategy_key"] == strategy_name
        assert payload["engine"] == "web3-trading/rolling-window"
