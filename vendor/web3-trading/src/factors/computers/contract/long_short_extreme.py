"""多空拥挤度 — 资金费率历史分位数，极端值暗示单边拥挤反转（仅合约）。

资金费率是市场多空力量最直接的代理变量：
  - 极高资金费率 = 多头拥挤（做多成本高）
  - 极低资金费率 = 空头拥挤（做空成本高）

使用分位数方法（vs funding_rate_zscore 的 Z-score 方法）互补：
  - 分位数对分布形状无假设，对长尾分布更稳健
  - Z-score 对正态偏离更敏感
"""
from __future__ import annotations

from typing import ClassVar, List, Set

import numpy as np

from ...base import BaseFactorComputer
from ...context import FactorContext
from ...enums import FactorCategory, FactorTier, MarketType, SignalDirection
from ...models import FactorResult, FundingRateData


class LongShortExtremeComputer(BaseFactorComputer):
    factor_name: ClassVar[str] = "long_short_extreme"
    category: ClassVar[FactorCategory] = FactorCategory.DERIVATIVES
    display_name: ClassVar[str] = "多空拥挤度"
    description: ClassVar[str] = "资金费率历史分位数，极端值=单边拥挤，反向指标。"
    requires_data: ClassVar[List[str]] = ["funding_rate"]
    supported_markets: ClassVar[Set[MarketType]] = {MarketType.CONTRACT}

    async def compute(self, ctx: FactorContext) -> FactorResult:
        rates_data = ctx.data.get("funding_rate")
        if rates_data is None:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "无资金费率数据。"),
            )

        rates: np.ndarray
        if isinstance(rates_data, FundingRateData):
            rates = np.asarray(rates_data.values, dtype=np.float64)
        elif isinstance(rates_data, (list, np.ndarray)):
            rates = np.asarray(rates_data, dtype=np.float64)
        elif isinstance(rates_data, dict):
            arr = rates_data.get("rates") or rates_data.get("values") or []
            rates = np.asarray(arr, dtype=np.float64)
        else:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "资金费率数据格式不支持。"),
            )

        if len(rates) < 30:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "资金费率历史不足（需要至少30条）。"),
            )

        current_rate = float(rates[-1])
        percentile = float(np.sum(rates <= current_rate) / len(rates))

        if percentile > 0.9:
            direction = SignalDirection.BEARISH
            clamped = -0.5
            action = "资金费率极端高位（多头拥挤），反向做空。"
        elif percentile < 0.1:
            direction = SignalDirection.BULLISH
            clamped = 0.5
            action = "资金费率极端低位（空头拥挤），逼空风险，做多。"
        elif percentile > 0.7:
            direction = SignalDirection.NEUTRAL_BEARISH
            clamped = -0.2
            action = "资金费率偏高，偏空。"
        elif percentile < 0.3:
            direction = SignalDirection.NEUTRAL_BULLISH
            clamped = 0.2
            action = "资金费率偏低，偏多。"
        else:
            direction = SignalDirection.NEUTRAL
            clamped = 0.0
            action = "资金费率正常范围。"

        evidence = [
            self._evidence(
                data_point=f"资金费率: {current_rate:.6f} ({percentile:.0%}分位)",
                interpretation=f"资金费率处于{'极端高位' if percentile > 0.9 else '极端低位' if percentile < 0.1 else '正常'}",
                implication="极端费率是反向指标，拥挤方向容易反转",
                confidence=0.70 if percentile > 0.85 or percentile < 0.15 else 0.45,
            ),
        ]

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=float(percentile),
            confidence=0.70 if abs(clamped) > 0.3 else 0.45,
            data_freshness_ms=0, data_completeness=1.0, weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"current_rate": float(current_rate), "percentile": float(percentile)},
                evidence,
                f"费率分位: {percentile:.0%} ({current_rate:.6f})。{action}",
                action,
                limitations=["资金费率不直接等于多空持仓比，是代理指标"],
            ),
        )
