"""社媒因子 — 公共因子。

- 社媒内容摘要：社媒情感分、提及量、热度
- 机会/风险消息类型：AI 信号来源分类
"""
from __future__ import annotations

from typing import ClassVar, List

from ...base import BaseFactorComputer
from ...context import FactorContext
from ...enums import FactorCategory, FactorTier, SignalDirection
from ...models import FactorResult


class SocialContentComputer(BaseFactorComputer):
    """社媒内容摘要 — 定性情感背景。"""

    factor_name: ClassVar[str] = "social_content"
    category: ClassVar[FactorCategory] = FactorCategory.SOCIAL
    display_name: ClassVar[str] = "社媒内容摘要"
    description: ClassVar[str] = "社媒内容摘要，定性情感背景信息。"
    requires_data: ClassVar[List[str]] = ["social_sentiment"]

    async def compute(self, ctx: FactorContext) -> FactorResult:
        social = ctx.data.get("social_sentiment")
        if social is None:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "无社媒数据。"),
            )

        bullish = getattr(social, "bullish_ratio", 0) or 0
        bearish = getattr(social, "bearish_ratio", 0) or 0
        neutral = getattr(social, "neutral_ratio", 0) or 0

        bullish_contents = getattr(social, "bullish_contents", []) or []
        bearish_contents = getattr(social, "bearish_contents", []) or []
        neutral_contents = getattr(social, "neutral_contents", []) or []
        total_contents = len(bullish_contents) + len(bearish_contents) + len(neutral_contents)

        evidence = [self._evidence(
            data_point=f"看涨={bullish:.1%}, 看跌={bearish:.1%}, 中性={neutral:.1%}, 内容数={total_contents}",
            interpretation=f"社媒{'看涨情绪占优' if bullish > bearish else '看跌情绪占优' if bearish > bullish else '多空均衡'}",
            implication="社媒情绪为背景信息，不直接产生交易信号",
            confidence=0.40 if total_contents > 0 else 0.20,
        )]

        net_sentiment = bullish - bearish

        # 弱方向信号：社媒情绪可提供边际方向参考，Tier 5 权重小(0.1)，不会主导综合评分
        clamped = max(-0.2, min(0.2, net_sentiment * 0.4))
        if clamped > 0.05:
            direction = SignalDirection.NEUTRAL_BULLISH
            action = "社媒情绪偏乐观，轻微看多。"
        elif clamped < -0.05:
            direction = SignalDirection.NEUTRAL_BEARISH
            action = "社媒情绪偏悲观，轻微看空。"
        else:
            direction = SignalDirection.NEUTRAL
            action = "社媒情绪中性。"

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=net_sentiment,
            confidence=0.35 if total_contents > 0 else 0.15,
            data_freshness_ms=0, data_completeness=1.0,
            weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"bullish_ratio": bullish, "bearish_ratio": bearish,
                 "neutral_ratio": neutral, "total_contents": total_contents},
                evidence,
                f"社媒: 看涨{bullish:.1%}, 看跌{bearish:.1%}, 中性{neutral:.1%}。"
                f"净情绪={'偏多' if clamped > 0 else '偏空' if clamped < 0 else '中性'}。",
                action,
                limitations=["社媒情绪为定性参考，需结合其他因子综合判断"],
            ),
        )


class MessageTypesComputer(BaseFactorComputer):
    """机会/风险消息类型分类。"""

    factor_name: ClassVar[str] = "message_types"
    category: ClassVar[FactorCategory] = FactorCategory.AI_COMPOSITE
    display_name: ClassVar[str] = "机会/风险消息类型"
    description: ClassVar[str] = "AI 信号消息类型分类。"
    requires_data: ClassVar[List[str]] = ["ai_chance", "ai_risk", "ai_funds"]

    async def compute(self, ctx: FactorContext) -> FactorResult:
        sources = []
        for key, label in [("ai_chance", "机会"), ("ai_risk", "风险"), ("ai_funds", "资金")]:
            item = ctx.data.get(key)
            if item is not None:
                reason = getattr(item, "reason", "") or ""
                sources.append(f"{label}: {reason}")

        if not sources:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "无AI消息数据。"),
            )

        evidence = [self._evidence(
            data_point="; ".join(sources),
            interpretation=f"AI信号来源: {len(sources)}个列表",
            implication="消息类型为定性参考信息",
            confidence=0.30,
        )]

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=SignalDirection.NEUTRAL,
            normalized_score=0.0,
            raw_value=float(len(sources)),
            confidence=0.25,
            data_freshness_ms=0, data_completeness=1.0,
            weight=0.0,
            trace=self._build_trace(
                self.factor_name, {"sources": sources}, evidence,
                f"AI消息: {'; '.join(sources[:2])}。零权重元数据因子。",
                limitations=["消息类型含义需参照业务文档"],
            ),
        )
