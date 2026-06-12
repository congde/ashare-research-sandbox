"""主力持仓余额趋势 — 公共因子。

主力地址余额变化趋势。增持=看涨，减持=看跌。
"""
from __future__ import annotations

from typing import ClassVar, List

from ...base import BaseFactorComputer
from ...context import FactorContext
from ...enums import FactorCategory, FactorTier, SignalDirection
from ...models import FactorResult
from ...utils import compute_change_rate


class BalanceTrendComputer(BaseFactorComputer):
    factor_name: ClassVar[str] = "balance_trend"
    category: ClassVar[FactorCategory] = FactorCategory.WHALE_COST
    display_name: ClassVar[str] = "主力持仓余额趋势"
    description: ClassVar[str] = "从 whale_cost 数据分析主力地址余额变化趋势。"
    requires_data: ClassVar[List[str]] = ["whale_cost"]

    async def compute(self, ctx: FactorContext) -> FactorResult:
        whale_data = ctx.data.get("whale_cost") or []

        if len(whale_data) < 2:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.2, weight=0.0,
                trace=self._build_trace(self.factor_name, {"data_points": len(whale_data)}, [],
                    "数据点不足，需至少2天数据。"),
            )

        balances = []
        for item in whale_data:
            bal = getattr(item, "balance", None)
            if bal is not None:
                balances.append(float(bal))

        if len(balances) < 2:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.2, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "余额数据不足。"),
            )

        first_balance = balances[0]
        last_balance = balances[-1]
        change = last_balance - first_balance
        change_pct = compute_change_rate(last_balance, first_balance)

        evidence = [self._evidence(
            data_point=f"主力持仓: {first_balance:,.0f} → {last_balance:,.0f} ({change_pct:+.2%})",
            interpretation=f"主力{'增持' if change > 0 else '减持'} {abs(change):,.0f} ({abs(change_pct):.1%})",
            implication="主力吸筹，利好后续上涨" if change > 0 else "主力派发，利好结束",
            confidence=0.80 if abs(change_pct) > 0.05 else 0.55,
        )]

        increases = sum(1 for i in range(1, len(balances)) if balances[i] > balances[i - 1])
        decreases = len(balances) - 1 - increases
        consistency = abs(increases - decreases) / max(1, len(balances) - 1)

        clamped = max(-1.0, min(1.0, change_pct * 1.5 * (0.5 + consistency * 0.5)))

        if clamped > 0.3:
            direction = SignalDirection.BULLISH
            action = "主力持续增持，可做多。"
        elif clamped < -0.3:
            direction = SignalDirection.BEARISH
            action = "主力持续减持，应减仓或做空。"
        else:
            direction = SignalDirection.NEUTRAL
            action = "观望。"

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=change_pct,
            confidence=0.70 + consistency * 0.15,
            data_freshness_ms=0,
            data_completeness=min(1.0, len(balances) / 7.0),
            weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"first_balance": first_balance, "last_balance": last_balance,
                 "change_pct": change_pct, "consistency": consistency},
                evidence,
                f"主力持仓变化: {change_pct:+.2%}，持续性={consistency:.2f}。",
                action,
                limitations=["主力地址识别可能不完整"],
            ),
        )
