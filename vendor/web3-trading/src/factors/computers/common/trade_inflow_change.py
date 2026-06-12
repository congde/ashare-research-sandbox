"""资金净流入变化率 — 公共因子。

捕捉资金流向的边际变化，通常领先绝对流向 1-2 个周期。
数据源从 getCoinTrade（realtime_fund）读取，按市场类型选择 spot_goods_list 或 contract_list。
"""
from __future__ import annotations

from typing import ClassVar, List

from ...base import BaseFactorComputer
from ...context import FactorContext
from ...enums import DataGranularity, FactorCategory, FactorTier, MarketType, SignalDirection
from ...models import FactorResult, GranularityValue
from ...utils import TIME_PARTICLE_TO_GRANULARITY


class TradeInflowChangeComputer(BaseFactorComputer):
    factor_name: ClassVar[str] = "trade_inflow_change"
    category: ClassVar[FactorCategory] = FactorCategory.FUND_FLOW
    display_name: ClassVar[str] = "资金净流入变化率"
    description: ClassVar[str] = "从 realtime_fund 数据计算的净流入环比变化率。"
    requires_data: ClassVar[List[str]] = ["realtime_fund"]

    _GRAN_WEIGHTS = {
        DataGranularity.H8: 1.0, DataGranularity.H24: 1.2,
        DataGranularity.H1: 0.7, DataGranularity.M30: 0.5,
        DataGranularity.M15: 0.4, DataGranularity.M5: 0.3,
    }

    async def compute(self, ctx: FactorContext) -> FactorResult:
        rt = ctx.data.get("realtime_fund")
        if rt is None:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "无 realtime_fund 数据。"),
            )

        is_spot = ctx.market_type == MarketType.SPOT
        items = rt.spot_goods_list if is_spot else rt.contract_list

        if not items:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.3, weight=0.0,
                trace=self._build_trace(self.factor_name, {"item_count": 0}, [],
                    f"{'现货' if is_spot else '合约'}数据为空。"),
            )

        evidence = []
        gran_results: List[GranularityValue] = []
        total_score = 0.0
        total_weight = 0.0

        for item in items:
            tpe = getattr(item, "time_particle_enum", None)
            if tpe is None:
                continue
            gran = TIME_PARTICLE_TO_GRANULARITY.get(int(tpe) if isinstance(tpe, str) else tpe)
            if gran is None:
                continue

            # 优先使用 API 返回的 trade_inflow_change，否则用 trade_inflow
            change = float(getattr(item, "trade_inflow_change", 0) or 0)
            gw = self._GRAN_WEIGHTS.get(gran, 0.4)

            # 流出加速（change < 0）= 看涨，流入加速（change > 0）= 看跌
            score = -change
            clamped_change = max(-2.0, min(2.0, score))
            normed = max(-1.0, min(1.0, clamped_change / 2.0))

            gran_results.append(GranularityValue(granularity=gran, value=change, weight=min(gw, 1.0)))
            total_score += normed * gw
            total_weight += gw

            if abs(change) > 0.05:
                direction_word = "流出加速" if change < 0 else "流入加速"
                inflow = float(getattr(item, "trade_inflow", 0) or 0)
                evidence.append(self._evidence(
                    data_point=f"{gran.value} 变化率: {change:+.2%} (净流入={inflow:,.0f})",
                    interpretation=f"{gran.value}级别资金{direction_word}",
                    implication="流出加速→囤币意愿增强，利好" if change < 0 else "流入加速→抛压增强，利空",
                    confidence=0.75 if abs(change) > 0.3 else 0.50,
                ))

        if total_weight == 0:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.2, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "无法解析时间粒度。"),
            )

        aggregate = total_score / total_weight
        clamped = max(-1.0, min(1.0, aggregate * 1.1))

        if clamped > 0.3:
            direction = SignalDirection.STRONG_BULLISH
            action = "流出加速信号强烈，偏多。"
        elif clamped > 0.08:
            direction = SignalDirection.BULLISH
            action = "流出加速，偏多。"
        elif clamped < -0.3:
            direction = SignalDirection.STRONG_BEARISH
            action = "流入加速信号强烈，偏空。"
        elif clamped < -0.08:
            direction = SignalDirection.BEARISH
            action = "流入加速，偏空。"
        else:
            direction = SignalDirection.NEUTRAL
            action = "观望。"

        market_label = "现货" if is_spot else "合约"
        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=aggregate,
            confidence=min(0.90, 0.55 + total_weight * 0.08),
            data_freshness_ms=0,
            data_completeness=min(1.0, total_weight / 3.0),
            weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"market": market_label, "aggregate": aggregate},
                evidence,
                f"{market_label}资金净流入变化率得分: {clamped:+.3f}。综合判断: {direction.value}。",
                action,
                limitations=["变化率对单个大单敏感，可能产生噪声"],
            ),
            granularity_breakdown=gran_results,
        )
