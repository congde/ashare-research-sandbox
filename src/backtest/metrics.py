from __future__ import annotations

import math


def sharpe_ratio(
    equity_values: list[float],
    *,
    periods_per_year: int = 365,
) -> float:
    """Annualized Sharpe from equity curve returns.

    Adapted from web3-trading ``compute_sharpe`` using daily bars
    (``sqrt(365)`` annualization).
    """
    if len(equity_values) < 2:
        return 0.0
    returns = [
        equity_values[index] / equity_values[index - 1] - 1
        for index in range(1, len(equity_values))
    ]
    if len(returns) < 2:
        return 0.0
    mean_r = sum(returns) / len(returns)
    variance = sum((value - mean_r) ** 2 for value in returns) / (len(returns) - 1)
    std_r = math.sqrt(variance) if variance > 0 else 0.0
    if std_r == 0:
        return 0.0
    return (mean_r / std_r) * math.sqrt(periods_per_year)
