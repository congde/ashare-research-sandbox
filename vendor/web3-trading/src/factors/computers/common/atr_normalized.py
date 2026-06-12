"""ATR波动归一化 — 为其他因子提供动态阈值基准。"""
from __future__ import annotations

from typing import ClassVar, List

import numpy as np

from ...base import BaseFactorComputer
from ...context import FactorContext
from ...enums import FactorCategory, FactorTier, SignalDirection
from ...models import FactorResult
from .._utils import atr, get_kline_column, sma


class ATRNormalizedComputer(BaseFactorComputer):
    factor_name: ClassVar[str] = "atr_normalized"
    category: ClassVar[FactorCategory] = FactorCategory.TECHNICAL
    display_name: ClassVar[str] = "ATR波动归一化"
    description: ClassVar[str] = "ATR/收盘价的归一化波动率，为其他因子提供动态阈值。"
    requires_data: ClassVar[List[str]] = ["kline"]

    async def compute(self, ctx: FactorContext) -> FactorResult:
        klines = ctx.data.get("kline", {})
        high = get_kline_column(klines, "1h", "high")
        low = get_kline_column(klines, "1h", "low")
        close = get_kline_column(klines, "1h", "close")

        if high is None:
            high = get_kline_column(klines, "4h", "high")
            low = get_kline_column(klines, "4h", "low")
            close = get_kline_column(klines, "4h", "close")

        if close is None or len(close) < 35:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "K线数据不足。"),
            )

        a = atr(high, low, close, 14)
        atr_pct = a / close * 100.0

        current_atr_pct = float(atr_pct[-1])
        if current_atr_pct != current_atr_pct:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "ATR数据不足。"),
            )

        valid = atr_pct[~np.isnan(atr_pct)]
        atr_ma = sma(valid, 20)
        current_ma = float(atr_ma[-1]) if len(atr_ma) > 0 and atr_ma[-1] == atr_ma[-1] else current_atr_pct
        atr_ratio = current_atr_pct / max(current_ma, 1e-10)

        if atr_ratio > 1.5:
            action = "波动率膨胀，建议收紧止损。"
        elif atr_ratio < 0.5:
            action = "波动率收缩，可放宽止损。"
        else:
            action = "波动率正常范围。"

        evidence = [
            self._evidence(
                data_point=f"ATR%={current_atr_pct:.3f}%, ATR比={atr_ratio:.2f}",
                interpretation=f"波动率{'膨胀' if atr_ratio > 1.2 else '收缩' if atr_ratio < 0.8 else '正常'}",
                implication="ATR比率为突破类因子提供自适应阈值基准",
                confidence=0.6,
            ),
        ]

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=SignalDirection.NEUTRAL,
            normalized_score=0.0,
            raw_value=float(atr_ratio),
            confidence=0.50,
            data_freshness_ms=0, data_completeness=1.0, weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"atr_pct": current_atr_pct, "atr_ratio": float(atr_ratio)},
                evidence,
                f"ATR归一化: {current_atr_pct:.3f}%, 比率={atr_ratio:.2f}。{action}",
                action,
                limitations=["ATR归一化为辅助指标，不产生独立交易信号"],
            ),
        )
