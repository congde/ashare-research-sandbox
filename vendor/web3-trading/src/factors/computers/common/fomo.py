"""FOMO指标 — 公共因子。

市场情绪过热信号。fomo=true 表示追涨风险，fomoEscalation=true 表示极端风险。
作为反向指标使用：极端FOMO → 即将回调。
"""
from __future__ import annotations

from typing import ClassVar, List

from ...base import BaseFactorComputer
from ...context import FactorContext
from ...enums import FactorCategory, FactorTier, SignalDirection
from ...models import FactorResult


class FomoComputer(BaseFactorComputer):
    factor_name: ClassVar[str] = "fomo"
    category: ClassVar[FactorCategory] = FactorCategory.AI_COMPOSITE
    display_name: ClassVar[str] = "FOMO指标"
    description: ClassVar[str] = "市场过热信号，作为反向指标使用。"
    requires_data: ClassVar[List[str]] = ["ai_chance", "ai_risk", "ai_funds"]

    async def compute(self, ctx: FactorContext) -> FactorResult:
        results = {}
        for key in ["ai_chance", "ai_risk", "ai_funds"]:
            item = ctx.data.get(key)
            if item is not None:
                fomo_val = getattr(item, "fomo", None)
                escalation = getattr(item, "fomo_escalation", None)
                if fomo_val is not None or escalation is not None:
                    results[key] = (bool(fomo_val), bool(escalation))

        if not results:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "无FOMO数据。"),
            )

        fomo_triggered = any(f for f, _ in results.values())
        escalation_triggered = any(e for _, e in results.values())
        evidence = []

        if escalation_triggered:
            evidence.append(self._evidence(
                data_point="FOMO升级触发",
                interpretation="市场情绪极端过热，FOMO进一步升级",
                implication="风险显著增加，短期回调概率高→考虑获利了结",
                confidence=0.85,
            ))
        elif fomo_triggered:
            evidence.append(self._evidence(
                data_point="FOMO触发",
                interpretation="市场情绪过热",
                implication="需警惕追高风险，短期可能回调",
                confidence=0.70,
            ))
        else:
            evidence.append(self._evidence(
                data_point="FOMO未触发",
                interpretation="市场情绪正常",
                implication="无过度追涨风险",
                confidence=0.50,
            ))

        if escalation_triggered:
            clamped = -0.6
            direction = SignalDirection.BEARISH
            action = "FOMO升级，强烈建议获利了结或减仓。"
        elif fomo_triggered:
            clamped = -0.3
            direction = SignalDirection.NEUTRAL_BEARISH
            action = "FOMO触发，注意回调风险。"
        else:
            clamped = 0.0
            direction = SignalDirection.NEUTRAL
            action = "观望。"

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=2.0 if escalation_triggered else (1.0 if fomo_triggered else 0.0),
            confidence=0.80 if escalation_triggered else (0.65 if fomo_triggered else 0.40),
            data_freshness_ms=0, data_completeness=1.0 if results else 0.0,
            weight=0.0,
            trace=self._build_trace(
                self.factor_name, {"fomo": fomo_triggered, "escalation": escalation_triggered},
                evidence,
                f"FOMO: {'升级' if escalation_triggered else '触发' if fomo_triggered else '未触发'}。",
                action,
                limitations=["FOMO指标为AI模型判断，可能存在误报"],
            ),
        )
