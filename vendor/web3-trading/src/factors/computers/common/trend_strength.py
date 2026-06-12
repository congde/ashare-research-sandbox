"""趋势强度 — 多周期EMA排列+ADX综合判断。"""
from __future__ import annotations

from typing import ClassVar, List

import numpy as np

from ...base import BaseFactorComputer
from ...context import FactorContext
from ...enums import FactorCategory, FactorTier, SignalDirection
from ...models import FactorResult
from .._utils import adx, ema, get_kline_column


class TrendStrengthComputer(BaseFactorComputer):
    factor_name: ClassVar[str] = "trend_strength"
    category: ClassVar[FactorCategory] = FactorCategory.TECHNICAL
    display_name: ClassVar[str] = "趋势强度"
    description: ClassVar[str] = "多周期EMA排列状态+ADX趋势强度，综合判断趋势方向和可靠性。"
    requires_data: ClassVar[List[str]] = ["kline"]

    async def compute(self, ctx: FactorContext) -> FactorResult:
        klines = ctx.data.get("kline", {})
        close_1d = get_kline_column(klines, "1d", "close")
        high_1d = get_kline_column(klines, "1d", "high")
        low_1d = get_kline_column(klines, "1d", "low")

        if close_1d is None or len(close_1d) < 50:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "K线数据不足，需要至少50根日线。"),
            )

        ema12 = ema(close_1d, 12)
        ema26 = ema(close_1d, 26)
        ema50 = ema(close_1d, 50)
        adx_val = adx(high_1d, low_1d, close_1d, 14)

        last = -1
        ema_alignment = np.sign(ema12[last] - ema26[last]) + np.sign(ema26[last] - ema50[last])
        current_adx = adx_val[last]

        trend_score = ema_alignment * min(current_adx / 25.0, 2.0) if not np.isnan(current_adx) else 0.0

        evidence = [
            self._evidence(
                data_point=f"EMA12={ema12[last]:.2f}, EMA26={ema26[last]:.2f}, EMA50={ema50[last]:.2f}",
                interpretation=f"EMA排列: {'多头' if ema_alignment > 0 else '空头' if ema_alignment < 0 else '交叉'} (得分={ema_alignment})",
                implication="多头排列表示上升趋势，空头排列表示下降趋势",
                confidence=0.8,
            ),
            self._evidence(
                data_point=f"ADX(14)={current_adx:.1f}",
                interpretation=f"ADX: {'强趋势' if current_adx > 25 else '震荡' if current_adx < 20 else '趋势形成中'}",
                implication="ADX>25确认趋势有效，<20表示震荡市",
                confidence=0.75,
            ),
        ]

        clamped = max(-1.0, min(1.0, trend_score / 3.0))
        if clamped > 0.5:
            direction = SignalDirection.STRONG_BULLISH
            action = "强多头趋势，顺势做多。"
        elif clamped > 0.15:
            direction = SignalDirection.BULLISH
            action = "偏多趋势，持仓为主。"
        elif clamped < -0.5:
            direction = SignalDirection.STRONG_BEARISH
            action = "强空头趋势，空仓或做空。"
        elif clamped < -0.15:
            direction = SignalDirection.BEARISH
            action = "偏空趋势，减仓。"
        else:
            direction = SignalDirection.NEUTRAL
            action = "震荡市，高抛低吸。"

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=float(trend_score),
            confidence=0.80 if abs(clamped) > 0.3 else 0.55,
            data_freshness_ms=0, data_completeness=1.0, weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"ema_alignment": int(ema_alignment), "adx": float(current_adx), "trend_score": float(trend_score)},
                evidence,
                f"趋势得分: {trend_score:+.2f}。{action}",
                action,
                limitations=["EMA排列在盘整期频繁交叉产生噪音"],
            ),
        )
