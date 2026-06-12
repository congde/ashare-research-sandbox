# -*- coding: utf-8 -*-
"""
WorkflowExecutor — DAG-based workflow execution engine.

Parses graph_data into a topologically sorted plan, executes nodes in DAG order
with asyncio.gather for parallel branches. A lightweight facade provides
snapshot/cancel hooks; workflow runs do not construct chat ConversationRuntime.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import sys
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime
from string import Template
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

_ACTIVE_EXECUTORS: Dict[str, "WorkflowExecutor"] = {}

_MAX_SUBWORKFLOW_DEPTH = 5


class _WorkflowRuntimeFacade:
    """Snapshot / interrupt surface for workflow runs (not chat ConversationRuntime)."""

    __slots__ = ("_executor",)

    def __init__(self, executor: "WorkflowExecutor") -> None:
        self._executor = executor

    def request_interrupt(self, reason: str = "user_cancel") -> None:
        self._executor._cancel_requested = True
        logger.debug("Workflow run interrupt requested: %s", reason)

    def snapshot(self) -> dict:
        ex = self._executor
        return {
            "kind": "workflow_run",
            "run_id": ex._run_id,
            "workspace_id": ex._workspace_id,
            "workflow_id": ex._workflow.get("id"),
            "nodes_total": len(ex._nodes),
            "nodes_completed": len(ex._node_results),
            "cancel_requested": bool(ex._cancel_requested),
            "nesting_depth": ex._nesting_depth,
        }


