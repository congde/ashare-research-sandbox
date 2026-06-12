"""量价关系 — 成交量与价格变化的方向一致性及背离检测。"""
from __future__ import annotations

from typing import ClassVar, List

import numpy as np

from ...base import BaseFactorComputer
from ...context import FactorContext
from ...enums import FactorCategory, FactorTier, SignalDirection
from ...models import FactorResult
from .._utils import get_kline_column


class VolumePriceDivergenceComputer(BaseFactorComputer):
    factor_name: ClassVar[str] = "volume_price_divergence"
    category: ClassVar[FactorCategory] = FactorCategory.TECHNICAL
    display_name: ClassVar[str] = "量价关系"
    description: ClassVar[str] = "成交量与价格变化的方向一致性，识别趋势健康度。"
    requires_data: ClassVar[List[str]] = ["kline"]

    async def compute(self, ctx: FactorContext) -> FactorResult:
        klines = ctx.data.get("kline", {})
        close = get_kline_column(klines, "1h", "close")
        volume = get_kline_column(klines, "1h", "volume")
        if close is None:
            close = get_kline_column(klines, "4h", "close")
            volume = get_kline_column(klines, "4h", "volume")

        if close is None or volume is None or len(close) < 25:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "K线数据不足。"),
            )

        close_recent = close[-20:]
        vol_recent = volume[-20:]

        price_direction = 1 if close_recent[-1] > close_recent[0] else -1
        corr_matrix = np.corrcoef(close_recent, vol_recent)
        corr = float(corr_matrix[0, 1]) if corr_matrix.shape == (2, 2) else 0.0

        vol_short = float(np.mean(volume[-5:]))
        vol_long = float(np.mean(volume[-20:]))
        vol_ratio = vol_short / max(vol_long, 1e-10)

        divergence = (price_direction > 0 and corr < 0) or (price_direction < 0 and corr < 0)

        evidence = [
            self._evidence(
                data_point=f"量价相关系数: {corr:+.3f}, 放量比: {vol_ratio:.2f}",
                interpretation=f"{'量价背离' if divergence else '量价一致'}，"
                              f"{'放量' if vol_ratio > 1.2 else '缩量' if vol_ratio < 0.8 else '量能正常'}",
                implication="量增价升=趋势健康，缩量突破可能是假突破",
                confidence=0.7,
            ),
        ]

        if price_direction > 0 and corr > 0.3 and vol_ratio > 1.1:
            direction = SignalDirection.BULLISH
            clamped = 0.5
            action = "量增价升，上升动能充足，持仓。"
        elif price_direction < 0 and corr > 0.3 and vol_ratio > 1.1:
            direction = SignalDirection.BEARISH
            clamped = -0.5
            action = "量增价跌，下跌动能充足，做空或减仓。"
        elif price_direction > 0 and vol_ratio < 0.8:
            direction = SignalDirection.NEUTRAL_BEARISH
            clamped = -0.2
            action = "缩量上涨，买盘衰竭，止盈。"
        elif price_direction < 0 and vol_ratio < 0.8:
            direction = SignalDirection.NEUTRAL_BULLISH
            clamped = 0.2
            action = "缩量下跌，卖压衰减。"
        elif divergence:
            direction = SignalDirection.NEUTRAL
            clamped = 0.0
            action = "量价背离，警惕变盘。"
        else:
            direction = SignalDirection.NEUTRAL
            clamped = 0.0
            action = "量价关系中性。"

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=float(corr),
            confidence=0.65 if abs(clamped) > 0.2 else 0.40,
            data_freshness_ms=0, data_completeness=1.0, weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"correlation": corr, "volume_ratio": float(vol_ratio), "divergence": divergence},
                evidence,
                f"量价关系: corr={corr:+.2f}, vol_ratio={vol_ratio:.2f}。{action}",
                action,
                limitations=["低成交量代币量价关系噪音较大"],
            ),
        )
