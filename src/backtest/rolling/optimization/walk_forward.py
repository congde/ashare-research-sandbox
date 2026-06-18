# -*- coding: utf-8 -*-
"""Walk-forward parameter optimization on the rolling backtest engine."""

from __future__ import annotations

import itertools
import random
from collections import Counter
from typing import Any, Dict, List

from backtest.rolling.engine import run_backtest
from backtest.rolling.metrics import compute_metrics, compute_sharpe
from backtest.rolling.models import BacktestConfig, WalkForwardResult
from backtest.rolling.strategies.base import Strategy


def walk_forward_optimize(
    candles: List[Dict],
    strategy: Strategy,
    *,
    num_windows: int = 3,
    stop_loss_pct: float = 3.0,
    take_profit_pct: float = 5.0,
    commission_pct: float = 0.1,
    kline_type: str = "1day",
    min_context: int = 20,
    early_stop_threshold: float = -2.0,
    max_combos: int = 500,
) -> WalkForwardResult:
    """Fit params on train slice, validate on the next OOS slice per window."""
    grid = strategy.param_grid()
    default = strategy.default_params()
    if not grid:
        return WalkForwardResult(
            best_params=default,
            in_sample_sharpe=0.0,
            out_of_sample_sharpe=0.0,
            out_of_sample_return=0.0,
            num_windows=0,
            window_results=[],
        )

    n = len(candles)
    test_size = max(min_context + 5, n // (num_windows + 1))
    min_train = max(min_context + 10, test_size)

    if n < min_train + test_size:
        return WalkForwardResult(
            best_params=default,
            in_sample_sharpe=0.0,
            out_of_sample_sharpe=0.0,
            out_of_sample_return=0.0,
            num_windows=0,
            window_results=[],
        )

    keys = list(grid.keys())
    values = list(grid.values())
    combinations = list(itertools.product(*values))
    if len(combinations) > max_combos:
        combinations = random.Random(42).sample(combinations, max_combos)
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
        half_train = len(train_candles) // 2

        best_sharpe = -999.0
        best_p = dict(default)

        for partial in param_dicts:
            merged = {**default, **partial}

            if half_train >= min_context and early_stop_threshold is not None:
                config_half = BacktestConfig(
                    min_context=min_context,
                    stop_loss_pct=stop_loss_pct,
                    take_profit_pct=take_profit_pct,
                    commission_pct=commission_pct,
                    kline_type=kline_type,
                )
                trades_half, _, _ = run_backtest(
                    train_candles[:half_train], strategy, merged, config_half,
                )
                if trades_half:
                    half_sharpe = compute_sharpe([t.pnl_pct for t in trades_half], kline_type)
                    if half_sharpe < early_stop_threshold:
                        continue

            config_train = BacktestConfig(
                min_context=min_context,
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
                commission_pct=commission_pct,
                kline_type=kline_type,
            )
            trades, equity, _ = run_backtest(train_candles, strategy, merged, config_train)
            if not trades:
                continue
            result = compute_metrics(
                trades=trades,
                equity_curve=equity,
                candles=train_candles,
                symbol="",
                kline_type=kline_type,
                strategy_name=strategy.display_name,
            )
            if result.sharpe_ratio > best_sharpe:
                best_sharpe = result.sharpe_ratio
                best_p = merged

        config_oos = BacktestConfig(
            min_context=min_context,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            commission_pct=commission_pct,
            start_from=train_end,
            kline_type=kline_type,
        )
        oos_trades, oos_equity, _ = run_backtest(full_candles, strategy, best_p, config_oos)
        oos_result = compute_metrics(
            trades=oos_trades,
            equity_curve=oos_equity,
            candles=full_candles,
            symbol="",
            kline_type=kline_type,
            strategy_name=strategy.display_name,
        )

        oos_sharpes.append(oos_result.sharpe_ratio)
        oos_returns.append(oos_result.total_return_pct)
        for key in keys:
            best_params_votes[key].append(best_p.get(key))

        window_results.append(
            {
                "window": w + 1,
                "trainSize": train_end,
                "testSize": test_end - train_end,
                "inSampleSharpe": round(best_sharpe, 2),
                "outOfSampleSharpe": round(oos_result.sharpe_ratio, 2),
                "outOfSampleReturn": round(oos_result.total_return_pct, 2),
                "bestParams": {key: best_p.get(key) for key in keys},
            }
        )

    final_params = dict(default)
    for key in keys:
        votes = best_params_votes.get(key, [])
        if votes:
            final_params[key] = Counter(votes).most_common(1)[0][0]

    avg_is = (
        sum(row["inSampleSharpe"] for row in window_results) / len(window_results)
        if window_results
        else 0.0
    )
    avg_oos_sharpe = sum(oos_sharpes) / len(oos_sharpes) if oos_sharpes else 0.0
    avg_oos_return = sum(oos_returns) / len(oos_returns) if oos_returns else 0.0

    return WalkForwardResult(
        best_params=final_params,
        in_sample_sharpe=round(avg_is, 2),
        out_of_sample_sharpe=round(avg_oos_sharpe, 2),
        out_of_sample_return=round(avg_oos_return, 2),
        num_windows=len(window_results),
        window_results=window_results,
    )
