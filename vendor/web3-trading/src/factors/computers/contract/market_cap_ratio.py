"""合约资金市值比 — 合约专属因子。"""

from __future__ import annotations

from typing import ClassVar, Set

from ...enums import MarketType
from .._base_flow import _BaseMarketCapRatioComputer


class ContractMarketCapRatioComputer(_BaseMarketCapRatioComputer):
    factor_name: ClassVar[str] = "contract_market_cap_ratio"
    display_name: ClassVar[str] = "资金市值比(合约)"
    description: ClassVar[str] = "合约资金流向与市值比率。"
    supported_markets: ClassVar[Set[MarketType]] = {MarketType.CONTRACT}

    _PRIMARY_IS_SPOT: ClassVar[bool] = False
    _SCORE_MULTIPLIER: ClassVar[float] = 0.8
    _DIRECTION_THRESHOLD: ClassVar[float] = 0.2
    _CONFIDENCE_HIGH: ClassVar[float] = 0.65
    _CONFIDENCE_LOW: ClassVar[float] = 0.40
    _MARKET_LABEL: ClassVar[str] = "合约"
    _PRIMARY_LABEL: ClassVar[str] = "合约"
    _OTHER_LABEL: ClassVar[str] = "现货"
    _IMPLICATION_HIGH: ClassVar[str] = "合约资金关注度高，短期波动可能加剧"
    _IMPLICATION_LOW: ClassVar[str] = "合约资金有一定关注度"
    _ACTION_BULLISH: ClassVar[str] = "合约资金相对市值面偏多，可关注。"
    _ACTION_BEARISH: ClassVar[str] = "合约资金相对市值面偏空。"
    _EVI_BIAS_HIGH: ClassVar[str] = "{prim}投机情绪主导，杠杆资金活跃"
    _EVI_BIAS_LOW: ClassVar[str] = "{prim}投机度低，{other}资金为主"
    _EVI_BIAS_HIGH_IMPLICATION: ClassVar[str] = "投机过热，波动加剧预警，注意风险控制"
    _EVI_BIAS_LOW_IMPLICATION: ClassVar[str] = "市场以中长期持仓为主，短期波动较小"
    _EXTREME_CAP_ENABLED: ClassVar[bool] = True
    _EXTREME_THRESHOLD: ClassVar[float] = 0.02
    _EXTREME_ACTION: ClassVar[str] = "合约市值比极端，波动加剧预警，建议降低杠杆。"
