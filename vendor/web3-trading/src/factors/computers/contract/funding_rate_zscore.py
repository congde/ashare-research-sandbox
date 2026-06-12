"""资金费率Z-score — 当前资金费率相对历史均值的标准化偏离（仅合约）。"""
from __future__ import annotations

from typing import ClassVar, List, Set

import numpy as np

from ...base import BaseFactorComputer
from ...context import FactorContext
from ...enums import FactorCategory, FactorTier, MarketType, SignalDirection
from ...models import FactorResult, FundingRateData


class FundingRateZScoreComputer(BaseFactorComputer):
    factor_name: ClassVar[str] = "funding_rate_zscore"
    category: ClassVar[FactorCategory] = FactorCategory.DERIVATIVES
    display_name: ClassVar[str] = "资金费率Z-score"
    description: ClassVar[str] = "资金费率标准化偏离，极端值=多头/空头拥挤，反转预警。"
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
        mean_rate = float(np.mean(rates))
        std_rate = float(np.std(rates, ddof=1))
        if std_rate == 0:
            zscore = 0.0
        else:
            zscore = (current_rate - mean_rate) / std_rate

        clamped = max(-1.0, min(1.0, zscore / 3.0))

        evidence = [
            self._evidence(
                data_point=f"当前费率: {current_rate:.6f}, 均值: {mean_rate:.6f}, Z-score: {zscore:+.2f}",
                interpretation=f"资金费率{'极端偏高' if zscore > 2.5 else '极端偏低' if zscore < -2.5 else '正常'}",
                implication="极端正Z-score=多头拥挤回调风险，极端负Z-score=空头拥挤逼空风险",
                confidence=0.75 if abs(zscore) > 2.0 else 0.50,
            ),
        ]

        if zscore > 2.5:
            direction = SignalDirection.STRONG_BEARISH
            action = "资金费率极端正偏离，多头拥挤，强烈看跌，多单止盈甚至反手做空。"
        elif zscore > 1.5:
            direction = SignalDirection.BEARISH
            action = "资金费率偏高，多头拥挤，注意回调风险。"
        elif zscore < -2.5:
            direction = SignalDirection.STRONG_BULLISH
            action = "资金费率极端负偏离，空头拥挤，逼空风险，空单止盈做多。"
        elif zscore < -1.5:
            direction = SignalDirection.BULLISH
            action = "资金费率偏低，空头拥挤，关注反弹。"
        else:
            direction = SignalDirection.NEUTRAL
            action = "资金费率正常范围。"

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=float(zscore),
            confidence=0.75 if abs(zscore) > 2.0 else 0.40,
            data_freshness_ms=0, data_completeness=1.0, weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"current_rate": float(current_rate), "mean": float(mean_rate), "zscore": float(zscore)},
                evidence,
                f"资金费率Z-score: {zscore:+.2f}。{action}",
                action,
                limitations=["资金费率历史分布可能随市场结构变化而变化"],
            ),
        )
