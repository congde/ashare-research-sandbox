# -*- coding: utf-8 -*-
"""资金流因子参数化基类 — 消除 spot/contract 6 对重复代码。

每个基类包含完整的 compute() 算法逻辑。
spot/contract 子类只需声明 ClassVar 覆写元数据、数据源字段和中文文本。
"""

from __future__ import annotations

from typing import ClassVar, List

from ..base import BaseFactorComputer
from ..context import FactorContext
from ..enums import DataGranularity, FactorCategory, FactorTier, SignalDirection
from ..models import FactorResult, GranularityValue
from ..utils import (
    clamp_score,
    directional_consensus,
    extract_inflows,
    gran_to_tpe,
    normalize_to_bipolar,
    score_to_direction,
)

# ═══════════════════════════════════════════════════════════════════════════════
# 1. 多周期资金趋势一致性
# ═══════════════════════════════════════════════════════════════════════════════


class _BaseConsistencyComputer(BaseFactorComputer):
    """多周期资金趋势一致性 — spot/contract 通用逻辑。"""

    category: ClassVar[FactorCategory] = FactorCategory.FUND_FLOW
    requires_data: ClassVar[List[str]] = ["realtime_fund"]

    # ── 子类覆写 ──
    _DATA_FIELD: ClassVar[str] = ""
    _MARKET_LABEL: ClassVar[str] = ""
    _ACTION_STRONG_BULL: ClassVar[str] = ""
    _ACTION_STRONG_BEAR: ClassVar[str] = ""
    _ACTION_BULLISH: ClassVar[str] = ""
    _ACTION_BEARISH: ClassVar[str] = ""
    _ACTION_NEUTRAL: ClassVar[str] = "观望，等待各周期方向趋于一致。"
    _IMPLICATION_ALL_BULL: ClassVar[str] = ""
    _IMPLICATION_ALL_BEAR: ClassVar[str] = ""
    _IMPLICATION_MIXED: ClassVar[str] = "各周期方向不一致，趋势不明朗"
    _COUNTER_STRONG_BULL: ClassVar[str] = ""
    _COUNTER_STRONG_BEAR: ClassVar[str] = ""

    _ALL_GRANULARITIES = [
        DataGranularity.M5, DataGranularity.M15, DataGranularity.M30,
        DataGranularity.H1, DataGranularity.H8, DataGranularity.H24,
    ]
    _SHORT = {DataGranularity.M5, DataGranularity.M15}
    _MEDIUM = {DataGranularity.M30, DataGranularity.H1}
    _LONG = {DataGranularity.H8, DataGranularity.H24}

    async def compute(self, ctx: FactorContext) -> FactorResult:
        rt = ctx.data.get("realtime_fund")
        if rt is None:
            return self._inconclusive("无实时资金数据。")

        raw_inflows = extract_inflows(getattr(rt, self._DATA_FIELD), self._ALL_GRANULARITIES)

        combined: dict[DataGranularity, float] = {}
        for gran in self._ALL_GRANULARITIES:
            combined[gran] = raw_inflows.get(gran, 0.0)

        def _group_sign(group: set[DataGranularity]) -> float:
            vals = [combined[g] for g in group if g in combined]
            if not vals:
                return 0.0
            avg = sum(vals) / len(vals)
            return 1.0 if avg < 0 else (-1.0 if avg > 0 else 0.0)

        short_sign = _group_sign(self._SHORT)
        medium_sign = _group_sign(self._MEDIUM)
        long_sign = _group_sign(self._LONG)

        signs = [short_sign, medium_sign, long_sign]
        bull_count = sum(1 for s in signs if s > 0)
        bear_count = sum(1 for s in signs if s < 0)

        total_outflow = sum(v for v in combined.values())
        overall_sign = 1 if total_outflow < 0 else (-1 if total_outflow > 0 else 0)

        evidence = []
        for label, group in [("短期(5m/15m)", self._SHORT), ("中期(30m/1h)", self._MEDIUM), ("长期(6h/24h)", self._LONG)]:
            vals = [combined[g] for g in group if g in combined]
            if vals:
                avg = sum(vals) / len(vals)
                direction = "净流出" if avg < 0 else "净流入"
                evidence.append(self._evidence(
                    data_point=f"{label} {self._MARKET_LABEL}均值: {avg:,.0f} USD",
                    interpretation=f"{label}{self._MARKET_LABEL}资金{direction}",
                    implication=self._IMPLICATION_ALL_BULL if bull_count == 3
                    else (self._IMPLICATION_ALL_BEAR if bear_count == 3
                          else self._IMPLICATION_MIXED),
                    confidence=0.85 if abs(avg) > 1_000_000 else 0.55,
                ))

        if bull_count == 3:
            consensus_score = 1.0
        elif bear_count == 3:
            consensus_score = -1.0
        elif bull_count == 2:
            consensus_score = 0.4
        elif bear_count == 2:
            consensus_score = -0.4
        else:
            consensus_score = 0.0

        magnitude_factor = min(1.0, abs(total_outflow) / 50_000_000.0) * 0.5
        final = consensus_score + (overall_sign * magnitude_factor)
        clamped = max(-1.0, min(1.0, final))

        if clamped > 0.5:
            direction = SignalDirection.STRONG_BULLISH
            action = self._ACTION_STRONG_BULL
            counter = self._COUNTER_STRONG_BULL
        elif clamped > 0.15:
            direction = SignalDirection.BULLISH
            action = self._ACTION_BULLISH
            counter = ""
        elif clamped < -0.5:
            direction = SignalDirection.STRONG_BEARISH
            action = self._ACTION_STRONG_BEAR
            counter = self._COUNTER_STRONG_BEAR
        elif clamped < -0.15:
            direction = SignalDirection.BEARISH
            action = self._ACTION_BEARISH
            counter = ""
        else:
            direction = SignalDirection.NEUTRAL
            action = self._ACTION_NEUTRAL
            counter = ""

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=consensus_score,
            confidence=0.70 + abs(consensus_score) * 0.25,
            data_freshness_ms=0, data_completeness=1.0,
            weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"short_sign": short_sign, "medium_sign": medium_sign, "long_sign": long_sign,
                 "bull_count": bull_count, "bear_count": bear_count},
                evidence,
                f"多周期一致性: bull={bull_count}/3, bear={bear_count}/3。一致性得分: {final:+.3f}。",
                action,
                limitations=["周期分组为人为划分，不同分组策略可能得到不同结论"],
                counter_argument=counter,
            ),
        )

    def _inconclusive(self, reason: str) -> FactorResult:
        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=SignalDirection.INCONCLUSIVE,
            normalized_score=0.0, raw_value=0.0, confidence=0.0,
            data_completeness=0.0, weight=0.0,
            trace=self._build_trace(self.factor_name, {}, [], reason),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 2. 多粒度资金净流入
# ═══════════════════════════════════════════════════════════════════════════════


class _BaseInflowComputer(BaseFactorComputer):
    """多粒度资金净流入 — spot/contract 通用逻辑。"""

    category: ClassVar[FactorCategory] = FactorCategory.FUND_FLOW
    requires_data: ClassVar[List[str]] = ["realtime_fund"]

    # ── 子类覆写 ──
    _DATA_FIELD: ClassVar[str] = ""
    _MARKET_LABEL: ClassVar[str] = ""
    _OUTFLOW_LABEL: ClassVar[str] = ""
    _INFLOW_LABEL: ClassVar[str] = ""
    _OUTFLOW_IMPLICATION: ClassVar[str] = ""
    _INFLOW_IMPLICATION: ClassVar[str] = ""
    _ACTION_STRONG_BULL: ClassVar[str] = ""
    _ACTION_STRONG_BEAR: ClassVar[str] = ""
    _COUNTER_STRONG_BULL: ClassVar[str] = ""
    _COUNTER_STRONG_BEAR: ClassVar[str] = ""
    _CONCLUSION_STRONG_BULL: ClassVar[str] = ""
    _CONCLUSION_BULLISH: ClassVar[str] = ""
    _CONCLUSION_STRONG_BEAR: ClassVar[str] = ""
    _LIMITATION_1: ClassVar[str] = ""
    _LIMITATION_2: ClassVar[str] = "5m/15m粒度噪声较大"

    _GRANULARITIES = [
        DataGranularity.M5, DataGranularity.M15, DataGranularity.M30,
        DataGranularity.H1, DataGranularity.H8, DataGranularity.H24,
    ]
    _GRAN_WEIGHTS = {
        DataGranularity.M5: 0.4, DataGranularity.M15: 0.4,
        DataGranularity.M30: 0.5, DataGranularity.H1: 0.7,
        DataGranularity.H8: 0.9, DataGranularity.H24: 1.2,
    }

    async def compute(self, ctx: FactorContext) -> FactorResult:
        rt = ctx.data.get("realtime_fund")
        if rt is None:
            return self._inconclusive("无数据，无法计算资金净流入信号。")

        inflows = extract_inflows(getattr(rt, self._DATA_FIELD), self._GRANULARITIES)

        evidence = []
        gran_results: List[GranularityValue] = []
        per_gran_scores: List[float] = []
        total_weight = 0.0
        weighted_sum = 0.0

        for gran in self._GRANULARITIES:
            combined = inflows.get(gran, 0.0)
            gw = self._GRAN_WEIGHTS.get(gran, 0.5)
            normed = normalize_to_bipolar(combined, center=0.0, scale=10_000_000.0)

            gran_results.append(GranularityValue(granularity=gran, value=combined, weight=min(gw, 1.0)))
            per_gran_scores.append(normed)
            weighted_sum += normed * gw
            total_weight += gw

            if abs(combined) > 100_000:
                direction = self._OUTFLOW_LABEL if combined < 0 else self._INFLOW_LABEL
                evidence.append(self._evidence(
                    data_point=f"{gran.value} {self._MARKET_LABEL}净流入: {combined:,.0f} USD",
                    interpretation=f"{gran.value}级别{self._MARKET_LABEL}资金{direction}",
                    implication=self._OUTFLOW_IMPLICATION if combined < 0 else self._INFLOW_IMPLICATION,
                    confidence=0.80 if abs(combined) > 5_000_000 else 0.55,
                ))

        if total_weight == 0:
            return self._inconclusive("无数据。")

        consensus = directional_consensus(per_gran_scores)
        aggregate = weighted_sum / total_weight
        clamped = max(-1.0, min(1.0, aggregate * 1.2 + consensus * 0.3))

        if clamped > 0.35:
            direction = SignalDirection.STRONG_BULLISH
            action = self._ACTION_STRONG_BULL
            counter = self._COUNTER_STRONG_BULL
        elif clamped > 0.1:
            direction = SignalDirection.BULLISH
            action = "偏多，关注 1H 级别确认。"
            counter = ""
        elif clamped < -0.35:
            direction = SignalDirection.STRONG_BEARISH
            action = self._ACTION_STRONG_BEAR
            counter = self._COUNTER_STRONG_BEAR
        elif clamped < -0.1:
            direction = SignalDirection.BEARISH
            action = "偏空，注意抛压风险。"
            counter = ""
        else:
            direction = SignalDirection.NEUTRAL
            action = "观望，等待资金方向明朗。"
            counter = ""

        conclusion = f"多粒度资金净流入得分 {clamped:+.3f}。各周期一致性={consensus:+.2f}。"
        if direction == SignalDirection.STRONG_BULLISH:
            conclusion += self._CONCLUSION_STRONG_BULL
        elif direction == SignalDirection.BULLISH:
            conclusion += self._CONCLUSION_BULLISH
        elif direction == SignalDirection.STRONG_BEARISH:
            conclusion += self._CONCLUSION_STRONG_BEAR

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=aggregate,
            confidence=min(0.95, 0.50 + abs(consensus) * 0.30 + (total_weight / 6.0) * 0.15),
            data_freshness_ms=0,
            data_completeness=min(1.0, total_weight / sum(self._GRAN_WEIGHTS.values())),
            weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"inflows": {g.value: inflows.get(g, 0.0) for g in self._GRANULARITIES}},
                evidence, conclusion, action,
                limitations=[self._LIMITATION_1, self._LIMITATION_2],
                counter_argument=counter,
            ),
            granularity_breakdown=gran_results,
        )

    def _inconclusive(self, reason: str) -> FactorResult:
        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=SignalDirection.INCONCLUSIVE,
            normalized_score=0.0, raw_value=0.0, confidence=0.0,
            data_completeness=0.0, weight=0.0,
            trace=self._build_trace(self.factor_name, {}, [], reason),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 资金市值比
# ═══════════════════════════════════════════════════════════════════════════════


class _BaseMarketCapRatioComputer(BaseFactorComputer):
    """资金市值比 — spot/contract 通用逻辑。"""

    category: ClassVar[FactorCategory] = FactorCategory.FUND_FLOW
    requires_data: ClassVar[List[str]] = ["market_cap_ratio"]

    # ── 子类覆写 ──
    _PRIMARY_IS_SPOT: ClassVar[bool] = True
    _SCORE_MULTIPLIER: ClassVar[float] = 1.0
    _DIRECTION_THRESHOLD: ClassVar[float] = 0.2
    _CONFIDENCE_HIGH: ClassVar[float] = 0.70
    _CONFIDENCE_LOW: ClassVar[float] = 0.45
    _MARKET_LABEL: ClassVar[str] = ""
    _PRIMARY_LABEL: ClassVar[str] = ""
    _OTHER_LABEL: ClassVar[str] = ""
    _IMPLICATION_HIGH: ClassVar[str] = ""
    _IMPLICATION_LOW: ClassVar[str] = ""
    _ACTION_BULLISH: ClassVar[str] = ""
    _ACTION_BEARISH: ClassVar[str] = ""
    _EVI_PRIMARY_HIGH_TPL: ClassVar[str] = ""
    _EVI_PRIMARY_LOW_TPL: ClassVar[str] = ""
    _EVI_BIAS_HIGH: ClassVar[str] = ""
    _EVI_BIAS_HIGH_IMPLICATION: ClassVar[str] = ""
    _EVI_BIAS_LOW: ClassVar[str] = ""
    _EVI_BIAS_LOW_IMPLICATION: ClassVar[str] = ""
    _EXTREME_CAP_ENABLED: ClassVar[bool] = False
    _EXTREME_THRESHOLD: ClassVar[float] = 0.02
    _EXTREME_ACTION: ClassVar[str] = ""

    async def compute(self, ctx: FactorContext) -> FactorResult:
        ratio_data = ctx.data.get("market_cap_ratio")
        if ratio_data is None:
            return self._inconclusive("无资金市值比数据。")

        spot_ratio = ratio_data.spot_market_cap_ratio
        contract_ratio = ratio_data.contract_market_cap_ratio

        if spot_ratio == 0.0 and contract_ratio == 0.0:
            return self._inconclusive("无资金市值比数据。")

        primary_ratio = spot_ratio if self._PRIMARY_IS_SPOT else contract_ratio
        other_ratio = contract_ratio if self._PRIMARY_IS_SPOT else spot_ratio

        evidence = []

        if abs(primary_ratio) > 0.001:
            evidence.append(self._evidence(
                data_point=f"{self._PRIMARY_LABEL}资金市值比: {primary_ratio:.4%}",
                interpretation=f"{self._PRIMARY_LABEL}资金净流入占市值 {abs(primary_ratio):.4%}，"
                f"比例{'较高' if abs(primary_ratio) > 0.01 else '中等'}",
                implication=self._IMPLICATION_HIGH if abs(primary_ratio) > 0.01
                else self._IMPLICATION_LOW,
                confidence=self._CONFIDENCE_HIGH if abs(primary_ratio) > 0.01 else self._CONFIDENCE_LOW,
            ))

        if spot_ratio != 0 and contract_ratio != 0:
            primary_bias = abs(primary_ratio) / (abs(spot_ratio) + abs(contract_ratio) + 0.0001)
            if primary_bias > 0.7:
                evidence.append(self._evidence(
                    data_point=f"{self._PRIMARY_LABEL}市值比: {primary_ratio:.4%} vs {self._OTHER_LABEL}: {other_ratio:.4%}",
                    interpretation=self._EVI_BIAS_HIGH.format(prim=self._PRIMARY_LABEL, other=self._OTHER_LABEL),
                    implication=self._EVI_BIAS_HIGH_IMPLICATION,
                    confidence=0.65,
                ))
            elif primary_bias < 0.3:
                evidence.append(self._evidence(
                    data_point=f"{self._OTHER_LABEL}市值比({other_ratio:.4%}) >> {self._PRIMARY_LABEL}({primary_ratio:.4%})",
                    interpretation=self._EVI_BIAS_LOW.format(prim=self._PRIMARY_LABEL, other=self._OTHER_LABEL),
                    implication=self._EVI_BIAS_LOW_IMPLICATION,
                    confidence=0.65,
                ))

        magnitude_score = normalize_to_bipolar(abs(primary_ratio), center=0, scale=0.05)
        direction_sign = 1 if primary_ratio < 0 else (-1 if primary_ratio > 0 else 0)
        clamped = max(-1.0, min(1.0, magnitude_score * direction_sign * self._SCORE_MULTIPLIER))

        # dampen when the other side dominates
        other_abs = abs(other_ratio)
        primary_abs = abs(primary_ratio)
        if other_abs > primary_abs * 3 and other_abs > 0.01:
            clamped *= 0.5

        is_extreme = False
        if self._EXTREME_CAP_ENABLED and abs(primary_ratio) > self._EXTREME_THRESHOLD:
            is_extreme = True
            clamped = max(-0.25, min(0.25, clamped))

        if is_extreme:
            direction = SignalDirection.NEUTRAL_BEARISH
            action = self._EXTREME_ACTION
        elif clamped > self._DIRECTION_THRESHOLD:
            direction = SignalDirection.BULLISH
            action = self._ACTION_BULLISH
        elif clamped < -self._DIRECTION_THRESHOLD:
            direction = SignalDirection.BEARISH
            action = self._ACTION_BEARISH
        else:
            direction = SignalDirection.NEUTRAL
            action = "观望。"

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=primary_ratio,
            confidence=self._CONFIDENCE_HIGH if abs(primary_ratio) > 0.01 else self._CONFIDENCE_LOW,
            data_freshness_ms=0, data_completeness=1.0,
            weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"spot": spot_ratio, "contract": contract_ratio, "primary": primary_ratio},
                evidence,
                f"{self._PRIMARY_LABEL}资金市值比: {primary_ratio:.4%}"
                f"{'（极端值，波动预警）' if is_extreme else ''}。"
                f"现货: {spot_ratio:.4%}，合约: {contract_ratio:.4%}。",
                action,
                limitations=["市值数据可能滞后更新"],
            ),
        )

    def _inconclusive(self, reason: str) -> FactorResult:
        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=SignalDirection.INCONCLUSIVE,
            normalized_score=0.0, raw_value=0.0, confidence=0.0,
            data_completeness=0.0, weight=0.0,
            trace=self._build_trace(self.factor_name, {}, [], reason),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 主力资金积累
# ═══════════════════════════════════════════════════════════════════════════════


class _BaseMaxInflowComputer(BaseFactorComputer):
    """主力资金积累 — spot/contract 通用逻辑。"""

    category: ClassVar[FactorCategory] = FactorCategory.FUND_FLOW
    requires_data: ClassVar[List[str]] = ["realtime_fund"]

    # ── 子类覆写 ──
    _PRIMARY_IS_SPOT: ClassVar[bool] = True
    _MARKET_LABEL: ClassVar[str] = ""
    _OTHER_LABEL: ClassVar[str] = ""
    _DIR_FACTOR_SPOT_DOM: ClassVar[float] = 1.0
    _DIR_FACTOR_CONTRACT_DOM: ClassVar[float] = -0.5
    _DIR_FACTOR_BALANCED: ClassVar[float] = 0.3
    _FOCUS_SPOT_DOM: ClassVar[str] = ""
    _FOCUS_CONTRACT_DOM: ClassVar[str] = ""
    _FOCUS_BALANCED: ClassVar[str] = ""
    _IMPLICATION_SPOT_DOM: ClassVar[str] = ""
    _IMPLICATION_CONTRACT_DOM: ClassVar[str] = ""
    _IMPLICATION_BALANCED: ClassVar[str] = ""
    _CONFIDENCE_HIGH: ClassVar[float] = 0.70
    _CONFIDENCE_LOW: ClassVar[float] = 0.50
    _ACTION_BULLISH: ClassVar[str] = ""
    _ACTION_BEARISH: ClassVar[str] = ""

    async def compute(self, ctx: FactorContext) -> FactorResult:
        rt = ctx.data.get("realtime_fund")
        if rt is None:
            return self._inconclusive("无主力积累数据。")

        spot_max = rt.spot_max_inflow
        contract_max = rt.contract_max_inflow

        if spot_max == 0.0 and contract_max == 0.0:
            return self._inconclusive("无主力积累数据。")

        primary_max = spot_max if self._PRIMARY_IS_SPOT else contract_max
        other_max = contract_max if self._PRIMARY_IS_SPOT else spot_max

        primary_abs_norm = normalize_to_bipolar(abs(primary_max), center=0, scale=50_000_000)

        spot_abs = abs(spot_max)
        contract_abs = abs(contract_max)
        if spot_abs > contract_abs * 1.5:
            direction_factor = self._DIR_FACTOR_SPOT_DOM
            focus = self._FOCUS_SPOT_DOM
            implication = self._IMPLICATION_SPOT_DOM
        elif contract_abs > spot_abs * 1.5:
            direction_factor = self._DIR_FACTOR_CONTRACT_DOM
            focus = self._FOCUS_CONTRACT_DOM
            implication = self._IMPLICATION_CONTRACT_DOM
        else:
            direction_factor = self._DIR_FACTOR_BALANCED
            focus = self._FOCUS_BALANCED
            implication = self._IMPLICATION_BALANCED

        evidence = [self._evidence(
            data_point=f"{self._MARKET_LABEL}主力最大积累: {primary_max:,.0f} USD ({self._OTHER_LABEL}: {other_max:,.0f})",
            interpretation=f"{self._MARKET_LABEL}主力曾大举介入(积累={primary_max:,.0f})，{focus}",
            implication=implication,
            confidence=self._CONFIDENCE_HIGH if abs(primary_max) > 10_000_000 else self._CONFIDENCE_LOW,
        )]

        score = primary_abs_norm * direction_factor
        direction = score_to_direction(score)

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamp_score(score),
            raw_value=primary_max,
            confidence=self._CONFIDENCE_HIGH if abs(primary_max) > 10_000_000 else self._CONFIDENCE_LOW,
            data_freshness_ms=0,
            data_completeness=1.0 if primary_max != 0 else 0.3,
            weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"spot_max_inflow": spot_max, "contract_max_inflow": contract_max},
                evidence,
                f"主力{self._MARKET_LABEL}积累: {primary_max:,.0f}。",
                self._action(direction),
                limitations=["Max inflow 是历史值，当前主力可能已改变方向。"],
            ),
        )

    def _action(self, direction: SignalDirection) -> str:
        if direction in (SignalDirection.STRONG_BULLISH, SignalDirection.BULLISH):
            return self._ACTION_BULLISH
        if direction in (SignalDirection.STRONG_BEARISH, SignalDirection.BEARISH):
            return self._ACTION_BEARISH
        if direction == SignalDirection.NEUTRAL_BULLISH:
            return "偏多，可关注。"
        if direction == SignalDirection.NEUTRAL_BEARISH:
            return "偏空，谨慎。"
        return "观望。"

    def _inconclusive(self, reason: str) -> FactorResult:
        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=SignalDirection.INCONCLUSIVE,
            normalized_score=0.0, raw_value=0.0, confidence=0.0,
            data_completeness=0.0, weight=0.0,
            trace=self._build_trace(self.factor_name, {}, [], reason),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 5. 资金积累持续性
# ═══════════════════════════════════════════════════════════════════════════════


class _BasePersistenceComputer(BaseFactorComputer):
    """资金积累持续性 — spot/contract 通用逻辑。"""

    category: ClassVar[FactorCategory] = FactorCategory.FUND_FLOW
    requires_data: ClassVar[List[str]] = ["realtime_fund"]

    # ── 子类覆写 ──
    _DATA_FIELD: ClassVar[str] = ""
    _MARKET_LABEL: ClassVar[str] = ""
    _INCREASING_INTERPRETATION: ClassVar[str] = ""
    _INCREASING_IMPLICATION: ClassVar[str] = ""
    _PERSISTENCE_DIRECTION: ClassVar[SignalDirection] = SignalDirection.NEUTRAL_BULLISH
    _CONFIDENCE: ClassVar[float] = 0.55
    _ACTION_ALERT: ClassVar[str] = ""
    _ACTION_NEUTRAL: ClassVar[str] = "观望。"

    async def compute(self, ctx: FactorContext) -> FactorResult:
        rt = ctx.data.get("realtime_fund")
        if rt is None:
            return self._inconclusive("无积累持续性数据。")

        records = getattr(rt, self._DATA_FIELD)
        short_max = 0.0
        mid_max = 0.0
        long_max = 0.0

        for r in records:
            tpe_raw = getattr(r, "time_particle_enum", None)
            if tpe_raw is None:
                continue
            tpe = int(tpe_raw) if isinstance(tpe_raw, str) else tpe_raw
            val = abs(r.trade_inflow)

            if tpe in (5, 15, 30):
                short_max = max(short_max, val)
            elif tpe in (101, 106):
                mid_max = max(mid_max, val)
            elif tpe in (124,):
                long_max = max(long_max, val)

        if short_max == 0.0 and mid_max == 0.0 and long_max == 0.0:
            return self._inconclusive("无积累持续性数据。")

        persistence = self._safe_div(long_max, mid_max, 0.0)
        is_increasing = short_max < mid_max < long_max
        is_decreasing = short_max > long_max

        evidence = [self._evidence(
            data_point=f"{self._MARKET_LABEL} 短期={short_max:,.0f}, 中期={mid_max:,.0f}, 长期={long_max:,.0f}",
            interpretation=self._INCREASING_INTERPRETATION if is_increasing
            else (f"{self._MARKET_LABEL}主力短线博弈，无中长期布局" if is_decreasing
                  else f"{self._MARKET_LABEL}主力介入力度中等"),
            implication=self._INCREASING_IMPLICATION if is_increasing
            else ("短线资金为主，谨慎看待" if is_decreasing else ""),
            confidence=0.60,
        )]

        clamped = max(-0.3, min(0.3, persistence * 0.3 if persistence < 1.0 else persistence * 0.2))
        direction = self._PERSISTENCE_DIRECTION if clamped > 0.05 else SignalDirection.NEUTRAL

        action = self._ACTION_ALERT if direction != SignalDirection.NEUTRAL else self._ACTION_NEUTRAL

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=persistence,
            confidence=self._CONFIDENCE,
            data_freshness_ms=0, data_completeness=1.0,
            weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"short_max": short_max, "mid_max": mid_max, "long_max": long_max},
                evidence,
                f"积累持续性: {persistence:.3f}。",
                action,
                limitations=["积累持续性基于历史数据，方向可能已改变"],
            ),
        )

    def _inconclusive(self, reason: str) -> FactorResult:
        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=SignalDirection.INCONCLUSIVE,
            normalized_score=0.0, raw_value=0.0, confidence=0.0,
            data_completeness=0.0, weight=0.0,
            trace=self._build_trace(self.factor_name, {}, [], reason),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 6. 资金快照拐点检测
# ═══════════════════════════════════════════════════════════════════════════════


class _BaseSnapshotComputer(BaseFactorComputer):
    """资金快照拐点检测 — spot/contract 通用逻辑。"""

    category: ClassVar[FactorCategory] = FactorCategory.FUND_FLOW
    requires_data: ClassVar[List[str]] = ["fund_snapshot", "realtime_fund"]

    # ── 子类覆写 ──
    _SNAP_DATA_FIELD: ClassVar[str] = ""
    _RT_DATA_FIELD: ClassVar[str] = ""
    _MARKET_LABEL: ClassVar[str] = ""
    _SIGN_CHANGE_SCORE: ClassVar[float] = 0.4
    _CLAMP_LOW: ClassVar[float] = -0.6
    _CLAMP_HIGH: ClassVar[float] = 0.6
    _DIRECTION_THRESHOLD: ClassVar[float] = 0.2
    _ACTION_BULLISH: ClassVar[str] = ""
    _ACTION_BEARISH: ClassVar[str] = ""
    _ACTION_NEUTRAL: ClassVar[str] = "资金方向无明显反转，观望。"
    _CONCLUSION_TPL: ClassVar[str] = ""

    _KEY_GRANULARITIES = [DataGranularity.H1, DataGranularity.H8, DataGranularity.H24]
    _GRAN_WEIGHTS = {DataGranularity.H1: 0.6, DataGranularity.H8: 0.8, DataGranularity.H24: 1.0}

    async def compute(self, ctx: FactorContext) -> FactorResult:
        snapshot = ctx.data.get("fund_snapshot")
        rt = ctx.data.get("realtime_fund")

        if snapshot is None and rt is None:
            return self._inconclusive("无快照数据。")

        def _build_index(records) -> dict:
            idx: dict = {}
            for r in (records or []):
                tpe = getattr(r, "time_particle_enum", None)
                if tpe is not None:
                    idx[int(tpe)] = float(getattr(r, "trade_inflow", 0) or 0)
            return idx

        snap_idx = _build_index(getattr(snapshot, self._SNAP_DATA_FIELD)) if snapshot else {}
        rt_idx = _build_index(getattr(rt, self._RT_DATA_FIELD)) if rt else {}

        evidence = []
        total_score = 0.0
        total_weight = 0.0
        sign_changes = 0

        for gran in self._KEY_GRANULARITIES:
            tpe = gran_to_tpe(gran)
            snap_val = snap_idx.get(tpe, 0.0)
            rt_val = rt_idx.get(tpe, 0.0)

            if snap_val == 0.0 and rt_val == 0.0:
                continue

            gw = self._GRAN_WEIGHTS.get(gran, 0.5)
            snap_sign = -1 if snap_val < 0 else (1 if snap_val > 0 else 0)
            rt_sign = -1 if rt_val < 0 else (1 if rt_val > 0 else 0)
            is_sign_change = snap_sign != 0 and rt_sign != 0 and snap_sign != rt_sign

            if is_sign_change:
                sign_changes += 1
                if snap_val < 0 and rt_val > 0:
                    gran_score = -self._SIGN_CHANGE_SCORE
                    interpretation = (
                        f"{gran.value} 由净流出({snap_val:,.0f})→净流入({rt_val:,.0f})，态度转空"
                    )
                else:
                    gran_score = self._SIGN_CHANGE_SCORE
                    interpretation = (
                        f"{gran.value} 由净流入({snap_val:,.0f})→净流出({rt_val:,.0f})，态度转多"
                    )
                total_score += gran_score * gw
            else:
                total_score += 0.0

            total_weight += gw

            evidence.append(self._evidence(
                data_point=f"{gran.value} 快照: {snap_val:,.0f} → 实时: {rt_val:,.0f} USD",
                interpretation=interpretation if is_sign_change
                else (f"{gran.value}资金方向延续"),
                implication="资金态度反转，可作为入场/出场信号" if is_sign_change
                else "资金方向延续",
                confidence=0.75 if is_sign_change else 0.45,
            ))

        if total_weight == 0:
            return self._inconclusive("无有效快照对比数据。")

        aggregate = total_score / total_weight
        clamped = max(self._CLAMP_LOW, min(self._CLAMP_HIGH, aggregate))

        if clamped > self._DIRECTION_THRESHOLD:
            direction = SignalDirection.BULLISH
            action = self._ACTION_BULLISH
        elif clamped < -self._DIRECTION_THRESHOLD:
            direction = SignalDirection.BEARISH
            action = self._ACTION_BEARISH
        else:
            direction = SignalDirection.NEUTRAL
            action = self._ACTION_NEUTRAL

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=aggregate,
            confidence=0.60 if sign_changes > 0 else 0.35,
            data_freshness_ms=0, data_completeness=1.0 if snapshot else 0.5,
            weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"sign_changes": sign_changes, "granularities_checked": len(evidence)},
                evidence,
                self._CONCLUSION_TPL.format(
                    label=self._MARKET_LABEL, changes=sign_changes, score=clamped,
                ),
                action,
                limitations=["快照时间点可能与当前不匹配", "仅分析 H1/H8/24H 三个关键粒度"],
            ),
        )

    def _inconclusive(self, reason: str) -> FactorResult:
        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=SignalDirection.INCONCLUSIVE,
            normalized_score=0.0, raw_value=0.0, confidence=0.0,
            data_completeness=0.0, weight=0.0,
            trace=self._build_trace(self.factor_name, {}, [], reason),
        )
