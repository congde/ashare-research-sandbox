"""Alpha信号 — 公共因子。

布尔标志，表示是否具有超额收益潜力或主力异常活跃。
计算逻辑与市场类型无关。
"""
from __future__ import annotations

from typing import ClassVar, List

from ...base import BaseFactorComputer
from ...context import FactorContext
from ...enums import FactorCategory, FactorTier, SignalDirection
from ...models import FactorResult


class AlphaComputer(BaseFactorComputer):
    factor_name: ClassVar[str] = "alpha"
    category: ClassVar[FactorCategory] = FactorCategory.AI_COMPOSITE
    display_name: ClassVar[str] = "Alpha信号"
    description: ClassVar[str] = "超额收益潜力或主力异常活动的布尔标记。"
    requires_data: ClassVar[List[str]] = ["ai_chance", "ai_risk", "ai_funds"]

    async def compute(self, ctx: FactorContext) -> FactorResult:
        results = []
        for key, label in [("ai_chance", "机会"), ("ai_risk", "风险"), ("ai_funds", "资金")]:
            item = ctx.data.get(key)
            if item is not None:
                alpha_val = getattr(item, "alpha", None)
                if alpha_val is not None:
                    results.append((label, bool(alpha_val)))

        if not results:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "无Alpha信号数据。"),
            )

        evidence = []
        bull_alpha = False
        bear_alpha = False

        for source, alpha_flag in results:
            if alpha_flag:
                if source == "机会":
                    bull_alpha = True
                    evidence.append(self._evidence(
                        data_point=f"Alpha=true (来源={source})",
                        interpretation="Alpha超额收益信号触发，主力异常活跃",
                        implication="强烈做多信号——机会列表中的Alpha",
                        confidence=0.85,
                    ))
                elif source == "风险":
                    bear_alpha = True
                    evidence.append(self._evidence(
                        data_point=f"Alpha=true (来源={source})",
                        interpretation="风险列表中的Alpha信号触发",
                        implication="强烈做空信号——主力异常活跃且处于风险列表",
                        confidence=0.85,
                    ))
                elif source == "资金":
                    evidence.append(self._evidence(
                        data_point=f"Alpha=true (来源={source})",
                        interpretation="资金异动列表中的Alpha信号触发",
                        implication="主力异常活跃，需关注方向",
                        confidence=0.65,
                    ))

        if bull_alpha and bear_alpha:
            clamped = 0.0
            direction = SignalDirection.NEUTRAL
            action = "Alpha信号多空同时触发，观望。"
        elif bull_alpha:
            clamped = 0.7
            direction = SignalDirection.STRONG_BULLISH
            action = "机会列表Alpha触发，强烈看涨，可积极做多。"
        elif bear_alpha:
            clamped = -0.7
            direction = SignalDirection.STRONG_BEARISH
            action = "风险列表Alpha触发，强烈看跌，应减仓或做空。"
        else:
            clamped = 0.15
            direction = SignalDirection.NEUTRAL_BULLISH
            action = "资金异动Alpha，偏多关注。"

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=1.0 if (bull_alpha or bear_alpha) else 0.0,
            confidence=0.85 if (bull_alpha or bear_alpha) else 0.40,
            data_freshness_ms=0, data_completeness=1.0,
            weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"alpha_sources": results},
                evidence,
                f"Alpha信号: {'触发' if (bull_alpha or bear_alpha) else '未触发'}。",
                action,
                limitations=["Alpha为布尔值，无法量化强度"],
            ),
        )
