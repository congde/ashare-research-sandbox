"""机会等级 — 公共因子。

Grade 1-3，AI 模型评估的风险收益等级。
"""
from __future__ import annotations

from typing import ClassVar, List

from ...base import BaseFactorComputer
from ...context import FactorContext
from ...enums import FactorCategory, FactorTier, SignalDirection
from ...models import FactorResult


class GradeComputer(BaseFactorComputer):
    factor_name: ClassVar[str] = "grade"
    category: ClassVar[FactorCategory] = FactorCategory.AI_COMPOSITE
    display_name: ClassVar[str] = "机会等级"
    description: ClassVar[str] = "AI 机会列表中的风险收益等级，1-3 级。"
    requires_data: ClassVar[List[str]] = ["ai_chance"]

    async def compute(self, ctx: FactorContext) -> FactorResult:
        ai_item = ctx.data.get("ai_chance")
        if ai_item is None:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [],
                    "该代币未在机会列表中。"),
            )

        grade = int(getattr(ai_item, "grade", 0) or 0)
        if grade == 0:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.NEUTRAL,
                normalized_score=0.0, raw_value=0.0, confidence=0.3,
                data_completeness=0.5, weight=0.0,
                trace=self._build_trace(self.factor_name, {"grade": grade}, [],
                    "机会等级未提供。"),
            )

        evidence = [self._evidence(
            data_point=f"机会等级: {grade}/3",
            interpretation=f"{'高风险高收益' if grade == 3 else '中等风险' if grade == 2 else '低风险'}机会",
            implication="高等级需严格止损" if grade == 3 else ("风险可控" if grade == 1 else ""),
            confidence=0.60,
        )]

        if grade == 3:
            clamped = 0.35
            direction = SignalDirection.NEUTRAL_BULLISH
            action = "高等级机会，需严格止损。"
        elif grade == 2:
            clamped = 0.15
            direction = SignalDirection.NEUTRAL
            action = "中等机会。"
        else:
            clamped = 0.05
            direction = SignalDirection.NEUTRAL
            action = "低等级机会，信号强度弱。"

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=float(grade),
            confidence=0.50, data_freshness_ms=0, data_completeness=1.0,
            weight=0.0,
            trace=self._build_trace(
                self.factor_name, {"grade": grade}, evidence,
                f"机会等级: {grade}/3。", action,
                limitations=["等级由AI模型评估，主观性强"],
            ),
        )
