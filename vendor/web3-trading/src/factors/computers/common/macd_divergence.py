"""MACD背离 — 价格与MACD柱的方向背离检测。"""
from __future__ import annotations

from typing import ClassVar, List

import numpy as np

from ...base import BaseFactorComputer
from ...context import FactorContext
from ...enums import FactorCategory, FactorTier, SignalDirection
from ...models import FactorResult
from .._utils import get_kline_column, macd


class MACDDivergenceComputer(BaseFactorComputer):
    factor_name: ClassVar[str] = "macd_divergence"
    category: ClassVar[FactorCategory] = FactorCategory.TECHNICAL
    display_name: ClassVar[str] = "MACD背离"
    description: ClassVar[str] = "价格与MACD柱的顶/底背离检测，反转信号。"
    requires_data: ClassVar[List[str]] = ["kline"]

    _LOOKBACK = 30

    async def compute(self, ctx: FactorContext) -> FactorResult:
        klines = ctx.data.get("kline", {})
        close_1d = get_kline_column(klines, "1d", "close")
        if close_1d is None:
            close_1d = get_kline_column(klines, "4h", "close")
        if close_1d is None or len(close_1d) < self._LOOKBACK + 26:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "K线数据不足。"),
            )

        _, _, hist = macd(close_1d)

        window = min(self._LOOKBACK, len(close_1d) - 1)
        recent_close = close_1d[-window:]
        recent_hist = hist[-window:]

        if np.all(np.isnan(recent_hist)):
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "MACD数据不足（全NaN）。"),
            )

        price_high_idx = int(np.argmax(recent_close))
        price_low_idx = int(np.argmin(recent_close))
        hist_high_idx = int(np.nanargmax(recent_hist))
        hist_low_idx = int(np.nanargmin(recent_hist))

        bearish_div = price_high_idx > len(recent_close) // 2 and hist_high_idx < price_high_idx
        bullish_div = price_low_idx > len(recent_close) // 2 and hist_low_idx < price_low_idx

        evidence = []
        if bearish_div:
            evidence.append(self._evidence(
                data_point=f"价格高点位置={price_high_idx}, MACD柱高点位置={hist_high_idx}",
                interpretation="顶背离：价格创新高但MACD柱未跟随，上涨动能衰竭",
                implication="反转下跌概率高，应止盈或做空",
                confidence=0.85,
            ))
        if bullish_div:
            evidence.append(self._evidence(
                data_point=f"价格低点位置={price_low_idx}, MACD柱低点位置={hist_low_idx}",
                interpretation="底背离：价格创新低但MACD柱未跟随，下跌动能衰竭",
                implication="反转上涨概率高，应抄底做多",
                confidence=0.85,
            ))

        if bearish_div and not bullish_div:
            clamped = -0.7
            direction = SignalDirection.STRONG_BEARISH
            action = "顶背离确认，强烈看跌反转。"
        elif bullish_div and not bearish_div:
            clamped = 0.7
            direction = SignalDirection.STRONG_BULLISH
            action = "底背离确认，强烈看涨反转。"
        elif bearish_div and bullish_div:
            clamped = 0.0
            direction = SignalDirection.NEUTRAL
            action = "顶底背离共存，方向不明，观望。"
        else:
            hist_last = float(hist[-1]) if not np.isnan(hist[-1]) else 0.0
            clamped = max(-1.0, min(1.0, hist_last / 100.0))
            if clamped > 0.1:
                direction = SignalDirection.BULLISH
                action = "MACD柱为正，趋势偏多。"
            elif clamped < -0.1:
                direction = SignalDirection.BEARISH
                action = "MACD柱为负，趋势偏空。"
            else:
                direction = SignalDirection.NEUTRAL
                action = "无背离信号，观望。"

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=1.0 if bullish_div else (-1.0 if bearish_div else 0.0),
            confidence=0.85 if (bullish_div or bearish_div) else 0.40,
            data_freshness_ms=0, data_completeness=1.0, weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"bearish_divergence": bearish_div, "bullish_divergence": bullish_div},
                evidence,
                f"MACD背离: {'顶背离' if bearish_div else ''}{'底背离' if bullish_div else ''}{'无' if not (bearish_div or bullish_div) else ''}。",
                action,
                limitations=["背离可能持续较长时间才反转，需结合其他信号确认"],
            ),
        )
