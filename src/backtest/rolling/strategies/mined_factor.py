# -*- coding: utf-8 -*-
"""Backtest strategy driven by GP / ML mined factor scores."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backtest.rolling.indicators import IndicatorSeries
from backtest.rolling.models import Signal
from backtest.rolling.strategies.base import Strategy
from factor_mining.expressions import eval_series
from factor_mining.serialize import expr_from_dict
from factor_mining.features import build_feature_matrix
from factor_mining.ml import _combine_linear, _normalize_features


def _zscore_series(values: list[float | None]) -> list[float | None]:
    nums = [v for v in values if v is not None]
    if len(nums) < 5:
        return values
    mean = sum(nums) / len(nums)
    var = sum((v - mean) ** 2 for v in nums) / (len(nums) - 1)
    std = var ** 0.5
    if std < 1e-9:
        return values
    out: list[float | None] = []
    for value in values:
        out.append(None if value is None else (value - mean) / std)
    return out


class MinedFactorStrategy(Strategy):
    name = "mined_factor"
    display_name = "挖掘因子策略"

    def __init__(self) -> None:
        self._series: list[float | None] = []
        self._label = "挖掘因子"

    def prepare(self, candles: List[Dict], params: Dict[str, Any]) -> None:
        self._label = str(params.get("label") or self.display_name)
        features, _, _ = build_feature_matrix(candles, horizon=int(params.get("horizon", 1)))

        source = params.get("factor_source", "gp")
        if source == "ml":
            normalized = _normalize_features(features)
            weights = params.get("weights") or {}
            raw = _combine_linear(normalized, weights)
        else:
            expr_payload = params.get("expr")
            if not expr_payload:
                self._series = [None] * len(candles)
                return
            expr = expr_from_dict(expr_payload) if isinstance(expr_payload, dict) else expr_payload
            raw = eval_series(expr, features)

        self._series = _zscore_series(raw)

    def generate_signal(
        self,
        candles: List[Dict],
        idx: int,
        params: Dict[str, Any],
        indicators: Optional[IndicatorSeries] = None,
    ) -> Signal:
        if idx >= len(self._series):
            return Signal(action="WAIT", score=0)

        value = self._series[idx]
        if value is None:
            return Signal(action="WAIT", score=0)

        threshold = float(params.get("entry_threshold", 0.5))
        score = max(-100.0, min(100.0, value * 50.0))

        if value >= threshold:
            action = "LONG" if value >= threshold * 1.5 else "WEAK_LONG"
        elif value <= -threshold:
            action = "SHORT" if value <= -threshold * 1.5 else "WEAK_SHORT"
        else:
            action = "WAIT"

        return Signal(action=action, score=score)

    def default_params(self) -> Dict[str, Any]:
        return {
            "factor_source": "gp",
            "expr": None,
            "weights": {},
            "label": self.display_name,
            "horizon": 1,
            "entry_threshold": 0.5,
        }

    def is_incremental(self) -> bool:
        return False
