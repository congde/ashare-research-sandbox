# -*- coding: utf-8 -*-
"""
KucoinTradingAgentsGraph

子类化上游 TradingAgentsGraph，仅替换 _create_tool_nodes 为
ValueScan / KuCoin 公共 API 工具，避免 yfinance 成为行情事实源。

上游包未安装时本模块不加载。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from langgraph.prebuilt import ToolNode

from agent.trading_agents.crypto_ta_tools import build_kucoin_tool_nodes

logger = logging.getLogger(__name__)

_KucoinClass = None


def get_kucoin_trading_agents_graph_class():
    global _KucoinClass
    if _KucoinClass is not None:
        return _KucoinClass
    try:
        from tradingagents.graph.trading_graph import TradingAgentsGraph
    except Exception as e:
        logger.warning("Cannot import TradingAgentsGraph: %s", e)
        return None

    class KucoinTradingAgentsGraph(TradingAgentsGraph):
        def _create_tool_nodes(self) -> Dict[str, ToolNode]:
            return build_kucoin_tool_nodes()

    _KucoinClass = KucoinTradingAgentsGraph
    return _KucoinClass
