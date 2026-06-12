# -*- coding: utf-8 -*-
"""
Walk-Forward Parameter Optimization with early stopping.

Improvements over the old backtest_strategies.walk_forward_optimize:
1. Early stopping — skip parameter combos that underperform after 50% of training
2. Proper metric computation using the new metrics module
3. Uses the new engine instead of the old run_backtest_with_strategy
"""

from __future__ import annotations

import itertools
import logging
import random
from collections import Counter
from typing import Any, Dict, List, Optional

from backtest.models import BacktestConfig, WalkForwardResult
from backtest.strategies.base import Strategy

logger = logging.getLogger(__name__)


def walk_forward_optimize(
    candles: List[Dict],
    strategy: Strategy,
    *,
    train_ratio: float = 0.7,
    num_windows: int = 3,
    stop_loss_pct: float = 3.0,
    take_profit_pct: float = 5.0,
    commission_pct: float = 0.1,
    kline_type: str = "1hour",
    early_stop_threshold: float = -2.0,
) -> WalkForwardResult:
    """Walk-forward optimization with early stopping.

    Architecture follows Claude Code's task system pattern — each window is
    an independent "task" that can be evaluated in isolation.
    """
    from backtest.engine import run_backtest
    from backtest.metrics import compute_metrics

    grid = strategy.param_grid()
    if not grid:
        return WalkForwardResult(
            best_params=strategy.default_params(),
            in_sample_sharpe=0.0, out_of_sample_sharpe=0.0,
            out_of_sample_return=0.0, num_windows=0, window_results=[],
        )

    n = len(candles)
    test_size = max(40, n // (num_windows + 1))
    min_train = max(60, test_size)

    if n < min_train + test_size:
        return WalkForwardResult(
            best_params=strategy.default_params(),
            in_sample_sharpe=0.0, out_of_sample_sharpe=0.0,
            out_of_sample_return=0.0, num_windows=0, window_results=[],
        )

    # Generate param combinations (capped at 500)
    keys = list(grid.keys())
    values = list(grid.values())
    combinations = list(itertools.product(*values))
    if len(combinations) > 500:
        rng = random.Random(42)
        combinations = rng.sample(combinations, 500)
    param_dicts = [dict(zip(keys, combo)) for combo in combinations]

    window_results: List[Dict[str, Any]] = []
    oos_sharpes: List[float] = []
    oos_returns: List[float] = []
    best_params_votes: Dict[str, list] = {k: [] for k in keys}

    for w in range(num_windows):
        test_end = n - (num_windows - 1 - w) * test_size
        train_end = test_end - test_size

        if train_end < min_train or test_end > n:
            continue

        train_candles = candles[:train_end]
        full_candles = candles[:test_end]

        # --- In-sample: find best params with early stopping ---
        best_sharpe = -999.0
        best_p = strategy.default_params()
        half_train = len(train_candles) // 2

        for p in param_dicts:
            merged = {**strategy.default_params(), **p}

            # Early stopping: test on first half of training data
            if half_train >= 80 and early_stop_threshold is not None:
                config_half = BacktestConfig(
                    stop_loss_pct=stop_loss_pct,
                    take_profit_pct=take_profit_pct,
                    commission_pct=commission_pct,
                    kline_type=kline_type,
                )
                trades_half, eq_half, _ = run_backtest(
                    train_candles[:half_train], strategy, merged, config_half,
                )
                if trades_half:
                    from backtest.metrics import compute_sharpe
                    half_sharpe = compute_sharpe(
                        [t.pnl_pct for t in trades_half], kline_type,
                    )
                    if half_sharpe < early_stop_threshold:
                        continue  # skip this combination

            # Full training evaluation
            config_train = BacktestConfig(
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
                commission_pct=commission_pct,
                kline_type=kline_type,
            )
            trades, eq, _ = run_backtest(train_candles, strategy, merged, config_train)
            if not trades:
                continue
            result = compute_metrics(trades, eq, train_candles, "", kline_type)
            if result.sharpe_ratio > best_sharpe:
                best_sharpe = result.sharpe_ratio
                best_p = merged

        # --- Out-of-sample: validate best params ---
        config_oos = BacktestConfig(
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            commission_pct=commission_pct,
            start_from=train_end,
            kline_type=kline_type,
        )
        oos_trades, oos_eq, _ = run_backtest(full_candles, strategy, best_p, config_oos)
        oos_result = compute_metrics(oos_trades, oos_eq, full_candles, "", kline_type)

        oos_sharpes.append(oos_result.sharpe_ratio)
        oos_returns.append(oos_result.total_return_pct)

        for k in keys:
            best_params_votes[k].append(best_p.get(k))

        window_results.append({
            "window": w + 1,
            "trainSize": train_end,
            "testSize": test_end - train_end,
            "inSampleSharpe": round(best_sharpe, 2),
            "outOfSampleSharpe": round(oos_result.sharpe_ratio, 2),
            "outOfSampleReturn": round(oos_result.total_return_pct, 2),
            "bestParams": {k: best_p.get(k) for k in keys},
        })

    # Aggregate: pick most common param value across windows (mode)
    final_params = dict(strategy.default_params())
    for k in keys:
        votes = best_params_votes.get(k, [])
        if votes:
            counter = Counter(votes)
            final_params[k] = counter.most_common(1)[0][0]

    avg_is_sharpe = sum(r["inSampleSharpe"] for r in window_results) / len(window_results) if window_results else 0
    avg_oos_sharpe = sum(oos_sharpes) / len(oos_sharpes) if oos_sharpes else 0
    avg_oos_return = sum(oos_returns) / len(oos_returns) if oos_returns else 0

    return WalkForwardResult(
        best_params=final_params,
        in_sample_sharpe=round(avg_is_sharpe, 2),
        out_of_sample_sharpe=round(avg_oos_sharpe, 2),
        out_of_sample_return=round(avg_oos_return, 2),
        num_windows=len(window_results),
        window_results=window_results,
    )
