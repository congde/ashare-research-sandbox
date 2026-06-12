"""现货资金积累持续性 — 现货专属因子。"""

from __future__ import annotations

from typing import ClassVar, Set

from ...enums import MarketType, SignalDirection
from .._base_flow import _BasePersistenceComputer


class SpotPersistenceComputer(_BasePersistenceComputer):
    factor_name: ClassVar[str] = "spot_persistence"
    display_name: ClassVar[str] = "资金积累持续性(现货)"
    description: ClassVar[str] = "现货主力资金跨时间窗口的积累持续性。"
    supported_markets: ClassVar[Set[MarketType]] = {MarketType.SPOT}

    _DATA_FIELD: ClassVar[str] = "spot_goods_list"
    _MARKET_LABEL: ClassVar[str] = "现货"
    _INCREASING_INTERPRETATION: ClassVar[str] = "现货短中长期积累递增，主力持续加仓"
    _INCREASING_IMPLICATION: ClassVar[str] = "主力持续加仓，方向明确→跟随主力持仓"
    _PERSISTENCE_DIRECTION: ClassVar[SignalDirection] = SignalDirection.NEUTRAL_BULLISH
    _CONFIDENCE: ClassVar[float] = 0.55
    _ACTION_ALERT: ClassVar[str] = ""
