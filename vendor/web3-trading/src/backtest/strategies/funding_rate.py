# -*- coding: utf-8 -*-
"""
Funding Rate Arbitrage Strategy — Perpetual Contract specific.

Exploits funding rate imbalances in perpetual futures:
- When funding rate is highly positive (longs pay shorts) → SHORT
  (collect funding while expecting mean reversion)
- When funding rate is highly negative (shorts pay longs) → LONG
  (collect funding while expecting mean reversion)

This strategy is unique to crypto perpetual contracts and has no
traditional finance equivalent.

Note: Actual funding rate data should be passed via candle metadata
or a separate data feed. This implementation uses price momentum as
a proxy for funding rate direction when actual data is unavailable.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backtest.models import Signal
from backtest.indicators import IndicatorSeries
from backtest.strategies.base import Strategy


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
        score_base = params.get("score_base", 50)

        if idx < max(lookback, momentum_period) + 1:
            return Signal(action="WAIT", score=0)

        # --- Try to use actual funding rate from candle metadata ---
        funding_rate = candles[idx].get("fundingRate", None)

        if funding_rate is not None:
            return self._signal_from_funding(
                funding_rate, funding_threshold, score_base, candles, idx, params,
            )

        # --- Proxy: estimate funding direction from price momentum ---
        return self._signal_from_momentum_proxy(
            candles, idx, params, indicators,
        )

    def _signal_from_funding(
        self,
        funding_rate: float,
        threshold: float,
        score_base: float,
        candles: List[Dict],
        idx: int,
        params: Dict[str, Any],
    ) -> Signal:
        """Generate signal from actual funding rate data."""
        # Extreme positive funding → market overleveraged long → short
        if funding_rate > threshold:
            intensity = min((funding_rate - threshold) / threshold, 2.0)
            score = score_base + intensity * 20
            return Signal(action="SHORT", score=-min(score, 85))

        # Extreme negative funding → market overleveraged short → long
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
        """
        Proxy strategy when funding rate data is unavailable.

        Uses price momentum + open interest proxy (volume divergence)
        to estimate funding rate direction:
        - Strong upward momentum + increasing volume → positive funding → short
        - Strong downward momentum + increasing volume → negative funding → long
        """
        momentum_period = params.get("momentum_period", 8)
        lookback = params.get("lookback", 24)
        score_base = params.get("score_base", 50)
        momentum_threshold = params.get("momentum_threshold", 3.0)

        # Price momentum (% change over momentum_period)
        current = candles[idx]["close"]
        past = candles[idx - momentum_period]["close"]
        if past <= 0:
            return Signal(action="WAIT", score=0)
        momentum_pct = (current - past) / past * 100

        # Volume trend (increasing = more leveraged positions)
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

        # RSI as overbought/oversold confirmation
        rsi_val = None
        if indicators and idx < len(indicators.rsi):
            rsi_val = indicators.rsi[idx]

        # --- Signal logic ---
        # Strong up momentum + volume expansion → overleveraged longs → short
        if momentum_pct > momentum_threshold and vol_expansion > 1.3:
            score = score_base
            if rsi_val and rsi_val > 70:
                score += 15  # RSI confirms overbought
            score += min(momentum_pct - momentum_threshold, 10) * 3
            return Signal(action="SHORT", score=-min(score, 80))

        # Strong down momentum + volume expansion → overleveraged shorts → long
        if momentum_pct < -momentum_threshold and vol_expansion > 1.3:
            score = score_base
            if rsi_val and rsi_val < 30:
                score += 15  # RSI confirms oversold
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