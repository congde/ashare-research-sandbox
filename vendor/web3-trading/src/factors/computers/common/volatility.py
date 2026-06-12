"""波动率 — 滚动窗口波动率及分位数，识别变盘和突破前兆。"""
from __future__ import annotations

from typing import ClassVar, List

import numpy as np

from ...base import BaseFactorComputer
from ...context import FactorContext
from ...enums import FactorCategory, FactorTier, SignalDirection
from ...models import FactorResult
from .._utils import get_kline_column, rolling_percentile, rolling_volatility


class VolatilityComputer(BaseFactorComputer):
    factor_name: ClassVar[str] = "volatility"
    category: ClassVar[FactorCategory] = FactorCategory.TECHNICAL
    display_name: ClassVar[str] = "波动率"
    description: ClassVar[str] = "滚动窗口波动率及历史分位数，识别趋势启动/衰竭。"
    requires_data: ClassVar[List[str]] = ["kline"]

    async def compute(self, ctx: FactorContext) -> FactorResult:
        klines = ctx.data.get("kline", {})
        close_1h = get_kline_column(klines, "1h", "close")
        if close_1h is None:
            close_1h = get_kline_column(klines, "4h", "close")

        if close_1h is None or len(close_1h) < 50:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "K线数据不足。"),
            )

        annualize = 365 * 24
        vol_20 = rolling_volatility(close_1h, 20, annualize)

        current_vol = float(vol_20[-1])
        if current_vol != current_vol:  # NaN check
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "波动率数据不足。"),
            )

        valid_vol = vol_20[~np.isnan(vol_20)]
        vol_percentile = rolling_percentile(valid_vol, min(720, len(valid_vol)))
        current_pct = float(vol_percentile[-1]) if len(vol_percentile) > 0 else 0.5

        evidence = [
            self._evidence(
                data_point=f"20周期波动率: {current_vol:.4f} (年化)",
                interpretation=f"当前波动率处于{current_pct:.0%}分位",
                implication="波动率低位→突破前兆，波动率高位→趋势衰竭",
                confidence=0.7,
            ),
        ]

        if current_pct > 0.9:
            direction = SignalDirection.NEUTRAL_BEARISH
            clamped = -0.3
            action = "波动率极端高位，趋势可能衰竭，注意止盈。"
        elif current_pct < 0.1:
            direction = SignalDirection.NEUTRAL_BULLISH
            clamped = 0.3
            action = "波动率极端低位，蓄力突破前兆，准备入场。"
        elif current_pct > 0.7:
            direction = SignalDirection.NEUTRAL
            clamped = 0.0
            action = "波动率偏高，趋势运行中。"
        elif current_pct < 0.3:
            direction = SignalDirection.NEUTRAL
            clamped = 0.0
            action = "波动率偏低，等待方向选择。"
        else:
            direction = SignalDirection.NEUTRAL
            clamped = 0.0
            action = "波动率正常范围。"

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=current_vol,
            confidence=0.65 if current_pct > 0.8 or current_pct < 0.2 else 0.40,
            data_freshness_ms=0, data_completeness=1.0, weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"vol_20": current_vol, "vol_percentile": float(current_pct)},
                evidence,
                f"波动率: {current_vol:.4f} ({current_pct:.0%}分位)。{action}",
                action,
                limitations=["波动率分位数依赖历史窗口长度，极端行情下可能失真"],
            ),
        )
