"""现货主力资金积累 — 现货专属因子。"""

from __future__ import annotations

from typing import ClassVar, Set

from ...enums import MarketType
from .._base_flow import _BaseMaxInflowComputer


class SpotMaxInflowComputer(_BaseMaxInflowComputer):
    factor_name: ClassVar[str] = "spot_max_inflow"
    display_name: ClassVar[str] = "主力资金积累(现货)"
    description: ClassVar[str] = "现货90天最大资金流入，反映主力介入规模。"
    supported_markets: ClassVar[Set[MarketType]] = {MarketType.SPOT}

    _PRIMARY_IS_SPOT: ClassVar[bool] = True
    _MARKET_LABEL: ClassVar[str] = "现货"
    _OTHER_LABEL: ClassVar[str] = "合约"
    _DIR_FACTOR_SPOT_DOM: ClassVar[float] = 1.0
    _DIR_FACTOR_CONTRACT_DOM: ClassVar[float] = -0.5
    _DIR_FACTOR_BALANCED: ClassVar[float] = 0.3
    _FOCUS_SPOT_DOM: ClassVar[str] = "主力偏重现货布局"
    _FOCUS_CONTRACT_DOM: ClassVar[str] = "主力偏重合约博弈"
    _FOCUS_BALANCED: ClassVar[str] = "现货合约积累均衡"
    _IMPLICATION_SPOT_DOM: ClassVar[str] = "现货积累主导:主力偏重现货布局，偏多"
    _IMPLICATION_CONTRACT_DOM: ClassVar[str] = "合约积累主导:主力偏重合约博弈，偏空"
    _IMPLICATION_BALANCED: ClassVar[str] = "现货合约均衡"
    _CONFIDENCE_HIGH: ClassVar[float] = 0.70
    _CONFIDENCE_LOW: ClassVar[float] = 0.50
    _ACTION_BULLISH: ClassVar[str] = "主力现货积累显著，看涨。"
    _ACTION_BEARISH: ClassVar[str] = "主力现货偏空，注意风险。"
