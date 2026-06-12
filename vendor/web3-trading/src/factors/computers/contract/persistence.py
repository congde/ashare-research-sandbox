"""合约资金积累持续性 — 合约专属因子。"""

from __future__ import annotations

from typing import ClassVar, Set

from ...enums import MarketType, SignalDirection
from .._base_flow import _BasePersistenceComputer


class ContractPersistenceComputer(_BasePersistenceComputer):
    factor_name: ClassVar[str] = "contract_persistence"
    display_name: ClassVar[str] = "资金积累持续性(合约)"
    description: ClassVar[str] = "合约主力跨时间周期的积累持续性。"
    supported_markets: ClassVar[Set[MarketType]] = {MarketType.CONTRACT}

    _DATA_FIELD: ClassVar[str] = "contract_list"
    _MARKET_LABEL: ClassVar[str] = "合约"
    _INCREASING_INTERPRETATION: ClassVar[str] = "合约短中长期积累递增，空头持仓持续堆积"
    _INCREASING_IMPLICATION: ClassVar[str] = "空头持仓持续堆积，下行压力增加"
    _PERSISTENCE_DIRECTION: ClassVar[SignalDirection] = SignalDirection.NEUTRAL_BEARISH
    _CONFIDENCE: ClassVar[float] = 0.50
    _ACTION_ALERT: ClassVar[str] = "合约空头持仓持续堆积，注意下行风险。"
