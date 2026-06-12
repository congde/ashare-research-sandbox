"""合约多周期资金趋势一致性 — 合约专属因子。"""

from __future__ import annotations

from typing import ClassVar, Set

from ...enums import MarketType
from .._base_flow import _BaseConsistencyComputer


class ContractConsistencyComputer(_BaseConsistencyComputer):
    factor_name: ClassVar[str] = "contract_consistency"
    display_name: ClassVar[str] = "多周期资金趋势一致性(合约)"
    description: ClassVar[str] = "合约短中长期资金方向一致性。"
    supported_markets: ClassVar[Set[MarketType]] = {MarketType.CONTRACT}

    _DATA_FIELD: ClassVar[str] = "contract_list"
    _MARKET_LABEL: ClassVar[str] = "合约"
    _ACTION_STRONG_BULL: ClassVar[str] = "短中长期资金一致净流出，全级别主力减仓，可积极做多。"
    _ACTION_STRONG_BEAR: ClassVar[str] = "全级别资金流入，做空压力沉重，应减仓或做空。"
    _ACTION_BULLISH: ClassVar[str] = "多数周期偏多，关注短期是否持续。"
    _ACTION_BEARISH: ClassVar[str] = "多数周期偏空，防范下跌。"
    _IMPLICATION_ALL_BULL: ClassVar[str] = "短中长期一致净流出，全级别合约减仓，最强看涨信号"
    _IMPLICATION_ALL_BEAR: ClassVar[str] = "短中长期一致净流入，全级别合约加仓做空，最强看跌信号"
    _COUNTER_STRONG_BULL: ClassVar[str] = "若流出是主力平多而非减仓做空，则看涨信号无效。"
    _COUNTER_STRONG_BEAR: ClassVar[str] = "若流入是主力平空而非加仓做空，则看跌信号无效。"
