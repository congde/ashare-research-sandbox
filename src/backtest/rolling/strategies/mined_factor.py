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
from factor_mining.stats import zscore_series


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
        if source in ("ml", "llm"):
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

        self._series = zscore_series(raw)

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


class MinedFactorLRStrategy(MinedFactorStrategy):
    """Mined factor strategy using Linear Regression."""
    name = "mined_factor_lr"
    display_name = "挖掘因子 - 线性回归"

    def prepare(self, candles: List[Dict], params: Dict[str, Any]) -> None:
        params_copy = dict(params)
        params_copy.setdefault("factor_source", "ml")
        params_copy.setdefault("label", self.display_name)
        super().prepare(candles, params_copy)


class MinedFactorRFStrategy(MinedFactorStrategy):
    """Mined factor strategy using Random Forest."""
    name = "mined_factor_rf"
    display_name = "挖掘因子 - 随机森林"

    def prepare(self, candles: List[Dict], params: Dict[str, Any]) -> None:
        params_copy = dict(params)
        params_copy.setdefault("factor_source", "ml")
        params_copy.setdefault("label", self.display_name)
        super().prepare(candles, params_copy)


class MinedFactorGBMStrategy(MinedFactorStrategy):
    """Mined factor strategy using Gradient Boosting."""
    name = "mined_factor_gbm"
    display_name = "挖掘因子 - 梯度提升"

    def prepare(self, candles: List[Dict], params: Dict[str, Any]) -> None:
        params_copy = dict(params)
        params_copy.setdefault("factor_source", "ml")
        params_copy.setdefault("label", self.display_name)
        super().prepare(candles, params_copy)


class MinedFactorNNStrategy(MinedFactorStrategy):
    """Mined factor strategy using Neural Network."""
    name = "mined_factor_nn"
    display_name = "挖掘因子 - 神经网络"

    def prepare(self, candles: List[Dict], params: Dict[str, Any]) -> None:
        params_copy = dict(params)
        params_copy.setdefault("factor_source", "ml")
        params_copy.setdefault("label", self.display_name)
        super().prepare(candles, params_copy)


class MinedFactorEnsembleStrategy(MinedFactorStrategy):
    """Mined factor strategy using Ensemble methods."""
    name = "mined_factor_ensemble"
    display_name = "挖掘因子 - 集成模型"

    def prepare(self, candles: List[Dict], params: Dict[str, Any]) -> None:
        params_copy = dict(params)
        params_copy.setdefault("factor_source", "ml")
        params_copy.setdefault("label", self.display_name)
        super().prepare(candles, params_copy)


class MinedFactorBayesStrategy(MinedFactorStrategy):
    """Mined factor strategy using Bayesian methods."""
    name = "mined_factor_bayes"
    display_name = "挖掘因子 - 贝叶斯模型"

    def prepare(self, candles: List[Dict], params: Dict[str, Any]) -> None:
        params_copy = dict(params)
        params_copy.setdefault("factor_source", "ml")
        params_copy.setdefault("label", self.display_name)
        super().prepare(candles, params_copy)


class MinedFactorKNNStrategy(MinedFactorStrategy):
    """Mined factor strategy using KNN."""
    name = "mined_factor_knn_factor"
    display_name = "挖掘因子 - KNN 模型"

    def prepare(self, candles: List[Dict], params: Dict[str, Any]) -> None:
        params_copy = dict(params)
        params_copy.setdefault("factor_source", "ml")
        params_copy.setdefault("label", self.display_name)
        super().prepare(candles, params_copy)


class MinedFactorGPStrategy(MinedFactorStrategy):
    """Mined factor strategy using Genetic Programming."""
    name = "mined_factor_gp"
    display_name = "挖掘因子 - 遗传规划"

    def prepare(self, candles: List[Dict], params: Dict[str, Any]) -> None:
        params_copy = dict(params)
        params_copy.setdefault("factor_source", "gp")
        params_copy.setdefault("label", self.display_name)
        super().prepare(candles, params_copy)


class MinedFactorLLMStrategy(MinedFactorStrategy):
    """Mined factor strategy using LLM-generated factors."""
    name = "mined_factor_llm"
    display_name = "挖掘因子 - LLM 智能因子"

    def prepare(self, candles: List[Dict], params: Dict[str, Any]) -> None:
        params_copy = dict(params)
        params_copy.setdefault("factor_source", "llm")
        params_copy.setdefault("label", self.display_name)
        super().prepare(candles, params_copy)

    def is_incremental(self) -> bool:
        return False
