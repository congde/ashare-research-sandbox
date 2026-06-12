"""链上数据因子 — 公共因子。

- 大额交易方向：转入/转出交易所的大额转账分析
- 地址盈亏趋势：持仓者整体盈亏状态
- 余额价格背离：主力余额与币价趋势背离检测
- 持仓地址活跃度：24h 活跃地址和新增地址数
- 交易行为次数：链上转入/转出次数趋势
"""
from __future__ import annotations

from typing import ClassVar, List

from ...base import BaseFactorComputer
from ...context import FactorContext
from ...enums import FactorCategory, FactorTier, SignalDirection
from ...models import FactorResult


class LargeTransactionsComputer(BaseFactorComputer):
    """大额交易方向 — 链上大额转账的交易所流向分析。"""

    factor_name: ClassVar[str] = "large_transactions"
    category: ClassVar[FactorCategory] = FactorCategory.ONCHAIN
    display_name: ClassVar[str] = "大额交易方向"
    description: ClassVar[str] = "链上大额转账的交易所流向方向分析。"
    requires_data: ClassVar[List[str]] = ["large_transactions"]

    async def compute(self, ctx: FactorContext) -> FactorResult:
        txs = ctx.data.get("large_transactions") or []

        if not txs:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "无大额交易数据。"),
            )

        to_exchange_count = 0
        from_exchange_count = 0
        total_amount = 0.0

        for tx in txs:
            amount = float(getattr(tx, "amount", 0) or 0)
            total_amount += amount
            from_ex = getattr(tx, "from_exchange_name", "") or ""
            to_ex = getattr(tx, "to_exchange_name", "") or ""

            if to_ex and not from_ex:
                to_exchange_count += 1
            elif from_ex and not to_ex:
                from_exchange_count += 1

        evidence = []
        net_direction = from_exchange_count - to_exchange_count

        if to_exchange_count > 0 or from_exchange_count > 0:
            evidence.append(self._evidence(
                data_point=f"转入交易所: {to_exchange_count}笔, 转出交易所: {from_exchange_count}笔",
                interpretation=f"大额交易净流出交易所{net_direction}笔" if net_direction > 0
                else (f"大额交易净流入交易所{-net_direction}笔" if net_direction < 0 else "大额交易流向平衡"),
                implication="机构从交易所提币囤积，利好" if net_direction > 0
                else ("机构向交易所充值，可能准备抛售，利空" if net_direction < 0 else ""),
                confidence=0.70 if abs(net_direction) > 2 else 0.45,
            ))

        if total_amount > 0:
            evidence.append(self._evidence(
                data_point=f"大额交易总额: {total_amount:,.0f} USD ({len(txs)}笔)",
                interpretation=f"大额交易活跃度: {'高' if len(txs) > 5 else '中等'}",
                implication="大额交易活跃时波动可能加剧",
                confidence=0.55,
            ))

        total_tx = to_exchange_count + from_exchange_count
        if total_tx == 0:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.NEUTRAL,
                normalized_score=0.0, raw_value=0.0, confidence=0.4,
                data_completeness=1.0, weight=0.0,
                trace=self._build_trace(self.factor_name,
                    {"tx_count": len(txs), "total_amount": total_amount},
                    evidence,
                    "大额交易中没有明确的交易所间转账方向。",
                    limitations=["仅分析有交易所标签的地址"],
                ),
            )

        direction_ratio = net_direction / max(1, total_tx)
        clamped = max(-1.0, min(1.0, direction_ratio * 1.5))

        if clamped > 0.3:
            direction = SignalDirection.BULLISH
            action = "大额资金流出交易所，机构囤币，可做多。"
        elif clamped < -0.3:
            direction = SignalDirection.BEARISH
            action = "大额资金流入交易所，抛压预警，可减仓。"
        else:
            direction = SignalDirection.NEUTRAL
            action = "观望。"

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=float(net_direction),
            confidence=0.65 if abs(net_direction) > 2 else 0.45,
            data_freshness_ms=0, data_completeness=1.0,
            weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"from_exchange": from_exchange_count, "to_exchange": to_exchange_count,
                 "total_amount": total_amount, "tx_count": len(txs)},
                evidence,
                f"大额交易: 转出交易所{from_exchange_count}笔, 转入{to_exchange_count}笔。"
                f"总金额{total_amount:,.0f} USD。",
                action,
                limitations=["交易所标签可能不完整", "仅分析地址标签，未分析链上行为意图"],
            ),
        )


class AddressPnlComputer(BaseFactorComputer):
    """地址盈亏趋势 — 持仓者整体盈亏状态。

    从 whale_cost (CoinTradeCostItem) 数据中计算 price - cost 作为
    持仓者未实现盈亏，price > cost 表示整体盈利，price < cost 表示整体亏损。
    """

    factor_name: ClassVar[str] = "address_pnl"
    category: ClassVar[FactorCategory] = FactorCategory.ONCHAIN
    display_name: ClassVar[str] = "地址盈亏趋势"
    description: ClassVar[str] = "从 whale_cost 数据计算持仓者价格偏离成本的程度。"
    requires_data: ClassVar[List[str]] = ["whale_cost"]

    async def compute(self, ctx: FactorContext) -> FactorResult:
        whale_data = ctx.data.get("whale_cost") or []

        pnl_margins = []
        for item in whale_data:
            price = getattr(item, "price", None)
            cost = getattr(item, "cost", None)
            if price is not None and cost is not None and cost > 0:
                pnl_margins.append((float(price) - float(cost)) / float(cost))

        if len(pnl_margins) < 2:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.2 if pnl_margins else 0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {"data_points": len(pnl_margins)}, [],
                    "盈亏数据不足。"),
            )

        recent = pnl_margins[-3:] if len(pnl_margins) >= 3 else pnl_margins
        avg_margin = sum(recent) / len(recent)

        evidence = [self._evidence(
            data_point=f"近期价格偏离成本均值: {avg_margin:+.2%}",
            interpretation="持仓者整体盈利" if avg_margin > 0 else "持仓者整体亏损",
            implication="盈利地址可能止盈，注意回调风险" if avg_margin > 0
            else "亏损地址不愿卖出，可能形成支撑",
            confidence=0.60,
        )]

        # 负向得分：盈利→利空（止盈压力），亏损→利好（支撑）
        clamped = max(-0.5, min(0.5, -avg_margin * 2.0)) if avg_margin != 0 else 0.0

        if clamped > 0.15:
            direction = SignalDirection.NEUTRAL_BULLISH
            action = "持仓者亏损，支撑较强。"
        elif clamped < -0.15:
            direction = SignalDirection.NEUTRAL_BEARISH
            action = "持仓者盈利，注意止盈压力。"
        else:
            direction = SignalDirection.NEUTRAL
            action = "观望。"

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=avg_margin,
            confidence=0.55,
            data_freshness_ms=0,
            data_completeness=min(1.0, len(pnl_margins) / 7.0),
            weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"avg_margin": avg_margin, "data_points": len(pnl_margins)},
                evidence,
                f"地址盈亏: 价格偏离成本均值{avg_margin:+.2%}。",
                action,
                limitations=["盈亏基于 whale_cost 的 price-cost 偏离度，非实际盈亏金额"],
            ),
        )


class BalancePriceDivergenceComputer(BaseFactorComputer):
    """余额价格背离 — 主力余额与币价趋势的背离检测。"""

    factor_name: ClassVar[str] = "balance_price_divergence"
    category: ClassVar[FactorCategory] = FactorCategory.WHALE_COST
    display_name: ClassVar[str] = "余额趋势与币价背离"
    description: ClassVar[str] = "主力余额趋势与币价趋势之间的背离度。"
    requires_data: ClassVar[List[str]] = ["whale_cost"]

    async def compute(self, ctx: FactorContext) -> FactorResult:
        whale_data = ctx.data.get("whale_cost") or []

        if len(whale_data) < 4:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.2, weight=0.0,
                trace=self._build_trace(self.factor_name, {"data_points": len(whale_data)},
                    [], "数据点不足，需至少4天数据。"),
            )

        balances = []
        prices = []
        for item in whale_data:
            b = getattr(item, "balance", None)
            p = getattr(item, "price", None)
            if b is not None and p is not None:
                balances.append(float(b))
                prices.append(float(p))

        if len(balances) < 4:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.3, weight=0.0,
                trace=self._build_trace(self.factor_name, {"data_points": len(balances)},
                    [], "余额/价格数据不足。"),
            )

        balance_change = (balances[-1] - balances[0]) / max(abs(balances[0]), 1)
        price_change = (prices[-1] - prices[0]) / max(abs(prices[0]), 1)

        evidence = [self._evidence(
            data_point=f"余额变化: {balance_change:+.2%}, 价格变化: {price_change:+.2%}",
            interpretation="余额上升+价格下跌→低位吸筹" if balance_change > 0.03 and price_change < -0.03
            else ("余额下降+价格上涨→高位派发" if balance_change < -0.03 and price_change > 0.03
                  else "余额与价格同向"),
            implication="低位吸筹，利好后续反弹" if balance_change > 0.03 and price_change < -0.03
            else ("高位派发，利好可能已透支" if balance_change < -0.03 and price_change > 0.03
                  else "无背离信号"),
            confidence=0.65 if abs(balance_change - price_change) > 0.06 else 0.45,
        )]

        div = balance_change - price_change
        clamped = max(-0.6, min(0.6, div * 5.0))

        if clamped > 0.15:
            direction = SignalDirection.NEUTRAL_BULLISH
            action = "余额趋势看涨，偏多。"
        elif clamped < -0.15:
            direction = SignalDirection.NEUTRAL_BEARISH
            action = "余额趋势看跌，偏空。"
        else:
            direction = SignalDirection.NEUTRAL
            action = "观望。"

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=div,
            confidence=0.60,
            data_freshness_ms=0,
            data_completeness=min(1.0, len(balances) / 7.0),
            weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"balance_change": balance_change, "price_change": price_change, "divergence": div},
                evidence,
                f"余额-价格背离: {div:+.3f}。",
                action,
                limitations=["偏离可能由链上特殊事件导致，非真实背离"],
            ),
        )


class AddressActivityComputer(BaseFactorComputer):
    """持仓地址活跃度 — 24h 活跃和新增地址。"""

    factor_name: ClassVar[str] = "address_activity"
    category: ClassVar[FactorCategory] = FactorCategory.ONCHAIN
    display_name: ClassVar[str] = "持仓地址活跃度"
    description: ClassVar[str] = "24 小时活跃地址和新增地址数量。"
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
                trace=self._build_trace(self.factor_name, {}, [], "无地址活跃度数据。"),
            )

        active = int(getattr(ai_item, "active", 0) or 0)
        newly = int(getattr(ai_item, "newly", 0) or 0)

        if active == 0 and newly == 0:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.NEUTRAL,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.3, weight=0.0,
                trace=self._build_trace(self.factor_name,
                    {"active": active, "newly": newly}, [],
                    "地址活跃度数据为零。"),
            )

        new_ratio = self._safe_div(newly, active, 0.0)
        evidence = [self._evidence(
            data_point=f"24h活跃: {active:,}, 新增: {newly:,} (新增占比: {new_ratio:.1%})",
            interpretation=f"新地址占比{new_ratio:.1%}，{'新资金积极流入' if new_ratio > 0.15 else '新资金有限'}",
            implication="新资金持续流入，利好后续上涨" if new_ratio > 0.15 and active > 0
            else "活跃度不足，上涨可持续性存疑",
            confidence=0.55 if active > 0 else 0.30,
        )]

        if new_ratio > 0.3 and active > 1000:
            clamped = 0.30
            direction = SignalDirection.BULLISH
            action = "大量新地址涌入，参与热度高，看涨。"
        elif new_ratio > 0.2 and active > 500:
            clamped = 0.20
            direction = SignalDirection.NEUTRAL_BULLISH
            action = "新地址积极流入，偏多。"
        elif new_ratio > 0.1 and active > 100:
            clamped = 0.08
            direction = SignalDirection.NEUTRAL_BULLISH
            action = "新地址温和增长。"
        elif active > 0:
            clamped = 0.03
            direction = SignalDirection.NEUTRAL
            action = "地址活跃度一般。"
        else:
            clamped = 0.0
            direction = SignalDirection.NEUTRAL
            action = "观望。"

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=float(active),
            confidence=0.45,
            data_freshness_ms=0, data_completeness=1.0 if active > 0 else 0.3,
            weight=0.0,
            trace=self._build_trace(
                self.factor_name, {"active": active, "newly": newly}, evidence,
                f"24h活跃地址: {active:,}, 新增: {newly:,}。",
                action,
                limitations=["地址数据可能有重复计数"],
            ),
        )


class TradeCountComputer(BaseFactorComputer):
    """交易行为次数 — 链上转入/转出次数趋势。"""

    factor_name: ClassVar[str] = "trade_count"
    category: ClassVar[FactorCategory] = FactorCategory.ONCHAIN
    display_name: ClassVar[str] = "交易行为次数"
    description: ClassVar[str] = "链上转入/转出次数趋势分析。"
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
        trade_in_n = int(getattr(latest, "trade_in_number", 0) or 0)
        trade_out_n = int(getattr(latest, "trade_out_number", 0) or 0)

        if trade_in_n == 0 and trade_out_n == 0:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.NEUTRAL,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.3, weight=0.0,
                trace=self._build_trace(self.factor_name,
                    {"trade_in_n": trade_in_n, "trade_out_n": trade_out_n},
                    [], "交易次数为零。"),
            )

        net = trade_in_n - trade_out_n
        evidence = [self._evidence(
            data_point=f"转入{trade_in_n:,}次, 转出{trade_out_n:,}次",
            interpretation="转入次数多于转出，积极建仓" if net > 0
            else ("转出次数多于转入，恐慌抛售" if net < 0 else "转入转出平衡"),
            implication="积极建仓，利好" if net > 0
            else ("恐慌抛售，利空" if net < 0 else ""),
            confidence=0.45,
        )]

        clamped = max(-0.2, min(0.2, net / max(trade_in_n + trade_out_n, 1) * 0.8))
        if clamped > 0.05:
            direction = SignalDirection.NEUTRAL_BULLISH
        elif clamped < -0.05:
            direction = SignalDirection.NEUTRAL_BEARISH
        else:
            direction = SignalDirection.NEUTRAL

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=float(net),
            confidence=0.40,
            data_freshness_ms=0, data_completeness=1.0,
            weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"trade_in_n": trade_in_n, "trade_out_n": trade_out_n},
                evidence,
                f"交易次数: 转入{trade_in_n}, 转出{trade_out_n}。",
                limitations=["交易次数不反映金额大小"],
            ),
        )
