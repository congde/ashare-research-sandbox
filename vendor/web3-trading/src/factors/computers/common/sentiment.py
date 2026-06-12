"""看涨看跌情绪比例 — 公共因子。

基于社媒内容分析的看涨/看跌情绪比例。
极端情绪是反向指标：过度看涨→回调，过度看跌→反弹。
"""
from __future__ import annotations

from typing import ClassVar, List

from ...base import BaseFactorComputer
from ...context import FactorContext
from ...enums import FactorCategory, FactorTier, SignalDirection
from ...models import FactorResult


class SentimentRatioComputer(BaseFactorComputer):
    factor_name: ClassVar[str] = "sentiment_ratio"
    category: ClassVar[FactorCategory] = FactorCategory.SOCIAL
    display_name: ClassVar[str] = "看涨看跌情绪比例"
    description: ClassVar[str] = "从社媒情绪数据分析的看涨/看跌比例。"
    requires_data: ClassVar[List[str]] = ["ai_chance", "social_sentiment"]

    async def compute(self, ctx: FactorContext) -> FactorResult:
        ai_item = ctx.data.get("ai_chance")
        social = ctx.data.get("social_sentiment")

        bullish = 0.5
        bearish = 0.5

        if ai_item is not None:
            br = getattr(ai_item, "bullish_ratio", None)
            ber = getattr(ai_item, "bearish_ratio", None)
            if br is not None:
                bullish = float(br)
            if ber is not None:
                bearish = float(ber)

        if social is not None and (bullish == 0.5 and bearish == 0.5):
            bullish = social.bullish_ratio
            bearish = social.bearish_ratio

        if bullish == 0.5 and bearish == 0.5:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "无情绪数据。"),
            )

        net_bullish = bullish - bearish

        if net_bullish > 0.3:
            clamped = -net_bullish * 0.6
            direction = SignalDirection.BEARISH
            action = "市场情绪过度看涨，警惕回调，考虑获利了结。"
            interpretation = f"看涨情绪极端({bullish:.0%})，市场过热"
        elif net_bullish > 0.05:
            clamped = net_bullish * 0.8
            direction = SignalDirection.NEUTRAL_BULLISH
            action = "市场偏乐观。"
            interpretation = f"看涨情绪温和({bullish:.0%})"
        elif net_bullish < -0.3:
            clamped = abs(net_bullish) * 0.6
            direction = SignalDirection.BULLISH
            action = "市场情绪过度看跌，可能超卖反弹，关注做多机会。"
            interpretation = f"看跌情绪极端({bearish:.0%})，市场恐慌"
        elif net_bullish < -0.05:
            clamped = net_bullish * 0.8
            direction = SignalDirection.NEUTRAL_BEARISH
            action = "市场偏悲观。"
            interpretation = f"看跌情绪({bearish:.0%})"
        else:
            clamped = 0.0
            direction = SignalDirection.NEUTRAL
            action = "观望。"
            interpretation = f"情绪中性(看涨{bullish:.0%}, 看跌{bearish:.0%})"

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=net_bullish,
            confidence=0.65 if abs(net_bullish) > 0.2 else 0.45,
            data_freshness_ms=0, data_completeness=1.0,
            weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"bullish_ratio": bullish, "bearish_ratio": bearish, "net": net_bullish},
                [self._evidence(
                    data_point=f"看涨={bullish:.0%}, 看跌={bearish:.0%}",
                    interpretation=interpretation,
                    implication=(
                        "极端看涨情绪常预示回调" if net_bullish > 0.3
                        else "极端看跌情绪常预示反弹" if net_bullish < -0.3
                        else "温和情绪无明确方向信号"
                    ),
                    confidence=0.60,
                )],
                f"社媒情绪: 看涨{bullish:.0%}, 看跌{bearish:.0%}。净看涨={net_bullish:+.3f}。",
                action,
                limitations=["社媒情绪易受舆论操纵，不适用于低流动性代币"],
            ),
        )
