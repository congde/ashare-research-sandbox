"""Simplified Probability of Backtest Overfitting (block CSCV)."""

from __future__ import annotations

import itertools
import random
from typing import Any

from backtest.rolling.engine import run_backtest
from backtest.rolling.metrics import compute_metrics
from backtest.rolling.models import BacktestConfig
from backtest.rolling.strategies.base import Strategy


def _param_candidates(strategy: Strategy, max_candidates: int = 12) -> list[dict[str, Any]]:
    grid = strategy.param_grid()
    default = strategy.default_params()
    if not grid:
        return [dict(default)]

    keys = list(grid.keys())
    values = list(grid.values())
    combos = [dict(zip(keys, combo)) for combo in itertools.product(*values)]
    if len(combos) > max_candidates:
        combos = random.Random(7).sample(combos, max_candidates)
    return [{**default, **partial} for partial in combos]


def _score_params(
    candles: list[dict[str, Any]],
    strategy: Strategy,
    params: dict[str, Any],
    config: BacktestConfig,
) -> float:
    trades, equity, _ = run_backtest(candles, strategy, params, config)
    if not trades:
        return -999.0
    metrics = compute_metrics(
        trades=trades,
        equity_curve=equity,
        candles=candles,
        symbol="",
        kline_type=config.kline_type,
        strategy_name=strategy.display_name,
    )
    return metrics.sharpe_ratio


def probability_of_backtest_overfitting(
    candles: list[dict[str, Any]],
    strategy: Strategy,
    *,
    num_blocks: int = 6,
    config: BacktestConfig,
    max_candidates: int = 12,
) -> dict[str, Any]:
    """Fraction of train/test splits where IS-best params fail OOS."""
    candidates = _param_candidates(strategy, max_candidates=max_candidates)
    n = len(candles)
    blocks = max(4, min(8, num_blocks))
    block_size = max(10, n // blocks)
    if block_size * blocks > n:
        blocks = max(2, n // block_size)
    if blocks < 4:
        return {
            "pbo": 0.0,
            "num_splits": 0,
            "verdict": "insufficient_data",
            "overfit_risk": False,
        }

    block_ids = list(range(blocks))
    half = blocks // 2
    splits = list(itertools.combinations(block_ids, half))
    if len(splits) > 20:
        splits = random.Random(11).sample(splits, 20)

    failures = 0
    evaluated = 0
    for train_blocks in splits:
        test_blocks = [block for block in block_ids if block not in train_blocks]
        train_idx = []
        test_idx = []
        for block in train_blocks:
            start = block * block_size
            end = min(n, (block + 1) * block_size)
            train_idx.extend(range(start, end))
        for block in test_blocks:
            start = block * block_size
            end = min(n, (block + 1) * block_size)
            test_idx.extend(range(start, end))
        if len(train_idx) < config.min_context + 5 or len(test_idx) < config.min_context + 5:
            continue

        train_candles = [candles[i] for i in train_idx]
        test_candles = [candles[i] for i in test_idx]

        best_is = max(
            candidates,
            key=lambda params: _score_params(train_candles, strategy, params, config),
        )
        is_winner = _score_params(train_candles, strategy, best_is, config)
        oos_winner_score = max(
            _score_params(test_candles, strategy, params, config) for params in candidates
        )
        oos_is_choice = _score_params(test_candles, strategy, best_is, config)

        evaluated += 1
        if oos_is_choice < oos_winner_score - 1e-6 or is_winner > oos_is_choice + 0.5:
            failures += 1

    pbo = failures / evaluated if evaluated else 0.0
    if pbo < 0.25:
        verdict = "strong"
    elif pbo <= 0.5:
        verdict = "uncertain"
    else:
        verdict = "overfit"

    return {
        "pbo": round(pbo, 4),
        "num_splits": evaluated,
        "failures": failures,
        "verdict": verdict,
        "overfit_risk": pbo > 0.5,
    }
