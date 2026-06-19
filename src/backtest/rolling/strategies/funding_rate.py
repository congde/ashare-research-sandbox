# -*- coding: utf-8 -*-
"""Funding rate strategy — perpetual contract teaching port."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backtest.rolling.indicators import IndicatorSeries
from backtest.rolling.models import Signal
from backtest.rolling.strategies.base import Strategy


class FundingRateStrategy(Strategy):
    name = "funding_rate"
    display_name = "资金费率套利策略"

    def generate_signal(
        self,
        candles: List[Dict],
        idx: int,
        params: Dict[str, Any],
        indicators: Optional[IndicatorSeries] = None,
    ) -> Signal:
        lookback = params.get("lookback", 24)
        funding_threshold = params.get("funding_threshold", 0.05)
        momentum_period = params.get("momentum_period", 8)

        if idx < max(lookback, momentum_period) + 1:
            return Signal(action="WAIT", score=0)

        funding_rate = candles[idx].get("fundingRate")
        if funding_rate is not None:
            return self._signal_from_funding(
                float(funding_rate),
                funding_threshold,
                params.get("score_base", 50),
            )
        return self._signal_from_momentum_proxy(candles, idx, params, indicators)

    def _signal_from_funding(
        self,
        funding_rate: float,
        threshold: float,
        score_base: float,
    ) -> Signal:
        if funding_rate > threshold:
            intensity = min((funding_rate - threshold) / threshold, 2.0)
            score = score_base + intensity * 20
            return Signal(action="SHORT", score=-min(score, 85))
        if funding_rate < -threshold:
            intensity = min((abs(funding_rate) - threshold) / threshold, 2.0)
            score = score_base + intensity * 20
            return Signal(action="LONG", score=min(score, 85))
        return Signal(action="WAIT", score=0)

    def _signal_from_momentum_proxy(
        self,
        candles: List[Dict],
        idx: int,
        params: Dict[str, Any],
        indicators: Optional[IndicatorSeries] = None,
    ) -> Signal:
        momentum_period = params.get("momentum_period", 8)
        lookback = params.get("lookback", 24)
        score_base = params.get("score_base", 50)
        momentum_threshold = params.get("momentum_threshold", 3.0)

        current = candles[idx]["close"]
        past = candles[idx - momentum_period]["close"]
        if past <= 0:
            return Signal(action="WAIT", score=0)
        momentum_pct = (current - past) / past * 100

        recent_vols = [
            candles[j].get("volume", 0)
            for j in range(idx - momentum_period, idx + 1)
        ]
        older_vols = [
            candles[j].get("volume", 0)
            for j in range(idx - lookback, idx - momentum_period)
        ]
        avg_recent = sum(recent_vols) / len(recent_vols) if recent_vols else 1
        avg_older = sum(older_vols) / len(older_vols) if older_vols else 1
        vol_expansion = avg_recent / avg_older if avg_older > 0 else 1

        rsi_val = None
        if indicators and idx < len(indicators.rsi):
            rsi_val = indicators.rsi[idx]

        if momentum_pct > momentum_threshold and vol_expansion > 1.3:
            score = score_base
            if rsi_val and rsi_val > 70:
                score += 15
            score += min(momentum_pct - momentum_threshold, 10) * 3
            return Signal(action="SHORT", score=-min(score, 80))

        if momentum_pct < -momentum_threshold and vol_expansion > 1.3:
            score = score_base
            if rsi_val and rsi_val < 30:
                score += 15
            score += min(abs(momentum_pct) - momentum_threshold, 10) * 3
            return Signal(action="LONG", score=min(score, 80))

        return Signal(action="WAIT", score=0)

    def default_params(self) -> Dict[str, Any]:
        return {
            "lookback": 24,
            "funding_threshold": 0.05,
            "momentum_period": 8,
            "momentum_threshold": 3.0,
            "score_base": 50,
            "entry_threshold": 35,
        }

    def param_grid(self) -> Dict[str, List]:
        return {
            "lookback": [12, 24, 48],
            "momentum_period": [4, 8, 12],
            "momentum_threshold": [2.0, 3.0, 5.0],
            "score_base": [40, 50, 60],
        }
