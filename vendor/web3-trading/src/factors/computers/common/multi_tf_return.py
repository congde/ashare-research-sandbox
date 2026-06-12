"""多周期对数收益率 — 多周期动量延续/反转信号。"""
from __future__ import annotations

from typing import ClassVar, List

from ...base import BaseFactorComputer
from ...context import FactorContext
from ...enums import FactorCategory, FactorTier, SignalDirection
from ...models import FactorResult
from .._utils import get_kline_column, log_returns


class MultiTFReturnComputer(BaseFactorComputer):
    factor_name: ClassVar[str] = "multi_tf_return"
    category: ClassVar[FactorCategory] = FactorCategory.TECHNICAL
    display_name: ClassVar[str] = "多周期对数收益率"
    description: ClassVar[str] = "多周期对数收益率，判断动量延续/反转。"
    requires_data: ClassVar[List[str]] = ["kline"]

    _TF_LOOKBACK = {"15m": 4, "1h": 1, "4h": 1, "1d": 1}  # 15m间隔4根=1h

    async def compute(self, ctx: FactorContext) -> FactorResult:
        klines = ctx.data.get("kline", {})

        returns: dict[str, float] = {}
        evidence = []
        available = 0

        for tf, lookback in self._TF_LOOKBACK.items():
            close = get_kline_column(klines, tf, "close")
            if close is None or len(close) <= lookback:
                continue
            lr = log_returns(close, lookback)
            val = float(lr[-1])
            if val != val:  # NaN check
                continue
            returns[tf] = val
            available += 1
            direction = "正收益" if val > 0 else "负收益"
            evidence.append(self._evidence(
                data_point=f"{tf} 对数收益率: {val:+.4f}",
                interpretation=f"{tf}周期{direction}，{'动量延续' if val > 0 else '趋势转弱'}",
                implication="多周期一致方向增强信号可靠性",
                confidence=0.65,
            ))

        if available == 0:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "K线数据不足。"),
            )

        signals = list(returns.values())
        positive = sum(1 for v in signals if v > 0.001)
        negative = sum(1 for v in signals if v < -0.001)

        if positive == len(signals):
            direction = SignalDirection.STRONG_BULLISH
            clamped = 0.6
            action = "多周期一致正收益，动量延续，持仓待涨。"
        elif negative == len(signals):
            direction = SignalDirection.STRONG_BEARISH
            clamped = -0.6
            action = "多周期一致负收益，趋势转弱，减仓。"
        elif positive > negative:
            direction = SignalDirection.BULLISH
            clamped = 0.25
            action = "多数周期正收益，偏多。"
        elif negative > positive:
            direction = SignalDirection.BEARISH
            clamped = -0.25
            action = "多数周期负收益，偏空。"
        else:
            direction = SignalDirection.NEUTRAL
            clamped = 0.0
            action = "多空均衡，观望。"

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=float(sum(signals)),
            confidence=0.60 + abs(clamped) * 0.3,
            data_freshness_ms=0, data_completeness=float(available) / float(len(self._TF_LOOKBACK)),
            weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"returns": returns, "positive": positive, "negative": negative},
                evidence,
                f"多周期收益: {positive}/{available} 正, {negative}/{available} 负。{action}",
                action,
                limitations=["对数收益率仅反映方向，不反映波动强度"],
            ),
        )
