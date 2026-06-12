"""成交量加权均价偏离 — 价格相对VWAP偏离，机构成本代理变量。"""
from __future__ import annotations

from typing import ClassVar, List

from ...base import BaseFactorComputer
from ...context import FactorContext
from ...enums import FactorCategory, FactorTier, SignalDirection
from ...models import FactorResult
from .._utils import get_kline_column, vwap


class VWAPDeviationComputer(BaseFactorComputer):
    factor_name: ClassVar[str] = "vwap_deviation"
    category: ClassVar[FactorCategory] = FactorCategory.TECHNICAL
    display_name: ClassVar[str] = "VWAP偏离"
    description: ClassVar[str] = "当前价格相对滚动VWAP偏离，机构成本代理变量。"
    requires_data: ClassVar[List[str]] = ["kline"]

    async def compute(self, ctx: FactorContext) -> FactorResult:
        klines = ctx.data.get("kline", {})
        close = get_kline_column(klines, "1h", "close")
        volume = get_kline_column(klines, "1h", "volume")

        if close is None or volume is None or len(close) < 24:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "K线数据不足，需要至少24根1h K线。"),
            )

        v = vwap(close, volume, 24)
        current_vwap = float(v[-1])
        current_close = float(close[-1])

        if current_vwap != current_vwap or current_vwap == 0:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "VWAP数据不足。"),
            )

        deviation_pct = (current_close - current_vwap) / current_vwap * 100.0

        clamped = max(-1.0, min(1.0, -deviation_pct / 5.0))

        evidence = [
            self._evidence(
                data_point=f"VWAP(24h)={current_vwap:.4f}, Close={current_close:.4f}, 偏离={deviation_pct:+.2f}%",
                interpretation=f"价格{'高于' if deviation_pct > 0 else '低于'}VWAP {abs(deviation_pct):.2f}%",
                implication="价格低于VWAP=机构成本线下方，可能吸筹；高于VWAP=成本线上方，可能派发",
                confidence=0.6,
            ),
        ]

        if deviation_pct < -3:
            direction = SignalDirection.BULLISH
            action = "价格显著低于VWAP，机构成本线下方吸筹，做多。"
        elif deviation_pct > 3:
            direction = SignalDirection.BEARISH
            action = "价格显著高于VWAP，机构成本线上方派发，注意回调。"
        elif deviation_pct < -1:
            direction = SignalDirection.NEUTRAL_BULLISH
            action = "价格略低于VWAP，偏多。"
        elif deviation_pct > 1:
            direction = SignalDirection.NEUTRAL_BEARISH
            action = "价格略高于VWAP，偏空。"
        else:
            direction = SignalDirection.NEUTRAL
            clamped = 0.0
            action = "价格在VWAP附近，中性。"

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=float(deviation_pct),
            confidence=0.55 if abs(deviation_pct) > 2 else 0.35,
            data_freshness_ms=0, data_completeness=1.0, weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"vwap": current_vwap, "close": current_close, "deviation_pct": float(deviation_pct)},
                evidence,
                f"VWAP偏离: {deviation_pct:+.2f}%。{action}",
                action,
                limitations=["VWAP仅反映1日机构成本，中长期成本需更长窗口"],
            ),
        )
