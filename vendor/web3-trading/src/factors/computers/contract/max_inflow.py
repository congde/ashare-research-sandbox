"""合约主力资金积累 — 合约专属因子。"""

from __future__ import annotations

from typing import ClassVar, Set

from ...enums import MarketType
from .._base_flow import _BaseMaxInflowComputer


class ContractMaxInflowComputer(_BaseMaxInflowComputer):
    factor_name: ClassVar[str] = "contract_max_inflow"
    display_name: ClassVar[str] = "主力资金积累(合约)"
    description: ClassVar[str] = "90天合约最大流入量——主力介入规模。"
    supported_markets: ClassVar[Set[MarketType]] = {MarketType.CONTRACT}

    _PRIMARY_IS_SPOT: ClassVar[bool] = False
    _MARKET_LABEL: ClassVar[str] = "合约"
    _OTHER_LABEL: ClassVar[str] = "现货"
    _DIR_FACTOR_SPOT_DOM: ClassVar[float] = 0.6
    _DIR_FACTOR_CONTRACT_DOM: ClassVar[float] = 0.2
    _DIR_FACTOR_BALANCED: ClassVar[float] = 0.2
    _FOCUS_SPOT_DOM: ClassVar[str] = "主力偏重现货布局"
    _FOCUS_CONTRACT_DOM: ClassVar[str] = "主力偏重合约博弈"
    _FOCUS_BALANCED: ClassVar[str] = "现货合约积累均衡"
    _IMPLICATION_SPOT_DOM: ClassVar[str] = "现货积累主导:基本面驱动，偏多"
    _IMPLICATION_CONTRACT_DOM: ClassVar[str] = "合约主导:杠杆博弈加剧，顺势跟进但注意风险"
    _IMPLICATION_BALANCED: ClassVar[str] = "现货合约均衡"
    _CONFIDENCE_HIGH: ClassVar[float] = 0.65
    _CONFIDENCE_LOW: ClassVar[float] = 0.45
    _ACTION_BULLISH: ClassVar[str] = "主力资金偏向现货积累，基本面驱动，偏多。"
    _ACTION_BEARISH: ClassVar[str] = "偏空信号，注意风险。"
