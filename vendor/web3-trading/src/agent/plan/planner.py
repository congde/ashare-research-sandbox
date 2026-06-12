# -*- coding: utf-8 -*-
"""
Backward-compatible re-exports.

The canonical home for these symbols is now agent.plan.task_graph.
This module is kept so existing `from agent.plan.planner import ...` continues to work.
"""

from agent.plan.task_graph import (  # noqa: F401
    TaskStatus,
    TaskNode,
    TaskPlan,
    TaskPlanner,
)

# Also re-export the route prompt (now lives in router.py)
from agent.plan.router import ROUTE_SYSTEM_PROMPT  # noqa: F401

__all__ = [
    "TaskStatus",
    "TaskNode",
    "TaskPlan",
    "TaskPlanner",
    "ROUTE_SYSTEM_PROMPT",
]
