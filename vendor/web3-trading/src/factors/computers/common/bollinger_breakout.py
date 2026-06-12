"""布林带突破 — 带宽收缩/扩张 + %B位置，识别趋势启动。"""
from __future__ import annotations

from typing import ClassVar, List

import numpy as np

from ...base import BaseFactorComputer
from ...context import FactorContext
from ...enums import FactorCategory, FactorTier, SignalDirection
from ...models import FactorResult
from .._utils import bollinger_bands, get_kline_column


class BollingerBreakoutComputer(BaseFactorComputer):
    factor_name: ClassVar[str] = "bollinger_breakout"
    category: ClassVar[FactorCategory] = FactorCategory.TECHNICAL
    display_name: ClassVar[str] = "布林带突破"
    description: ClassVar[str] = "BOLL带宽收缩/扩张+%B位置，识别趋势启动和加速。"
    requires_data: ClassVar[List[str]] = ["kline"]

    async def compute(self, ctx: FactorContext) -> FactorResult:
        klines = ctx.data.get("kline", {})
        close = get_kline_column(klines, "1h", "close")
        if close is None:
            close = get_kline_column(klines, "4h", "close")

        if close is None or len(close) < 30:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "K线数据不足。"),
            )

        middle, upper, lower = bollinger_bands(close, 20, 2.0)
        bw = (upper - lower) / np.where(middle == 0, 1e-10, middle)
        pct_b = (close - lower) / np.where((upper - lower) == 0, 1e-10, upper - lower)

        last = -1
        current_bw = float(bw[last])
        current_pct_b = float(pct_b[last])
        current_close = float(close[last])

        if current_bw != current_bw or current_pct_b != current_pct_b:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "布林带数据不足。"),
            )

        valid_bw = bw[~np.isnan(bw)]
        bw_pct = float(np.sum(bw[last] >= valid_bw) / max(len(valid_bw), 1))
        bw_pct = max(0.0, min(1.0, bw_pct))

        if bw_pct < 0.15 and current_pct_b > 0.8:
            direction = SignalDirection.STRONG_BULLISH
            clamped = 0.7
            action = "布林带收缩至极值后向上突破，多头启动。"
        elif bw_pct < 0.15 and current_pct_b < 0.2:
            direction = SignalDirection.STRONG_BEARISH
            clamped = -0.7
            action = "布林带收缩至极值后向下突破，空头启动。"
        elif current_pct_b > 1.0:
            direction = SignalDirection.BULLISH
            clamped = 0.35
            action = "价格突破上轨，趋势加速中。"
        elif current_pct_b < 0.0:
            direction = SignalDirection.BEARISH
            clamped = -0.35
            action = "价格跌破下轨，下跌加速中。"
        elif current_pct_b > 0.7:
            direction = SignalDirection.NEUTRAL_BULLISH
            clamped = 0.15
            action = "价格偏向上轨。"
        elif current_pct_b < 0.3:
            direction = SignalDirection.NEUTRAL_BEARISH
            clamped = -0.15
            action = "价格偏向下轨。"
        else:
            direction = SignalDirection.NEUTRAL
            clamped = 0.0
            action = "布林带中轨附近，等待方向选择。"

        evidence = [
            self._evidence(
                data_point=f"BW={current_bw:.4f} (分位{bw_pct:.0%}), %B={current_pct_b:.3f}, Close={current_close:.2f}",
                interpretation=f"带宽处于{bw_pct:.0%}分位，%B={current_pct_b:.2f}",
                implication="带宽收缩至极值=大行情前兆，%B突破1.0=趋势加速",
                confidence=0.7,
            ),
        ]

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=float(current_pct_b),
            confidence=0.70 if abs(clamped) > 0.3 else 0.40,
            data_freshness_ms=0, data_completeness=1.0, weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"bandwidth": current_bw, "bandwidth_percentile": bw_pct, "pct_b": current_pct_b},
                evidence,
                f"布林带: BW={current_bw:.4f}({bw_pct:.0%}), %B={current_pct_b:.3f}。{action}",
                action,
                limitations=["布林带在盘整期频繁假突破"],
            ),
        )
