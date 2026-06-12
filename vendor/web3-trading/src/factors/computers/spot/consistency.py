"""现货多周期资金趋势一致性 — 现货专属因子。"""

from __future__ import annotations

from typing import ClassVar, Set

from ...enums import MarketType
from .._base_flow import _BaseConsistencyComputer


class SpotConsistencyComputer(_BaseConsistencyComputer):
    factor_name: ClassVar[str] = "spot_consistency"
    display_name: ClassVar[str] = "多周期资金趋势一致性(现货)"
    description: ClassVar[str] = "现货短中长期资金流向一致性。"
    supported_markets: ClassVar[Set[MarketType]] = {MarketType.SPOT}

    _DATA_FIELD: ClassVar[str] = "spot_goods_list"
    _MARKET_LABEL: ClassVar[str] = "现货"
    _ACTION_STRONG_BULL: ClassVar[str] = "短中长期资金一致净流出，全级别主力囤币，可积极做多。"
    _ACTION_STRONG_BEAR: ClassVar[str] = "全级别资金流入，抛压沉重，应减仓或做空。"
    _ACTION_BULLISH: ClassVar[str] = "多数周期偏多，关注短期是否持续。"
    _ACTION_BEARISH: ClassVar[str] = "多数周期偏空，防范下跌。"
    _IMPLICATION_ALL_BULL: ClassVar[str] = "短中长期一致净流出，全级别囤币，最强看涨信号"
    _IMPLICATION_ALL_BEAR: ClassVar[str] = "短中长期一致净流入，全级别抛压，最强看跌信号"
