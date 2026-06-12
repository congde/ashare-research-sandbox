"""元数据因子 — 公共因子。

- 基础标识与数据可用性：代币解析质量、数据完整性标志
- 持仓地址标签与集中度：地址标签分类和持仓集中度
"""
from __future__ import annotations

from typing import ClassVar, List

from ...base import BaseFactorComputer
from ...context import FactorContext
from ...enums import FactorCategory, FactorTier, SignalDirection
from ...models import FactorResult


class IdentifiersComputer(BaseFactorComputer):
    """基础标识与数据可用性 — 代币解析质量和数据完整性。"""

    factor_name: ClassVar[str] = "identifiers"
    category: ClassVar[FactorCategory] = FactorCategory.META
    display_name: ClassVar[str] = "基础标识与数据可用性"
    description: ClassVar[str] = "代币解析质量和数据可用性标志。"
    requires_data: ClassVar[List[str]] = []

    async def compute(self, ctx: FactorContext) -> FactorResult:
        trade_type = "未知"
        ai_item = ctx.data.get("ai_chance")
        if ai_item is not None:
            tt = getattr(ai_item, "trade_type", None)
            if tt == 1:
                trade_type = "现货"
            elif tt == 2:
                trade_type = "合约"
            elif tt == 3:
                trade_type = "交割合约"

        evidence = [self._evidence(
            data_point=(
                f"vs_token_id={ctx.vs_token_id}, symbol={ctx.symbol}, "
                f"现货={'✓' if ctx.has_spot else '✗'}, "
                f"合约={'✓' if ctx.has_contract else '✗'}, "
                f"类型={trade_type}"
            ),
            interpretation="数据完整" if ctx.has_spot and ctx.has_contract
            else ("部分数据可用" if ctx.has_spot or ctx.has_contract else "数据不完整"),
            implication="现货+合约数据完整，信号可靠性高" if ctx.has_spot and ctx.has_contract
            else ("仅现货数据，适合中长期策略" if ctx.has_spot
                  else ("仅合约数据，纯投机标的" if ctx.has_contract
                        else "数据缺失严重，建议排除")),
            confidence=0.95,
        )]

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=SignalDirection.NEUTRAL,
            normalized_score=0.0,
            raw_value=float(ctx.vs_token_id) if ctx.vs_token_id.isdigit() else 0.0,
            confidence=0.95,
            data_freshness_ms=0,
            data_completeness=1.0 if ctx.has_spot or ctx.has_contract else 0.2,
            weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"vs_token_id": ctx.vs_token_id, "symbol": ctx.symbol,
                 "has_spot": ctx.has_spot, "has_contract": ctx.has_contract},
                evidence,
                f"代币{ctx.symbol}(id={ctx.vs_token_id}): "
                f"现货={ctx.has_spot}, 合约={ctx.has_contract}。零权重元数据因子。",
                limitations=[],
            ),
        )


class HolderLabelsComputer(BaseFactorComputer):
    """持仓地址标签与集中度 — 地址标签分类和持仓集中度。"""

    factor_name: ClassVar[str] = "holder_labels"
    category: ClassVar[FactorCategory] = FactorCategory.ONCHAIN
    display_name: ClassVar[str] = "持仓地址标签与集中度"
    description: ClassVar[str] = "持仓地址标签分类和集中度分析。"
    requires_data: ClassVar[List[str]] = ["holder_list"]

    async def compute(self, ctx: FactorContext) -> FactorResult:
        holders = ctx.data.get("holder_list") or []

        if not holders:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "无持仓地址数据。"),
            )

        label_counts = {"exchange": 0, "cold_wallet": 0, "contract": 0, "unknown": 0}
        total_balance = 0.0
        top10_balance = 0.0

        for i, h in enumerate(holders):
            bal = float(getattr(h, "balance", 0) or 0)
            total_balance += bal
            if i < 10:
                top10_balance += bal

            label = getattr(h, "label", None)
            if label is not None:
                label_name = getattr(label, "label_name", "") or ""
                if "exchange" in label_name.lower():
                    label_counts["exchange"] += 1
                elif "cold" in label_name.lower():
                    label_counts["cold_wallet"] += 1
                elif "contract" in label_name.lower():
                    label_counts["contract"] += 1
                else:
                    label_counts["unknown"] += 1
            else:
                label_counts["unknown"] += 1

        concentration = self._safe_div(top10_balance, total_balance, 0.0)
        evidence = [self._evidence(
            data_point=f"前10地址占比: {concentration:.1%}，交易所:{label_counts['exchange']}，冷钱包:{label_counts['cold_wallet']}",
            interpretation=f"持仓{'高度集中' if concentration > 0.8 else '较分散' if concentration < 0.5 else '中等集中'}",
            implication="持仓集中+主力派发→抛售冲击大" if concentration > 0.7
            else "持仓分散→价格操纵风险低",
            confidence=0.40,
        )]

        # 弱信号：高集中度=操纵风险溢价，偏负面；分散=健康
        if concentration > 0.8:
            clamped = -0.15
            direction = SignalDirection.NEUTRAL_BEARISH
            action = "持仓高度集中，注意大户抛售风险。"
        elif concentration > 0.6:
            clamped = -0.05
            direction = SignalDirection.NEUTRAL_BEARISH
            action = "持仓偏集中，存在一定操纵风险。"
        elif concentration > 0.3:
            clamped = 0.0
            direction = SignalDirection.NEUTRAL
            action = "持仓较分散。"
        else:
            clamped = 0.05
            direction = SignalDirection.NEUTRAL_BULLISH
            action = "持仓高度分散，价格操纵风险低。"

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=concentration,
            confidence=0.30,
            data_freshness_ms=0,
            data_completeness=1.0 if holders else 0.0,
            weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"holder_count": len(holders), "concentration": concentration,
                 "label_counts": label_counts},
                evidence,
                f"持仓地址: {len(holders)}个，前10占比{concentration:.1%}。",
                action,
                limitations=["地址标签可能不准确", "仅分析前20条数据"],
            ),
        )
