"""AI综合评分及变化 — 公共因子。

消费 ValueScan AI 模型的预融合评分（0-100）及其环比变化。
计算逻辑与市场类型（现货/合约）无关。
"""
from __future__ import annotations

from typing import ClassVar, List

from ...base import BaseFactorComputer
from ...context import FactorContext
from ...enums import FactorCategory, FactorTier, SignalDirection
from ...models import EvidenceLink, FactorResult
from ...utils import clamp_score


class ScoreAndChangeComputer(BaseFactorComputer):
    factor_name: ClassVar[str] = "score_and_change"
    category: ClassVar[FactorCategory] = FactorCategory.AI_COMPOSITE
    display_name: ClassVar[str] = "AI综合评分及变化"
    description: ClassVar[str] = "AI 综合评分（0-100）及其环比变化。"
    requires_data: ClassVar[List[str]] = ["ai_chance", "ai_risk", "ai_funds"]

    async def compute(self, ctx: FactorContext) -> FactorResult:
        ai_chance = ctx.data.get("ai_chance")
        ai_risk = ctx.data.get("ai_risk")
        ai_funds = ctx.data.get("ai_funds")

        evidence: List[EvidenceLink] = []
        score = 50.0
        score_change = 0.0
        source = ""

        if ai_chance is not None:
            score = float(getattr(ai_chance, "score", 50) or 50)
            score_change = float(getattr(ai_chance, "score_change", 0) or 0)
            source = "chance"
            evidence.append(self._evidence(
                data_point=f"AI机会评分: {score:.0f}/100",
                interpretation=f"机会代币列表中，评分={score:.0f}",
                implication="高分表示上涨潜力强" if score > 55 else "低分表示上涨潜力弱",
                confidence=0.80,
            ))
        elif ai_risk is not None:
            score = float(getattr(ai_risk, "score", 50) or 50)
            score_change = float(getattr(ai_risk, "score_change", 0) or 0)
            source = "risk"
            evidence.append(self._evidence(
                data_point=f"AI风险评分: {score:.0f}/100",
                interpretation=f"风险代币列表中，评分={score:.0f}",
                implication="高分表示下跌风险大" if score > 75 else "低分表示下跌风险小",
                confidence=0.80,
            ))
        elif ai_funds is not None:
            score = float(getattr(ai_funds, "score", 50) or 50)
            source = "funds"
            evidence.append(self._evidence(
                data_point=f"AI资金异动评分: {score:.0f}/100",
                interpretation="资金异动列表中",
                implication="主力异常活跃，需关注方向",
                confidence=0.65,
            ))
        else:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=50.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [],
                    "该代币未出现在AI机会/风险/资金列表中。"),
            )

        if abs(score_change) > 1:
            direction_word = "上升" if score_change > 0 else "下降"
            evidence.append(self._evidence(
                data_point=f"评分变化: {score_change:+.1f}",
                interpretation=f"AI评分环比{direction_word}",
                implication=(
                    "上涨潜力增强" if score_change > 0 and source == "chance"
                    else "下跌风险增大" if score_change > 0 and source == "risk"
                    else "信号减弱"
                ),
                confidence=0.60,
            ))

        if source == "chance":
            raw_norm = (score - 55) / 25.0
            clamped = clamp_score(raw_norm * 0.8)
        elif source == "risk":
            if score >= 75:
                raw_norm = -(score - 75) / 5.0
                clamped = clamp_score(raw_norm * 0.8)
            else:
                clamped = 0.0
        else:
            clamped = 0.0

        if abs(score_change) > 1:
            change_impact = clamp_score(score_change / 10.0) * 0.3
            clamped = clamp_score(clamped + change_impact)

        if clamped > 0.25:
            direction = SignalDirection.BULLISH
            action = "AI评分偏多，可做多。"
        elif clamped < -0.25:
            direction = SignalDirection.BEARISH
            action = "AI评分偏空，可做空或减仓。"
        else:
            direction = SignalDirection.NEUTRAL
            action = "观望。"

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=score,
            confidence=0.75 if source in ("chance", "risk") else 0.55,
            data_freshness_ms=0, data_completeness=1.0,
            weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"score": score, "score_change": score_change, "source": source},
                evidence,
                f"AI综合评分: {score:.0f}/100 (来源={source})。评分变化: {score_change:+.1f}。归一化得分: {clamped:+.3f}。",
                action,
                limitations=["AI评分为黑盒模型输出，内部逻辑不可解释"],
            ),
        )
