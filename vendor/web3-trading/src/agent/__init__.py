# -*- coding: utf-8 -*-
'''
@Time    :   2025/08/18 19:53:57
'''

from .quick_reasoning import QuickReasoningAgent
from .deep_research import DeepResearchAgent
from .deep_think import DeepThinkAgent
from .event_delivery import EventDeliveryAgent
from .currency_insight import CurrencyInsightAgent
from .dag_reasoning import DAGReasoningAgent
from .customer_service import CustomerServiceAgent

# Tools package (tool system + loop + subagent)
from .tools import (
    BaseTool, ToolResult, ToolRegistry, MCPToolAdapter,
    AgentLoop, LoopEvent, LoopEventType,
    SubagentManager, SubagentResult,
)

# Skills package (skill system + workflow engine)
from .skills import (
    BaseWorkflowState,
    WorkflowBuilder,
    WorkflowRunner,
    create_plan_execute_synthesize_workflow,
    create_conditional_workflow,
)

# DAG Execution modules
from .dag_executor import DAGPlan, DAGTask, DAGExecutor, DAGExecutionResult
from .dag_execution import DAGExecutionMixin

# Plan package (gateway + task-DAG + orchestrator + decorators)
from .plan import (
    Gateway, Router, RouteResult, ToolPolicy,
    TaskPlanner, TaskPlan, TaskNode, TaskStatus,
    TaskOrchestrator, ToolAwareRunner,
    OrchestratorAgent,
)

from .schema import AgentType


# AUTO 与 DEEP_THINK 统一由 DeepThinkAgent 处理，是否走自动编排（plan + DAG）由 deep_think 内 plan() 结果自动判断
ALL_AGENTS = {
    # QuickReasoningAgent.NAME: QuickReasoningAgent,
    DeepThinkAgent.NAME: DeepThinkAgent,
    DeepResearchAgent.NAME: DeepResearchAgent,
    EventDeliveryAgent.NAME: EventDeliveryAgent,
    DAGReasoningAgent.NAME: DAGReasoningAgent,
    CustomerServiceAgent.NAME: CustomerServiceAgent,
    AgentType.AUTO: DeepThinkAgent,
}
