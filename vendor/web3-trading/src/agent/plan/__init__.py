# -*- coding: utf-8 -*-
"""
Agent Plan — Gateway (management and command center).

This package is the orchestration hub that:
- Routes messages to the appropriate Agent (Router)
- Controls which tools each Agent can use (ToolPolicy)
- Injects skills into Agents (via SkillRegistry integration)
- Provides a single dispatch entry point (Gateway)
- Hosts the Task-DAG primitives (TaskPlanner, TaskOrchestrator, …)
- Hosts the OrchestratorAgent (agentType=AUTO)
- Hosts agent decorators (save_step, StopError, …)
"""

from .fast_filter import FastFilter, FilterResult
from .router import Router, RouteResult
from .tool_policy import ToolPolicy
from .decorators import save_step, ConnectionTerminatedError, StopError, enable_connect

from .task_graph import (
    TaskPlanner,
    TaskPlan,
    TaskNode,
    TaskStatus,
    TaskOrchestrator,
    ToolAwareRunner,
)

# Gateway and OrchestratorAgent are lazy-loaded to break the circular import:
#   agent.base → agent.plan (this __init__) → .orchestrator_agent → agent.base
_lazy_cache = {}

def __getattr__(name):
    if name == "OrchestratorAgent":
        if "OrchestratorAgent" not in _lazy_cache:
            from .orchestrator_agent import OrchestratorAgent
            _lazy_cache["OrchestratorAgent"] = OrchestratorAgent
        return _lazy_cache["OrchestratorAgent"]
    if name == "Gateway":
        if "Gateway" not in _lazy_cache:
            from .gateway import Gateway
            _lazy_cache["Gateway"] = Gateway
        return _lazy_cache["Gateway"]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Gateway components
    "FastFilter",
    "FilterResult",
    "Gateway",
    "Router",
    "RouteResult",
    "ToolPolicy",
    # Task-DAG primitives
    "TaskStatus",
    "TaskNode",
    "TaskPlan",
    "TaskPlanner",
    "TaskOrchestrator",
    "ToolAwareRunner",
    # Orchestrator Agent
    "OrchestratorAgent",
    # Decorators
    "save_step",
    "ConnectionTerminatedError",
    "StopError",
    "enable_connect",
]
