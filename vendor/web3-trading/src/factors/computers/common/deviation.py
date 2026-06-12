"""主力成本偏离度 — 公共因子。

deviation = (当前价格 - 主力成本价) / 主力成本价 × 100%。
计算逻辑与市场类型无关，但不同市场下的解读权重由 RankingProfile 决定。
"""
from __future__ import annotations

from typing import ClassVar, List

from ...base import BaseFactorComputer
from ...context import FactorContext
from ...enums import FactorCategory, FactorTier, SignalDirection
from ...models import FactorResult
from ...utils import clamp_score, normalize_to_bipolar


class DeviationComputer(BaseFactorComputer):
    factor_name: ClassVar[str] = "deviation"
    category: ClassVar[FactorCategory] = FactorCategory.WHALE_COST
    display_name: ClassVar[str] = "主力成本偏离度"
    description: ClassVar[str] = "主力成本与市场价格之间的偏离百分比。"
    requires_data: ClassVar[List[str]] = ["whale_cost"]

    async def compute(self, ctx: FactorContext) -> FactorResult:
        whale_data = ctx.data.get("whale_cost") or []
        ai_item = ctx.data.get("ai_chance")

        deviation_pct = 0.0
        latest_cost = 0.0
        latest_price = ctx.current_price

        if ai_item is not None and getattr(ai_item, "deviation", None) is not None:
            deviation_pct = float(ai_item.deviation)
        elif whale_data:
            latest = whale_data[-1]
            cost = getattr(latest, "cost", 0.0)
            price = getattr(latest, "price", ctx.current_price)
            if cost > 0:
                latest_cost = cost
                latest_price = price
                deviation_pct = (price - cost) / cost * 100.0

        if deviation_pct == 0.0 and not whale_data and ai_item is None:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [],
                    "无主力成本数据，无法计算偏离度。"),
            )

        normed = normalize_to_bipolar(-deviation_pct, center=0.0, scale=50.0)
        clamped = clamp_score(normed)

        if deviation_pct < -20:
            direction = SignalDirection.STRONG_BULLISH
            action = "价格低于主力成本超过20%，主力亏损严重，护盘动力强，考虑做多。"
            counter = "若主力已减仓离场，低于成本也不会护盘。"
        elif deviation_pct < -5:
            direction = SignalDirection.BULLISH
            action = "价格略低于主力成本，偏多。"
            counter = ""
        elif deviation_pct > 30:
            direction = SignalDirection.STRONG_BEARISH
            action = "价格高于主力成本超过30%，主力已大幅盈利，派发风险极高，应止盈或做空。"
            counter = "若主力看好后市且未减仓，高盈利不一定意味派发。"
        elif deviation_pct > 10:
            direction = SignalDirection.BEARISH
            action = "价格高于主力成本，谨慎追多。"
            counter = ""
        else:
            direction = SignalDirection.NEUTRAL
            action = "观望。"
            counter = ""

        confidence = 0.85 if abs(deviation_pct) > 15 else 0.65

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=deviation_pct,
            confidence=confidence, data_freshness_ms=0,
            data_completeness=1.0 if deviation_pct != 0.0 else 0.5,
            weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"deviation_pct": deviation_pct, "current_price": latest_price, "whale_cost": latest_cost},
                [self._evidence(
                    data_point=f"偏离度={deviation_pct:+.1f}%",
                    interpretation="价格低于主力成本，主力亏损" if deviation_pct < 0 else "价格高于主力成本，主力盈利",
                    implication="主力亏损时倾向护盘或吸筹，利好上涨" if deviation_pct < 0 else "主力盈利时可能派发，利空",
                    confidence=confidence,
                )],
                f"主力成本偏离度: {deviation_pct:+.1f}%。当前价格为主力成本的{100+deviation_pct:.0f}%。",
                action,
                limitations=["主力成本为估算值，可能与实际有偏差"],
                counter_argument=counter,
            ),
        )
