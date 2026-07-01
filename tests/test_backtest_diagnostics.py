from __future__ import annotations

from backtest.rolling.service import execute_backtest


def test_backtest_exposes_professional_diagnostics() -> None:
    payload = execute_backtest(
        strategy_name="ma_crossover",
        symbol="WEB3-DEMO/USDT",
        limit=120,
        stop_loss_pct=3.0,
        take_profit_pct=5.0,
    )

    assert payload["ok"] is True
    for key in (
        "benchmark_return_pct",
        "alpha_pct",
        "expectancy_pct",
        "exposure_pct",
        "payoff_ratio",
        "omega_ratio",
        "tail_ratio",
        "recovery_factor",
        "max_consecutive_wins",
        "max_consecutive_losses",
    ):
        assert key in payload
    assert 0 <= payload["exposure_pct"] <= 100
