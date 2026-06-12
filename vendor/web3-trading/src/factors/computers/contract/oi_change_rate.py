"""持仓量变化率 — OI+价格方向联合判断趋势健康度（仅合约）。"""
from __future__ import annotations

from typing import ClassVar, List, Set

import numpy as np

from ...base import BaseFactorComputer
from ...context import FactorContext
from ...enums import FactorCategory, FactorTier, MarketType, SignalDirection
from ...models import FactorResult, OpenInterestData
from .._utils import get_kline_column


class OIChangeRateComputer(BaseFactorComputer):
    factor_name: ClassVar[str] = "oi_change_rate"
    category: ClassVar[FactorCategory] = FactorCategory.DERIVATIVES
    display_name: ClassVar[str] = "持仓量变化率"
    description: ClassVar[str] = "持仓量环比变化率，结合价格方向判断趋势健康度。"
    requires_data: ClassVar[List[str]] = ["open_interest", "kline"]
    supported_markets: ClassVar[Set[MarketType]] = {MarketType.CONTRACT}

    async def compute(self, ctx: FactorContext) -> FactorResult:
        oi_data = ctx.data.get("open_interest")
        if oi_data is None:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "无持仓量数据。"),
            )

        oi: np.ndarray
        if isinstance(oi_data, OpenInterestData):
            oi = np.asarray(oi_data.values, dtype=np.float64)
        elif isinstance(oi_data, (list, np.ndarray)):
            oi = np.asarray(oi_data, dtype=np.float64)
        elif isinstance(oi_data, dict):
            arr = oi_data.get("oi") or oi_data.get("values") or []
            oi = np.asarray(arr, dtype=np.float64)
        else:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "持仓量数据格式不支持。"),
            )

        if len(oi) < 2:
            return FactorResult(
                factor_name=self.factor_name, factor_index=0,
                factor_tier=FactorTier.TIER_5, category=self.category,
                display_name=self.display_name,
                signal_direction=SignalDirection.INCONCLUSIVE,
                normalized_score=0.0, raw_value=0.0, confidence=0.0,
                data_completeness=0.0, weight=0.0,
                trace=self._build_trace(self.factor_name, {}, [], "持仓量数据不足。"),
            )

        klines = ctx.data.get("kline", {})
        close = get_kline_column(klines, "1h", "close")
        if close is None:
            close = get_kline_column(klines, "4h", "close")

        current_oi = float(oi[-1])
        prev_oi = float(oi[-2])
        oi_change_pct = (current_oi - prev_oi) / max(abs(prev_oi), 1e-10) * 100.0

        price_up = close is not None and len(close) >= 2 and close[-1] > close[-2]
        price_down = close is not None and len(close) >= 2 and close[-1] < close[-2]
        oi_up = oi_change_pct > 1.0
        oi_down = oi_change_pct < -1.0

        evidence = [
            self._evidence(
                data_point=f"OI变化: {oi_change_pct:+.2f}%, 价格: {'↑' if price_up else '↓' if price_down else '→'}",
                interpretation=f"价格{'↑' if price_up else '↓'}+OI{'↑' if oi_up else '↓'}",
                implication="价格↑+OI↑=多头增仓健康，价格↑+OI↓=空头平仓推动不可持续",
                confidence=0.7,
            ),
        ]

        if price_up and oi_up:
            direction = SignalDirection.BULLISH
            clamped = 0.5
            action = "价格涨+OI增，多头主动增仓，趋势健康，顺势做多。"
        elif price_up and oi_down:
            direction = SignalDirection.NEUTRAL_BEARISH
            clamped = -0.2
            action = "价格涨+OI减，空头平仓推涨，不可持续，警惕反转。"
        elif price_down and oi_up:
            direction = SignalDirection.BEARISH
            clamped = -0.5
            action = "价格跌+OI增，空头主动增仓，趋势健康，顺势做空。"
        elif price_down and oi_down:
            direction = SignalDirection.NEUTRAL_BULLISH
            clamped = 0.2
            action = "价格跌+OI减，多头平仓推动下跌，可能见底。"
        else:
            direction = SignalDirection.NEUTRAL
            clamped = 0.0
            action = "价格与OI变化不显著，观望。"

        return FactorResult(
            factor_name=self.factor_name, factor_index=0,
            factor_tier=FactorTier.TIER_5, category=self.category,
            display_name=self.display_name,
            signal_direction=direction, normalized_score=clamped,
            raw_value=float(oi_change_pct),
            confidence=0.65 if abs(clamped) > 0.3 else 0.40,
            data_freshness_ms=0, data_completeness=1.0, weight=0.0,
            trace=self._build_trace(
                self.factor_name,
                {"oi_change_pct": float(oi_change_pct), "price_up": price_up, "oi_up": oi_up},
                evidence,
                f"OI变化: {oi_change_pct:+.2f}%。{action}",
                action,
                limitations=["OI变化受主力换月/移仓影响，单个1h变化可能噪音较大"],
            ),
        )
