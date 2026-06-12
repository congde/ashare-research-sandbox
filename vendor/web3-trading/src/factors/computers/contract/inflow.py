"""合约多粒度资金净流入 — 合约专属因子。"""

from __future__ import annotations

from typing import ClassVar, Set

from ...enums import MarketType
from .._base_flow import _BaseInflowComputer


class ContractTradeInflowComputer(_BaseInflowComputer):
    factor_name: ClassVar[str] = "contract_trade_inflow"
    display_name: ClassVar[str] = "多粒度资金净流入(合约)"
    description: ClassVar[str] = "合约5分钟~24小时多粒度资金净流入。"
    supported_markets: ClassVar[Set[MarketType]] = {MarketType.CONTRACT}

    _DATA_FIELD: ClassVar[str] = "contract_list"
    _MARKET_LABEL: ClassVar[str] = "合约"
    _OUTFLOW_LABEL: ClassVar[str] = "流出(减仓)"
    _INFLOW_LABEL: ClassVar[str] = "流入(加仓)"
    _OUTFLOW_IMPLICATION: ClassVar[str] = "持续减仓利好上涨"
    _INFLOW_IMPLICATION: ClassVar[str] = "持续加仓利空"
    _ACTION_STRONG_BULL: ClassVar[str] = "多周期一致净流出，主力全面减仓，可积极做多。"
    _ACTION_STRONG_BEAR: ClassVar[str] = "多周期一致净流入，主力全面加仓做空，应减仓或做空。"
    _COUNTER_STRONG_BULL: ClassVar[str] = "若流出是主力平空而非减仓，则看涨信号无效。"
    _COUNTER_STRONG_BEAR: ClassVar[str] = "若流入是散户追空而非主力加仓，下跌空间可能有限。"
    _CONCLUSION_STRONG_BULL: ClassVar[str] = "各周期一致净流出，主力全面减仓，强烈看涨信号。"
    _CONCLUSION_BULLISH: ClassVar[str] = "多周期偏流出，主力偏多。"
    _CONCLUSION_STRONG_BEAR: ClassVar[str] = "各周期一致净流入，主力全面加仓做空，强烈看跌信号。"
    _LIMITATION_1: ClassVar[str] = "合约资金流出可能是平空而非减仓"
