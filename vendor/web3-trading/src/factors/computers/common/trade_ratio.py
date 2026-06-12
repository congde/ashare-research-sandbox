"""资金流入流出比 — 公共因子。

区分主力大单与散户小单的充提比。
inflow/outflow > 1 = 充值主导；< 1 = 提币主导。
数据源从 getCoinTrade（realtime_fund）读取，按市场类型选择。
"""
from __future__ import annotations

from typing import ClassVar, List

from ...base import BaseFactorComputer
from ...context import FactorContext
from ...enums import FactorCategory, FactorTier, MarketType, SignalDirection
from ...models import FactorResult


class TradeRatioComputer(BaseFactorComputer):
    factor_name: ClassVar[str] = "trade_ratio"
    category: ClassVar[FactorCategory] = FactorCategory.FUND_FLOW
    display_name: ClassVar[str] = "资金流入流出比"
    description: ClassVar[str] = "从 realtime_fund 数据计算的资金流入与流出比值。"
    requires_data: ClassVar[List[str]] = ["realtime_fund"]

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
                trace=self._build_trace(self.factor_name, {}, [], "无realtime_fund数据。"),
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
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [],
                    f"{'现货' if is_spot else '合约'}数据为空。"),
            )

        # 取 H24 粒度（time_particle_enum=124），无则取第一条
        latest = items[0]
        for item in items:
            tpe_raw = getattr(item, "time_particle_enum", 0) or 0
            tpe = int(tpe_raw) if isinstance(tpe_raw, str) else tpe_raw
            if tpe == 124:
                latest = item
                break

        trade_in = float(getattr(latest, "trade_in", 0) or 0)
        trade_out = float(getattr(latest, "trade_out", 0) or 0)

        if trade_in == 0.0 and trade_out == 0.0:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.NEUTRAL,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.3, weight=0.0,
                trace=self._build_trace(self.factor_name,
                    {"trade_in": trade_in, "trade_out": trade_out},
                    [], "流入流出数据为零。"),
            )

        ratio = self._safe_div(trade_in, trade_out, 1.0)
        evidence = [self._evidence(
            data_point=f"流入/流出比: {ratio:.3f} (in={trade_in:,.0f}, out={trade_out:,.0f})",
            interpretation="充值大于提币，抛压占优" if ratio > 1.05
            else ("提币大于充值，持币意愿强" if ratio < 0.95 else "充提基本平衡"),
            implication="持币意愿强，利好" if ratio < 0.95
            else ("抛压占优，利空" if ratio > 1.05 else "方向不明确"),
            confidence=0.65 if abs(ratio - 1.0) > 0.2 else 0.45,
        )]

        clamped = max(-1.0, min(1.0, (1.0 - ratio) * 1.5))

        if clamped > 0.2:
            direction = SignalDirection.BULLISH
            action = "提币主导，偏多。"
        elif clamped < -0.2:
            direction = SignalDirection.BEARISH
            action = "充值主导，偏空。"
        else:
            direction = SignalDirection.NEUTRAL
            action = "观望。"

        market_label = "现货" if is_spot else "合约"
        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=ratio,
            confidence=0.60 if abs(ratio - 1.0) > 0.2 else 0.40,
            data_freshness_ms=0, data_completeness=1.0,
            weight=0.0,
            trace=self._build_trace(
                self.factor_name, {"trade_in": trade_in, "trade_out": trade_out, "ratio": ratio,
                                   "market": market_label},
                evidence,
                f"{market_label}流入流出比: {ratio:.3f}。{'提币主导' if ratio < 1 else '充值主导'}。",
                action,
                limitations=["流入流出比不区分大单/小单，需要结合大额交易分析"],
            ),
        )
