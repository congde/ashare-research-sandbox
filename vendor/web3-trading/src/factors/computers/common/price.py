"""价格相关因子 — 公共因子。

- 主力行为价格趋势：priceMarketType 指标（1=涨，2=跌）
- 推送价格涨跌幅：AI 信号推送后的历史涨跌表现
- 交易量：24h 总交易额
- 现货合约资金背离度：跨市场资金方向背离检测
"""
from __future__ import annotations

from typing import ClassVar, List

from ...base import BaseFactorComputer
from ...context import FactorContext
from ...enums import (
    DataGranularity,
    FactorCategory,
    FactorTier,
    SignalDirection,
)
from ...models import FactorResult
from ...utils import extract_inflows


class PriceMarketTypeComputer(BaseFactorComputer):
    """主力行为价格趋势 — priceMarketType 指标。"""

    factor_name: ClassVar[str] = "price_market_type"
    category: ClassVar[FactorCategory] = FactorCategory.MARKET_STRUCTURE
    display_name: ClassVar[str] = "主力行为价格趋势"
    description: ClassVar[str] = "基于主力行为的价格趋势（1=上涨，2=下跌）。"
    requires_data: ClassVar[List[str]] = ["price_indicators", "ai_chance"]

    async def compute(self, ctx: FactorContext) -> FactorResult:
        indicators = ctx.data.get("price_indicators") or []
        trend = 0
        if indicators:
            latest = indicators[-1]
            trend = int(getattr(latest, "price_market_type", 0) or 0)

        if trend == 0:
            ai_item = ctx.data.get("ai_chance")
            if ai_item is not None:
                trend = int(getattr(ai_item, "price_market_type", 0) or 0)

        if trend == 0:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "无价格趋势数据。"),
            )

        is_up = trend == 1
        evidence = [self._evidence(
            data_point=f"主力行为趋势: {'上涨' if is_up else '下跌'}",
            interpretation=f"主力行为指标显示短期{'看涨' if is_up else '看跌'}",
            implication="若与资金面一致（上涨+净流出），趋势更可靠" if is_up
            else "若与资金面一致（下跌+净流入），趋势更可靠",
            confidence=0.50,
        )]

        clamped = 0.15 if is_up else -0.15
        direction = SignalDirection.NEUTRAL_BULLISH if is_up else SignalDirection.NEUTRAL_BEARISH

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=float(trend),
            confidence=0.40,
            data_freshness_ms=0, data_completeness=1.0,
            weight=0.0,
            trace=self._build_trace(
                self.factor_name, {"trend": trend}, evidence,
                f"主力行为趋势: {'上涨' if is_up else '下跌'}。",
                limitations=["主力行为指标为AI模型输出，需与资金指标交叉验证"],
            ),
        )


class GainsDeclinesComputer(BaseFactorComputer):
    """推送价格涨跌幅 — AI 信号推送后历史表现。"""

    factor_name: ClassVar[str] = "gains_declines"
    category: ClassVar[FactorCategory] = FactorCategory.AI_COMPOSITE
    display_name: ClassVar[str] = "推送价格涨跌幅"
    description: ClassVar[str] = "AI 信号推送后的历史涨跌表现。"
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
                trace=self._build_trace(self.factor_name, {}, [], "无AI推送数据。"),
            )

        gains = float(getattr(ai_item, "gains", 0) or 0)
        declines = float(getattr(ai_item, "declines", 0) or 0)

        if gains == 0.0 and declines == 0.0:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.NEUTRAL,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.5, weight=0.0,
                trace=self._build_trace(self.factor_name,
                    {"gains": gains, "declines": declines}, [],
                    "推送涨跌幅数据为零。"),
            )

        net_swing = gains - declines
        evidence = [self._evidence(
            data_point=f"推送后涨幅: {gains:.1f}%, 跌幅: {declines:.1f}%",
            interpretation=f"推送后曾上涨{gains:.1f}%，下跌{declines:.1f}%",
            implication="历史推送信号偏多，参考价值高" if net_swing > 5
            else ("历史推送信号偏空" if net_swing < -5 else "信号方向不明"),
            confidence=0.55,
        )]

        clamped = max(-0.5, min(0.5, net_swing / 20.0))
        if net_swing > 5:
            direction = SignalDirection.NEUTRAL_BULLISH
        elif net_swing < -5:
            direction = SignalDirection.NEUTRAL_BEARISH
        else:
            direction = SignalDirection.NEUTRAL

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=net_swing,
            confidence=0.45,
            data_freshness_ms=0, data_completeness=1.0,
            weight=0.0,
            trace=self._build_trace(
                self.factor_name, {"gains": gains, "declines": declines, "net": net_swing},
                evidence,
                f"推送后涨跌幅: +{gains:.1f}% / -{declines:.1f}%。",
                "参考历史推送表现评估信号质量。",
                limitations=["历史表现不代表未来结果"],
            ),
        )


class TradeAmountComputer(BaseFactorComputer):
    """交易量 — 24h 总交易额。"""

    factor_name: ClassVar[str] = "trade_amount"
    category: ClassVar[FactorCategory] = FactorCategory.FUND_FLOW
    display_name: ClassVar[str] = "交易量"
    description: ClassVar[str] = "从 token_flow 获取的 24 小时总交易额。"
    requires_data: ClassVar[List[str]] = ["token_flow"]

    async def compute(self, ctx: FactorContext) -> FactorResult:
        flow = ctx.data.get("token_flow")
        if flow is None:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "无数据。"),
            )

        items = getattr(flow, "items", []) or []
        if not items:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "items为空。"),
            )

        latest = items[0]
        trade_amount = float(getattr(latest, "trade_amount", 0) or 0)

        if trade_amount == 0:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.NEUTRAL,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.3, weight=0.0,
                trace=self._build_trace(self.factor_name, {"trade_amount": 0}, [],
                    "交易量为零。"),
            )

        evidence = [self._evidence(
            data_point=f"24h交易额: {trade_amount:,.0f} USD",
            interpretation=f"交易量{'高' if trade_amount > 100_000_000 else '中等' if trade_amount > 10_000_000 else '低'}",
            implication="交易量极端放大往往伴随波动加剧或趋势反转",
            confidence=0.40,
        )]

        # 弱信号：交易量反映市场活跃度，高量=流动性好偏正面，极低量=流动性风险偏负面
        if trade_amount > 100_000_000:
            clamped = 0.10
            direction = SignalDirection.NEUTRAL_BULLISH
            action = "交易量活跃，市场流动性充足。"
        elif trade_amount > 10_000_000:
            clamped = 0.03
            direction = SignalDirection.NEUTRAL
            action = "交易量正常。"
        elif trade_amount > 1_000_000:
            clamped = 0.0
            direction = SignalDirection.NEUTRAL
            action = "交易量偏低。"
        else:
            clamped = -0.08
            direction = SignalDirection.NEUTRAL_BEARISH
            action = "交易量极低，流动性不足风险。"

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=trade_amount,
            confidence=0.35,
            data_freshness_ms=0, data_completeness=1.0,
            weight=0.0,
            trace=self._build_trace(
                self.factor_name, {"trade_amount": trade_amount}, evidence,
                f"24h交易额: {trade_amount:,.0f} USD。",
                action,
                limitations=["交易量不提供方向信号，需与其他因子结合"],
            ),
        )


class SpotContractDivergenceComputer(BaseFactorComputer):
    """现货合约资金背离度 — 跨市场资金方向背离检测。

    现货流出+合约流入 = 主力囤币+散户做空 = 强看涨。
    现货流入+合约流出 = 主力派发+合约平空 = 强看跌。
    仅在同时有现货和合约数据时有意义。
    """

    factor_name: ClassVar[str] = "spot_contract_divergence"
    category: ClassVar[FactorCategory] = FactorCategory.FUND_FLOW
    display_name: ClassVar[str] = "现货合约资金背离度"
    description: ClassVar[str] = "现货与合约净流入之间的方向性背离度。"
    requires_data: ClassVar[List[str]] = ["realtime_fund"]

    _KEY_GRANULARITIES = [DataGranularity.H1, DataGranularity.H8, DataGranularity.H24]
    _GRAN_WEIGHTS = {DataGranularity.H1: 0.6, DataGranularity.H8: 0.8, DataGranularity.H24: 1.0}

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
                trace=self._build_trace(self.factor_name, {}, [], "无实时资金数据。"),
            )

        spot_inflows = extract_inflows(rt.spot_goods_list, self._KEY_GRANULARITIES)
        contract_inflows = extract_inflows(rt.contract_list, self._KEY_GRANULARITIES)

        evidence = []
        total_score = 0.0
        total_weight = 0.0

        for gran in self._KEY_GRANULARITIES:
            spot_val = spot_inflows.get(gran, 0.0)
            contract_val = contract_inflows.get(gran, 0.0)
            gw = self._GRAN_WEIGHTS.get(gran, 0.5)

            spot_sign = 1 if spot_val > 0 else (-1 if spot_val < 0 else 0)
            contract_sign = 1 if contract_val > 0 else (-1 if contract_val < 0 else 0)
            is_divergent = spot_sign != 0 and contract_sign != 0 and spot_sign != contract_sign

            if is_divergent:
                if spot_val < 0 and contract_val > 0:
                    gran_score = 0.8
                    interpretation = (
                        f"现货净流出({spot_val:,.0f})，合约净流入({contract_val:,.0f})"
                        f"——主力囤币+合约做空，强看涨信号"
                    )
                elif spot_val > 0 and contract_val < 0:
                    gran_score = -0.8
                    interpretation = (
                        f"现货净流入({spot_val:,.0f})，合约净流出({contract_val:,.0f})"
                        f"——主力派发+合约平空，强看跌信号"
                    )
                else:
                    gran_score = 0.0
                    interpretation = "现货与合约背离但方向不明确"

                total_score += gran_score * gw
                total_weight += gw

                evidence.append(self._evidence(
                    data_point=f"{gran.value} spot={spot_val:,.0f}, contract={contract_val:,.0f}",
                    interpretation=interpretation,
                    implication="主力现货囤币而散户合约做空，中期看涨" if gran_score > 0
                    else ("主力现货派发，中期看跌" if gran_score < 0 else ""),
                    confidence=0.80 if abs(gran_score) > 0.5 else 0.55,
                ))
            else:
                total_weight += gw * 0.3

        if total_weight == 0 or not evidence:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.NEUTRAL,
                normalized_score=0.0, raw_value=0.0, confidence=0.5,
                data_completeness=1.0, weight=0.0,
                trace=self._build_trace(
                    self.factor_name, {}, [],
                    "现货与合约资金方向一致，无背离信号。",
                    limitations=["仅分析 H1/H6/24H 窗口"],
                ),
            )

        aggregate = total_score / total_weight if total_weight > 0 else 0.0
        clamped = max(-1.0, min(1.0, aggregate))

        if clamped > 0.3:
            direction = SignalDirection.STRONG_BULLISH
            action = "现货囤币+合约做空背离，强看涨，可积极做多。"
        elif clamped > 0.08:
            direction = SignalDirection.BULLISH
            action = "偏看涨。"
        elif clamped < -0.3:
            direction = SignalDirection.STRONG_BEARISH
            action = "现货派发+合约平空背离，强看跌，应减仓或做空。"
        elif clamped < -0.08:
            direction = SignalDirection.BEARISH
            action = "偏看跌。"
        else:
            direction = SignalDirection.NEUTRAL
            action = "观望。"

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=aggregate,
            confidence=0.75 if abs(clamped) > 0.3 else 0.55,
            data_freshness_ms=0, data_completeness=1.0,
            weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"spot": {g.value: spot_inflows.get(g, 0.0) for g in self._KEY_GRANULARITIES},
                 "contract": {g.value: contract_inflows.get(g, 0.0) for g in self._KEY_GRANULARITIES}},
                evidence,
                f"现货合约背离度得分: {clamped:+.3f}。综合判断: {direction.value}。",
                action,
                limitations=["背离信号可能只是暂时性套利而非真实背离"],
            ),
        )
