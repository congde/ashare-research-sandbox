"""Combinatorial purged cross-validation (teaching-scale CPCV)."""

from __future__ import annotations

import itertools
import random
from typing import Any

from backtest.rolling.engine import run_backtest
from backtest.rolling.metrics import compute_metrics
from backtest.rolling.models import BacktestConfig
from backtest.rolling.strategies.base import Strategy


def _kline_embargo_bars(kline_type: str) -> int:
    return {
        "15min": 4,
        "1hour": 2,
        "4hour": 1,
        "1day": 1,
    }.get(kline_type, 1)


def run_cpcv_audit(
    candles: list[dict[str, Any]],
    strategy: Strategy,
    *,
    config: BacktestConfig,
    num_groups: int = 6,
    test_groups: int = 2,
    max_paths: int = 15,
) -> dict[str, Any]:
    """Evaluate strategy on multiple OOS paths with embargo between folds."""
    params = dict(strategy.default_params())
    n = len(candles)
    groups = max(4, min(8, num_groups))
    group_size = max(config.min_context + 5, n // groups)
    if group_size * groups > n:
        groups = max(2, n // group_size)

    group_ids = list(range(groups))
    combos = list(itertools.combinations(group_ids, test_groups))
    if len(combos) > max_paths:
        combos = random.Random(19).sample(combos, max_paths)

    embargo = _kline_embargo_bars(config.kline_type)
    path_returns: list[float] = []
    path_sharpes: list[float] = []

    for test_group_set in combos:
        test_indices: set[int] = set()
        for group in test_group_set:
            start = group * group_size
            end = min(n, (group + 1) * group_size)
            for idx in range(start, end):
                test_indices.add(idx)
                for gap in range(1, embargo + 1):
                    if idx + gap < n:
                        test_indices.add(idx + gap)

        oos_candles = [candles[i] for i in sorted(test_indices)]
        if len(oos_candles) < config.min_context + 5:
            continue

        oos_config = BacktestConfig(
            min_context=config.min_context,
            stop_loss_pct=config.stop_loss_pct,
            take_profit_pct=config.take_profit_pct,
            trailing_stop_pct=config.trailing_stop_pct,
            max_hold_bars=config.max_hold_bars,
            commission_pct=config.commission_pct,
            slippage_pct=config.slippage_pct,
            dynamic_slippage=config.dynamic_slippage,
            dynamic_slippage_factor=config.dynamic_slippage_factor,
            funding_rate_pct=config.funding_rate_pct,
            kline_type=config.kline_type,
        )
        trades, equity, _ = run_backtest(oos_candles, strategy, params, oos_config)
        metrics = compute_metrics(
            trades=trades,
            equity_curve=equity,
            candles=oos_candles,
            symbol="",
            kline_type=config.kline_type,
            strategy_name=strategy.display_name,
        )
        path_returns.append(metrics.total_return_pct)
        path_sharpes.append(metrics.sharpe_ratio)

    if not path_returns:
        return {
            "num_paths": 0,
            "profitable_paths_pct": 0.0,
            "sharpe_p5": 0.0,
            "sharpe_p50": 0.0,
            "sharpe_p95": 0.0,
            "verdict": "insufficient_data",
        }

    path_returns.sort()
    path_sharpes.sort()
    profitable = sum(1 for value in path_returns if value > 0) / len(path_returns) * 100

    def percentile(values: list[float], pct: float) -> float:
        if not values:
            return 0.0
        idx = int(round((len(values) - 1) * pct))
        return values[max(0, min(len(values) - 1, idx))]

    verdict = "robust" if profitable >= 50 and percentile(path_sharpes, 0.5) > 0 else "fragile"

    return {
        "num_paths": len(path_returns),
        "profitable_paths_pct": round(profitable, 2),
        "return_p5": round(percentile(path_returns, 0.05), 2),
        "return_p50": round(percentile(path_returns, 0.5), 2),
        "return_p95": round(percentile(path_returns, 0.95), 2),
        "sharpe_p5": round(percentile(path_sharpes, 0.05), 2),
        "sharpe_p50": round(percentile(path_sharpes, 0.5), 2),
        "sharpe_p95": round(percentile(path_sharpes, 0.95), 2),
        "verdict": verdict,
        "paths": [
            {"return_pct": round(ret, 2), "sharpe": round(sh, 2)}
            for ret, sh in zip(path_returns, path_sharpes)
        ],
    }
