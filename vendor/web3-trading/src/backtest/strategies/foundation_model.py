# -*- coding: utf-8 -*-
"""Foundation Model Prediction Strategy — time-series model forecasting."""
from __future__ import annotations

import importlib
import logging
from typing import Any, Dict, List, Optional

from backtest.models import Signal
from backtest.indicators import IndicatorSeries
from backtest.strategies.base import Strategy

logger = logging.getLogger(__name__)


def _check_chronos() -> bool:
    try:
        return importlib.util.find_spec("chronos") is not None
    except Exception:
        return False


class FoundationModelStrategy(Strategy):
    name = "foundation_model"
    display_name = "基础模型预测策略"

    def __init__(self):
        self._predictions: Dict[int, float] = {}

    def prepare(self, candles: List[Dict], params: Dict[str, Any]) -> None:
        import numpy as np

        closes = np.array([c["close"] for c in candles], dtype=float)
        backend = params.get("model_backend", "ar")
        ctx_len = params.get("context_length", 64)
        min_ctx = max(20, ctx_len // 2)
        self._predictions = {}

        if backend == "chronos" and _check_chronos():
            self._batch_predict_chronos(closes, ctx_len, min_ctx, params)
        elif backend == "ema":
            self._batch_predict_ema(closes, ctx_len, min_ctx)
        else:
            self._batch_predict_ar(closes, ctx_len, min_ctx)

        logger.info(
            "FoundationModelStrategy.prepare: backend=%s, predictions=%d",
            backend, len(self._predictions),
        )

    def _batch_predict_ar(self, closes, ctx_len: int, min_ctx: int) -> None:
        import numpy as np

        n = len(closes)
        order = 5

        for i in range(min_ctx, n):
            window = closes[max(0, i - ctx_len): i + 1]
            wn = len(window)
            p = min(order, wn // 3)
            if wn < p + 2:
                self._predictions[i] = float(closes[i])
                continue
            X = np.column_stack([window[j: wn - p + j] for j in range(p)])
            y = window[p:]
            try:
                beta, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
                predicted = float(window[-p:] @ beta)
            except Exception:
                predicted = float(closes[i])
            self._predictions[i] = predicted

    def _batch_predict_ema(self, closes, ctx_len: int, min_ctx: int) -> None:
        import numpy as np

        n = len(closes)
        span = min(20, ctx_len // 3)
        alpha = 2.0 / (span + 1)

        for i in range(min_ctx, n):
            window = closes[max(0, i - ctx_len): i + 1]
            ema = window[0]
            for v in window[1:]:
                ema = alpha * v + (1 - alpha) * ema
            tail = window[-min(6, len(window)):]
            if len(tail) >= 2:
                rets = np.diff(tail) / tail[:-1]
                momentum = float(np.mean(rets))
            else:
                momentum = 0.0
            self._predictions[i] = ema * (1 + momentum)

    def _batch_predict_chronos(self, closes, ctx_len: int, min_ctx: int, params: Dict) -> None:
        import numpy as np

        torch = importlib.import_module("torch")
        ChronosPipeline = importlib.import_module("chronos").ChronosPipeline

        model_id = params.get("chronos_model", "amazon/chronos-t5-tiny")
        stride = params.get("predict_stride", 5)
        n = len(closes)

        pipeline = ChronosPipeline.from_pretrained(
            model_id, device_map="cpu", torch_dtype=torch.float32,
        )

        contexts = []
        indices = []
        for i in range(min_ctx, n, stride):
            ctx = closes[max(0, i - ctx_len): i + 1]
            contexts.append(torch.tensor(ctx, dtype=torch.float32))
            indices.append(i)

        batch_size = 32
        for b in range(0, len(contexts), batch_size):
            batch_ctx = contexts[b: b + batch_size]
            forecasts = pipeline.predict(batch_ctx, prediction_length=1, num_samples=20)
            for j, fc in enumerate(forecasts):
                pred = float(fc.median(dim=0).values[0])
                idx = indices[b + j]
                for s in range(stride):
                    fill_idx = idx + s
                    if fill_idx < n:
                        self._predictions[fill_idx] = pred

    def generate_signal(
        self,
        candles: List[Dict],
        idx: int,
        params: Dict[str, Any],
        indicators: Optional[IndicatorSeries] = None,
    ) -> Signal:
        pred = self._predictions.get(idx)
        if pred is None:
            return Signal(action="WAIT", score=0)

        close = candles[idx]["close"]
        if close == 0:
            return Signal(action="WAIT", score=0)

        change_pct = (pred - close) / close * 100
        threshold = params.get("change_threshold", 0.3)

        score = change_pct / max(threshold, 0.01) * 50
        score = max(-100.0, min(100.0, score))

        entry_threshold = params.get("entry_threshold", 25)
        if score >= entry_threshold:
            action = "LONG"
        elif score >= 10:
            action = "WEAK_LONG"
        elif score <= -entry_threshold:
            action = "SHORT"
        elif score <= -10:
            action = "WEAK_SHORT"
        else:
            action = "WAIT"

        return Signal(action=action, score=score)

    def default_params(self) -> Dict[str, Any]:
        return {
            "model_backend": "ar",
            "context_length": 64,
            "change_threshold": 0.3,
            "entry_threshold": 25,
        }

    def param_grid(self) -> Dict[str, List[Any]]:
        return {
            "context_length": [32, 64, 128],
            "change_threshold": [0.1, 0.2, 0.3, 0.5],
            "entry_threshold": [15, 20, 25, 30],
        }

    def is_incremental(self) -> bool:
        return False  # uses prepare() with batch predictions
