# -*- coding: utf-8 -*-
"""
DAG Reasoning Agent

使用 Plan & DAG Execute 模式的 Agent，支持复杂多任务场景。

特点：
1. 自动任务分解和规划
2. 并行/串行工具调用
3. 最多3次迭代优化
4. 适合复杂查询和多任务场景
"""

import logging
from agent.base import BaseAgent
from agent.dag_execution import DAGExecutionMixin
from agent.schema import AgentType

logger = logging.getLogger(__name__)


class DAGReasoningAgent(DAGExecutionMixin, BaseAgent):
    """
    DAG 推理 Agent
    
    使用 DAG (有向无环图) 模式进行任务规划和执行。
    特别适合：
    - 多步骤复杂查询
    - 需要并行执行的任务
    - 涉及多个数据源的对比分析
    
    示例查询：
    - "比较BTC和ETH的价格，并告诉我AI趋势"
    - "获取BTC的RSI和200-EMA指标"
    - "搜索AI趋势并分析主要特点"
    """
    
    NAME = AgentType.QUICK_REASONING  # 可以定义新的类型
    DESCRIPTION = "DAG-based reasoning agent for complex multi-task queries"
    
    async def _run(self):
        """
        Agent 执行入口
        
        使用 _run_dag_pipeline 替代传统的线性流程：
        - 传统: decide_tools -> call_tools -> generate_response
        - DAG: plan_dag -> execute_dag (多次) -> generate_response
        """
        # 确保 tools_info 已加载（用于 ToolRegistry）
        if not self._tools_info:
            from mcp.mcp_http_client import mcp_client
            tools_info = await mcp_client.get_tools_info()
            self._tools_info = tools_info
            if tools_info:
                logger.info(f"Loaded {len(tools_info.tools)} tools for DAG execution")
            else:
                logger.warning("No tools_info available for DAG execution")
        
        async for event in self._run_dag_pipeline(
            user_query=self.query,
            max_iterations=3,  # 最多3次Plan&Execute迭代
            enable_think=False,
        ):
            yield event


__all__ = ["DAGReasoningAgent"]
