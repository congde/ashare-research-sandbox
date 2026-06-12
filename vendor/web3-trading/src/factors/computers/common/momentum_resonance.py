"""多周期动量共振 — 多周期RSI/MACD方向一致性。"""
from __future__ import annotations

from typing import ClassVar, List

import numpy as np

from ...base import BaseFactorComputer
from ...context import FactorContext
from ...enums import FactorCategory, FactorTier, SignalDirection
from ...models import FactorResult
from .._utils import get_kline_column, macd, rsi

_TF_WEIGHTS = {"15m": 0.3, "1h": 0.5, "4h": 0.8, "1d": 1.0}


class MomentumResonanceComputer(BaseFactorComputer):
    factor_name: ClassVar[str] = "momentum_resonance"
    category: ClassVar[FactorCategory] = FactorCategory.TECHNICAL
    display_name: ClassVar[str] = "多周期动量共振"
    description: ClassVar[str] = "多周期RSI/MACD方向一致性，与资金一致性对称验证。"
    requires_data: ClassVar[List[str]] = ["kline"]

    async def compute(self, ctx: FactorContext) -> FactorResult:
        klines = ctx.data.get("kline", {})

        dirs: dict[str, float] = {}
        weights_sum = 0.0
        evidence = []
        available_tfs = []

        for tf in ["15m", "1h", "4h", "1d"]:
            close = get_kline_column(klines, tf, "close")
            if close is None or len(close) < 30:
                continue
            available_tfs.append(tf)
            r = rsi(close, 14)
            _, _, hist = macd(close)
            rsi_dir = np.sign(r[-1] - 50) if not np.isnan(r[-1]) else 0.0
            macd_dir = np.sign(hist[-1]) if not np.isnan(hist[-1]) else 0.0
            dir_val = rsi_dir + macd_dir  # range: -2 to +2
            dirs[tf] = dir_val
            weights_sum += _TF_WEIGHTS.get(tf, 0.5)

        if not available_tfs:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "K线数据不足。"),
            )

        weighted_sum = sum(dirs[tf] * _TF_WEIGHTS.get(tf, 0.5) for tf in dirs)
        resonance = weighted_sum / max(weights_sum, 0.01)
        clamped = max(-1.0, min(1.0, resonance / 2.0))

        for tf in available_tfs:
            label = "多头" if dirs[tf] > 0 else ("空头" if dirs[tf] < 0 else "中性")
            evidence.append(self._evidence(
                data_point=f"{tf} 动量方向: {label} (得分={dirs[tf]:.0f})",
                interpretation=f"{tf}周期{'多头' if dirs[tf] > 0 else '空头'}共振",
                implication="多周期共振增强信号可靠性",
                confidence=0.7,
            ))

        if clamped > 0.5:
            direction = SignalDirection.STRONG_BULLISH
            action = "全周期多头共振，最强看涨信号。"
        elif clamped > 0.15:
            direction = SignalDirection.BULLISH
            action = "多数周期偏多，持仓。"
        elif clamped < -0.5:
            direction = SignalDirection.STRONG_BEARISH
            action = "全周期空头共振，最强看跌信号。"
        elif clamped < -0.15:
            direction = SignalDirection.BEARISH
            action = "多数周期偏空，减仓。"
        else:
            direction = SignalDirection.NEUTRAL
            action = "周期分歧，方向不明确，观望。"

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=float(resonance),
            confidence=0.75 if abs(clamped) > 0.3 else 0.45,
            data_freshness_ms=0, data_completeness=float(len(available_tfs)) / 4.0,
            weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"tf_directions": {tf: float(dirs[tf]) for tf in dirs}, "resonance": float(resonance)},
                evidence,
                f"动量共振得分: {resonance:+.3f}。{action}",
                action,
                limitations=["短周期噪音可能干扰长周期信号"],
            ),
        )
