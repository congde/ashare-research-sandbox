"""现货资金市值比 — 现货专属因子。"""

from __future__ import annotations

from typing import ClassVar, Set

from ...enums import MarketType
from .._base_flow import _BaseMarketCapRatioComputer


class SpotMarketCapRatioComputer(_BaseMarketCapRatioComputer):
    factor_name: ClassVar[str] = "spot_market_cap_ratio"
    display_name: ClassVar[str] = "资金市值比(现货)"
    description: ClassVar[str] = "现货资金流向市值比。"
    supported_markets: ClassVar[Set[MarketType]] = {MarketType.SPOT}

    _PRIMARY_IS_SPOT: ClassVar[bool] = True
    _SCORE_MULTIPLIER: ClassVar[float] = 1.0
    _DIRECTION_THRESHOLD: ClassVar[float] = 0.2
    _CONFIDENCE_HIGH: ClassVar[float] = 0.70
    _CONFIDENCE_LOW: ClassVar[float] = 0.45
    _MARKET_LABEL: ClassVar[str] = "现货"
    _PRIMARY_LABEL: ClassVar[str] = "现货"
    _OTHER_LABEL: ClassVar[str] = "合约"
    _IMPLICATION_HIGH: ClassVar[str] = "现货资金强度高，可能成为板块龙头，优先配置"
    _IMPLICATION_LOW: ClassVar[str] = "现货资金有一定关注度"
    _ACTION_BULLISH: ClassVar[str] = "资金相对市值面关注度较高，可做多。"
    _ACTION_BEARISH: ClassVar[str] = "资金相对市值面偏空。"
    _EVI_BIAS_HIGH: ClassVar[str] = "{prim}资金占比显著高于{other}，中长期持仓为主"
    _EVI_BIAS_HIGH_IMPLICATION: ClassVar[str] = "现货导向资金更可靠，看涨置信度更高"
    _EVI_BIAS_LOW: ClassVar[str] = "{other}投机情绪主导，杠杆资金活跃"
    _EVI_BIAS_LOW_IMPLICATION: ClassVar[str] = "投机过热，波动加剧预警"
