"""Probabilistic and Deflated Sharpe Ratio (Bailey & López de Prado)."""

from __future__ import annotations

import math
from typing import Any


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Rational approximation for inverse standard normal CDF."""
    if p <= 0.0 or p >= 1.0:
        return 0.0
    if p < 0.5:
        return -_norm_ppf(1.0 - p)

    t = math.sqrt(-2.0 * math.log(1.0 - p))
    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308
    return t - (c0 + c1 * t + c2 * t * t) / (1.0 + d1 * t + d2 * t * t + d3 * t * t * t)


def _moments(values: list[float]) -> tuple[float, float, float]:
    if len(values) < 2:
        return 0.0, 0.0, 0.0
    mean = sum(values) / len(values)
    centered = [value - mean for value in values]
    variance = sum(item * item for item in centered) / (len(values) - 1)
    if variance <= 0:
        return mean, 0.0, 0.0
    std = math.sqrt(variance)
    skew = sum(item**3 for item in centered) / (len(values) * std**3)
    kurt = sum(item**4 for item in centered) / (len(values) * std**4)
    return mean, skew, kurt - 3.0


def probabilistic_sharpe_ratio(
    observed_sr: float,
    benchmark_sr: float,
    sample_length: int,
    *,
    skewness: float = 0.0,
    excess_kurtosis: float = 0.0,
) -> float:
    if sample_length < 2:
        return 0.0
    variance_sr = (
        1.0
        - skewness * observed_sr
        + (excess_kurtosis / 4.0) * (observed_sr**2)
    ) / (sample_length - 1)
    if variance_sr <= 0:
        variance_sr = 1e-12
    z = (observed_sr - benchmark_sr) * math.sqrt(sample_length - 1) / math.sqrt(variance_sr)
    return _norm_cdf(z)


def expected_max_sharpe(num_trials: int, variance_of_trials: float = 1.0) -> float:
    if num_trials <= 1:
        return 0.0
    euler = 0.5772156649
    z1 = _norm_ppf(1.0 - 1.0 / num_trials)
    z2 = _norm_ppf(1.0 - 1.0 / (num_trials * math.e))
    return ((1.0 - euler) * z1 + euler * z2) * math.sqrt(max(variance_of_trials, 1e-12))


def deflated_sharpe_ratio(
    observed_sr: float,
    sample_length: int,
    num_trials: int,
    *,
    skewness: float = 0.0,
    excess_kurtosis: float = 0.0,
    variance_of_trials: float = 1.0,
    benchmark_sr: float = 0.0,
) -> dict[str, float | bool | int]:
    psr = probabilistic_sharpe_ratio(
        observed_sr,
        benchmark_sr,
        sample_length,
        skewness=skewness,
        excess_kurtosis=excess_kurtosis,
    )
    e_max = expected_max_sharpe(num_trials, variance_of_trials)
    dsr = probabilistic_sharpe_ratio(
        observed_sr,
        e_max,
        sample_length,
        skewness=skewness,
        excess_kurtosis=excess_kurtosis,
    )
    return {
        "psr": round(psr, 4),
        "dsr": round(dsr, 4),
        "expected_max_sharpe": round(e_max, 4),
        "is_significant": dsr >= 0.95,
        "num_trials": max(1, num_trials),
    }


def audit_sharpe(
    trade_pnls: list[float],
    sharpe_ratio: float,
    *,
    num_trials: int,
    sharpe_variance: float = 1.0,
    kline_type: str = "1day",
) -> dict[str, Any]:
    _, skew, excess_kurt = _moments(trade_pnls)
    sample_length = max(2, len(trade_pnls))
    if kline_type == "1day":
        sample_length = max(sample_length, 252)
    payload = deflated_sharpe_ratio(
        sharpe_ratio,
        sample_length,
        max(1, num_trials),
        skewness=skew,
        excess_kurtosis=excess_kurt,
        variance_of_trials=max(sharpe_variance, 1e-6),
    )
    payload["skewness"] = round(skew, 4)
    payload["excess_kurtosis"] = round(excess_kurt, 4)
    return payload
