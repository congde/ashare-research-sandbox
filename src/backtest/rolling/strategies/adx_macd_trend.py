# -*- coding: utf-8 -*-
"""ADX + EMA stack + MACD histogram — rules adapted from vendor/Qbot (MIT).

Reference: vendor/Qbot/qbot/strategies/adx_strategy.py
  - EMA13 > EMA55 > EMA89 (bullish alignment)
  - ADX <= threshold and rising (trend forming, not yet strong)
  - MACD histogram rising
  - Hold ~3 bars then exit (via max_hold_bars engine override)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backtest.rolling.indicators import IndicatorSeries
from backtest.rolling.models import Signal
from backtest.rolling.strategies.base import Strategy


class ADXMacdTrendStrategy(Strategy):
    name = "adx_macd_trend"
    display_name = "ADX+MACD 趋势（Qbot）"

    def generate_signal(
        self,
        candles: List[Dict],
        idx: int,
        params: Dict[str, Any],
        indicators: Optional[IndicatorSeries] = None,
    ) -> Signal:
        if indicators is None or idx >= len(indicators.adx):
            return Signal(action="WAIT", score=0.0)

        ema1 = indicators.ema13[idx]
        ema2 = indicators.ema55[idx]
        ema3 = indicators.ema89[idx]
        adx_val = indicators.adx[idx]
        prev_adx = indicators.adx[idx - 1] if idx > 0 else None
        hist = indicators.macd_histogram[idx]
        prev_hist = indicators.macd_histogram[idx - 1] if idx > 0 else None

        if any(v is None for v in (ema1, ema2, ema3, adx_val, hist)):
            return Signal(action="WAIT", score=0.0)
        if prev_adx is None or prev_hist is None:
            return Signal(action="WAIT", score=0.0)

        adx_threshold = float(params.get("adx_threshold", 25))

        aligned = ema1 > ema2 > ema3
        adx_rising = adx_val <= adx_threshold and adx_val > prev_adx
        hist_rising = hist > prev_hist

        if aligned and adx_rising and hist_rising:
            strength = min(100.0, 40.0 + (adx_threshold - adx_val) + (hist - prev_hist) * 100)
            return Signal(action="LONG", score=strength)

        if not aligned:
            return Signal(action="WAIT", score=-20.0)

        return Signal(action="WAIT", score=0.0)

    def default_params(self) -> Dict[str, Any]:
        return {
            "adx_threshold": 25,
            "hold_bars": 3,
            "entry_threshold": 25,
        }

    def param_grid(self) -> Dict[str, List[Any]]:
        return {
            "adx_threshold": [20, 25, 30],
            "hold_bars": [3, 5],
            "entry_threshold": [20, 25, 30],
        }

    def backtest_config_overrides(self, params: Dict[str, Any]) -> Dict[str, Any]:
        hold = int(params.get("hold_bars", 3))
        if hold > 0:
            return {"max_hold_bars": hold}
        return {}
