"""RSI极端区域 — 超买超卖 + 多周期RSI共振判断。"""
from __future__ import annotations

from typing import ClassVar, List

from ...base import BaseFactorComputer
from ...context import FactorContext
from ...enums import FactorCategory, FactorTier, SignalDirection
from ...models import FactorResult
from .._utils import get_kline_column, rsi


class RSIExtremeComputer(BaseFactorComputer):
    factor_name: ClassVar[str] = "rsi_extreme"
    category: ClassVar[FactorCategory] = FactorCategory.TECHNICAL
    display_name: ClassVar[str] = "RSI极端区域"
    description: ClassVar[str] = "RSI超买超卖+多周期共振，识别极端情绪反转。"
    requires_data: ClassVar[List[str]] = ["kline"]

    async def compute(self, ctx: FactorContext) -> FactorResult:
        klines = ctx.data.get("kline", {})

        rsi_values: dict[str, float] = {}
        evidence = []
        available = 0

        for tf in ["15m", "1h", "4h", "1d"]:
            close = get_kline_column(klines, tf, "close")
            if close is None or len(close) < 20:
                continue
            r = rsi(close, 14)
            val = float(r[-1])
            if val != val:
                continue
            rsi_values[tf] = val
            available += 1
            if val > 70:
                label = "超买"
            elif val < 30:
                label = "超卖"
            else:
                label = "正常"
            evidence.append(self._evidence(
                data_point=f"{tf} RSI(14): {val:.1f} ({label})",
                interpretation=f"{tf}周期RSI{'超买' if val > 70 else '超卖' if val < 30 else '中性'}",
                implication="极端RSI预示反转概率增加",
                confidence=0.65,
            ))

        if available == 0:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "K线数据不足。"),
            )

        primary_rsi = rsi_values.get("1h", rsi_values.get("4h", rsi_values.get("1d", 50.0)))

        overbought_count = sum(1 for v in rsi_values.values() if v > 70)
        oversold_count = sum(1 for v in rsi_values.values() if v < 30)

        if oversold_count >= 2:
            clamped = 0.55
            direction = SignalDirection.BULLISH
            action = "多周期RSI超卖共振，反弹做多机会。"
        elif overbought_count >= 2:
            clamped = -0.55
            direction = SignalDirection.BEARISH
            action = "多周期RSI超买共振，回调做空机会。"
        elif primary_rsi < 30:
            clamped = 0.35
            direction = SignalDirection.BULLISH
            action = "主周期RSI超卖，关注反弹。"
        elif primary_rsi > 70:
            clamped = -0.35
            direction = SignalDirection.BEARISH
            action = "主周期RSI超买，注意回调。"
        elif primary_rsi < 40:
            clamped = 0.1
            direction = SignalDirection.NEUTRAL_BULLISH
            action = "RSI偏低，偏多关注。"
        elif primary_rsi > 60:
            clamped = -0.1
            direction = SignalDirection.NEUTRAL_BEARISH
            action = "RSI偏高，偏空关注。"
        else:
            clamped = 0.0
            direction = SignalDirection.NEUTRAL
            action = "RSI中性区域。"

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=float(primary_rsi - 50),
            confidence=0.70 if abs(clamped) > 0.3 else 0.40,
            data_freshness_ms=0, data_completeness=float(available) / 4.0,
            weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"rsi_values": rsi_values, "overbought": overbought_count, "oversold": oversold_count},
                evidence,
                f"RSI: 超买{overbought_count}/超卖{oversold_count}。{action}",
                action,
                limitations=["RSI在强趋势中可能长期处于极端区域而不反转"],
            ),
        )
