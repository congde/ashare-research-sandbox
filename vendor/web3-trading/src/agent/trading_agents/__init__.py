# -*- coding: utf-8 -*-
"""
TauricResearch / TradingAgents 集成层。

`use_trading_agents: true` 时，DeepThink 在需要工具的分析路径上优先调用
`TradingAgentsGraph`（yfinance 等上游），替代本服务原 MCP 工具 DAG。

未安装 `tradingagents` 包时自动回退为原有 DAG 行为。
"""

from agent.trading_agents.compat import (
    get_resolved_trading_graph_class,
    is_trading_agents_available,
)

__all__ = [
    "is_trading_agents_available",
    "get_resolved_trading_graph_class",
]
