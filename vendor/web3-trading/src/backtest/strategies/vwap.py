# -*- coding: utf-8 -*-
"""
VWAP Strategy — Volume Weighted Average Price.

Uses VWAP as dynamic support/resistance:
- Price crosses above VWAP with volume confirmation → LONG
- Price crosses below VWAP with volume confirmation → SHORT

Best suited for intraday (15min, 1hour) timeframes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backtest.models import Signal
from backtest.indicators import IndicatorSeries
from backtest.strategies.base import Strategy


class VWAPStrategy(Strategy):
    name = "vwap"
    display_name = "VWAP策略"

    def generate_signal(
        self,
        candles: List[Dict],
        idx: int,
        params: Dict[str, Any],
        indicators: Optional[IndicatorSeries] = None,
    ) -> Signal:
        lookback = params.get("vwap_period", 20)
        vol_threshold = params.get("volume_multiplier", 1.5)
        score_base = params.get("score_base", 55)

        if idx < lookback + 1:
            return Signal(action="WAIT", score=0)

        # --- Compute VWAP over lookback period ---
        total_pv = 0.0  # price * volume
        total_vol = 0.0
        for j in range(idx - lookback, idx + 1):
            typical_price = (
                candles[j]["high"] + candles[j]["low"] + candles[j]["close"]
            ) / 3
            vol = candles[j].get("volume", 0)
            total_pv += typical_price * vol
            total_vol += vol

        if total_vol <= 0:
            return Signal(action="WAIT", score=0)

        vwap = total_pv / total_vol
        current_close = candles[idx]["close"]
        prev_close = candles[idx - 1]["close"]

        # --- Volume confirmation ---
        recent_vols = [
            candles[j].get("volume", 0)
            for j in range(idx - lookback, idx)
        ]
        avg_vol = sum(recent_vols) / len(recent_vols) if recent_vols else 1
        current_vol = candles[idx].get("volume", 0)
        vol_ratio = current_vol / avg_vol if avg_vol > 0 else 0

        # --- Signal generation ---
        # Crossover above VWAP with volume
        if current_close > vwap and prev_close <= vwap and vol_ratio >= vol_threshold:
            # Distance from VWAP as score modifier
            dist_pct = (current_close - vwap) / vwap * 100
            score = min(score_base + dist_pct * 10, 90)
            return Signal(action="LONG", score=score)

        # Crossover below VWAP with volume
        if current_close < vwap and prev_close >= vwap and vol_ratio >= vol_threshold:
            dist_pct = (vwap - current_close) / vwap * 100
            score = min(score_base + dist_pct * 10, 90)
            return Signal(action="SHORT", score=-score)

        # Mean reversion: price far from VWAP without volume
        dev_pct = (current_close - vwap) / vwap * 100
        if abs(dev_pct) > 3 and vol_ratio < 0.8:
            # Expect reversion
            if dev_pct > 3:
                return Signal(action="SHORT", score=-min(30 + abs(dev_pct) * 5, 70))
            else:
                return Signal(action="LONG", score=min(30 + abs(dev_pct) * 5, 70))

        return Signal(action="WAIT", score=0)

    def default_params(self) -> Dict[str, Any]:
        return {
            "vwap_period": 20,
            "volume_multiplier": 1.5,
            "score_base": 55,
            "entry_threshold": 40,
        }

    def param_grid(self) -> Dict[str, List]:
        return {
            "vwap_period": [10, 15, 20, 30],
            "volume_multiplier": [1.2, 1.5, 2.0],
            "score_base": [45, 55, 65],
        }