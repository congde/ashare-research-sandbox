"""现货多粒度资金净流入 — 现货专属因子。"""

from __future__ import annotations

from typing import ClassVar, Set

from ...enums import MarketType
from .._base_flow import _BaseInflowComputer


class SpotTradeInflowComputer(_BaseInflowComputer):
    factor_name: ClassVar[str] = "spot_trade_inflow"
    display_name: ClassVar[str] = "多粒度资金净流入(现货)"
    description: ClassVar[str] = "现货5分钟~24小时多粒度资金净流入。"
    supported_markets: ClassVar[Set[MarketType]] = {MarketType.SPOT}

    _DATA_FIELD: ClassVar[str] = "spot_goods_list"
    _MARKET_LABEL: ClassVar[str] = "现货"
    _OUTFLOW_LABEL: ClassVar[str] = "流出(囤币)"
    _INFLOW_LABEL: ClassVar[str] = "流入(抛压)"
    _OUTFLOW_IMPLICATION: ClassVar[str] = "持续囤币利好上涨"
    _INFLOW_IMPLICATION: ClassVar[str] = "持续抛压利空"
    _ACTION_STRONG_BULL: ClassVar[str] = "多周期一致净流出，主力全面囤币，可积极做多。"
    _ACTION_STRONG_BEAR: ClassVar[str] = "多周期一致净流入，主力全面派发，应减仓或做空。"
    _COUNTER_STRONG_BULL: ClassVar[str] = "若流出是OTC大宗交易而非囤币，则看涨信号无效。"
    _COUNTER_STRONG_BEAR: ClassVar[str] = "若流入是散户追涨而非主力派发，下跌空间可能有限。"
    _CONCLUSION_STRONG_BULL: ClassVar[str] = "各周期一致净流出，主力全面囤币，强烈看涨信号。"
    _CONCLUSION_BULLISH: ClassVar[str] = "多周期偏流出，主力偏多。"
    _CONCLUSION_STRONG_BEAR: ClassVar[str] = "各周期一致净流入，主力全面派发，强烈看跌信号。"
    _LIMITATION_1: ClassVar[str] = "资金流出可能是OTC大宗交易而非囤币"
