# -*- coding: utf-8 -*-
"""
Task Graph — DAG primitives, LLM-based task decomposition, and execution engine.

Moved out of agent/plan/ so that plan/ can focus on Gateway concerns
(routing, session, skill injection, tool policy).

Key concepts:
- TaskNode: a unit of work with optional tool_name, dependency edges, and context flow
- TaskPlan: a DAG of TaskNodes with topological ordering for execution
- TaskPlanner: LLM-based decomposition / tool-level DAG planning
- TaskOrchestrator: DAG execution engine with parallel dispatch
- ToolAwareRunner: executes MCP tool nodes directly + LLM synthesis nodes
"""

import asyncio
import json
import logging
import time
import uuid
from enum import Enum
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Set

from dataclasses import dataclass, field
from pydantic import BaseModel, Field

from llm.llm import llm

logger = logging.getLogger(__name__)


# ============================================================
# Task Graph Primitives
# ============================================================

class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class TaskNode:
    """
    A single node in the task execution DAG.

    Supports both agent-level routing and tool-level orchestration.
    When tool_name is set, the orchestrator executes the MCP tool directly
    instead of delegating to a full agent.
    """
    task_id: str
    agent_type: str
    query: str
    tool_name: Optional[str] = None
    tool_arguments: Dict[str, Any] = field(default_factory=dict)
    context_from: List[str] = field(default_factory=list)
    depends_on: Set[str] = field(default_factory=set)
    priority: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[Any] = None
    error: Optional[str] = None
    elapsed_ms: int = 0
    retry_count: int = 0
    _tool_call_id: Optional[str] = field(default=None, init=False, repr=False)

    @property
    def raw_result(self) -> Any:
        if self.result is not None:
            try:
                return json.loads(self.result)
            except Exception:
                return self.result
            
    @property
    def enable_reply(self) -> bool:
        if isinstance(self.raw_result, dict) and self.raw_result.get("disable_llm"):
            return False
        return True

    @property
    def tool_call_id(self) -> Optional[str]:
        if self.tool_name is None:
            return None
        if self._tool_call_id is None:
            self._tool_call_id = f"call_{uuid.uuid4().hex[:24]}"
        return self._tool_call_id

    @property
    def is_tool_node(self) -> bool:
        return self.tool_name is not None

    @property
    def is_terminal(self) -> bool:
        return self.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED)


@dataclass
class TaskPlan:
    """
    An execution plan consisting of a DAG of TaskNodes.

    The plan maintains topological ordering so the orchestrator can determine
    which tasks are ready to run at any point.
    """
    plan_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    tasks: Dict[str, TaskNode] = field(default_factory=dict)
    root_query: str = ""
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_task(self, node: TaskNode) -> None:
        self.tasks[node.task_id] = node

    def get_ready_tasks(self) -> List[TaskNode]:
        ready = []
        for node in self.tasks.values():
            if node.status != TaskStatus.PENDING:
                continue
            deps_met = all(
                self.tasks[dep_id].status == TaskStatus.COMPLETED
                for dep_id in node.depends_on
                if dep_id in self.tasks
            )
            if deps_met:
                ready.append(node)
        ready.sort(key=lambda n: -n.priority)
        return ready

    def get_failed_tasks(self) -> List[TaskNode]:
        return [n for n in self.tasks.values() if n.status == TaskStatus.FAILED]

    @property
    def is_complete(self) -> bool:
        return all(n.is_terminal for n in self.tasks.values())

    @property
    def task_count(self) -> int:
        return len(self.tasks)

    @property
    def execution_layers(self) -> List[List[str]]:
        remaining = {tid for tid in self.tasks}
        layers = []
        while remaining:
            layer = []
            for tid in list(remaining):
                node = self.tasks[tid]
                if node.depends_on.issubset(set(self.tasks.keys()) - remaining):
                    layer.append(tid)
            if not layer:
                layer = list(remaining)
                remaining.clear()
            else:
                for tid in layer:
                    remaining.discard(tid)
            layers.append(layer)
        return layers

    def get_completed_context(self) -> Dict[str, str]:
        """Collect results from all completed tasks for replanning context."""
        return {
            tid: str(node.result)
            for tid, node in self.tasks.items()
            if node.status == TaskStatus.COMPLETED and node.result
        }

    def get_pending_dependents(self, failed_ids: Set[str]) -> Set[str]:
        """Find all PENDING tasks that transitively depend on the given failed task IDs."""
        affected: Set[str] = set()
        changed = True
        while changed:
            changed = False
            for tid, node in self.tasks.items():
                if tid in affected or tid in failed_ids:
                    continue
                if node.status != TaskStatus.PENDING:
                    continue
                if node.depends_on & (failed_ids | affected):
                    affected.add(tid)
                    changed = True
        return affected

    def mark_subtree_skipped(self, failed_ids: Set[str]) -> List[str]:
        """Mark failed tasks and their pending dependents as SKIPPED. Returns skipped IDs."""
        dependents = self.get_pending_dependents(failed_ids)
        skipped = []
        for tid in dependents:
            node = self.tasks[tid]
            node.status = TaskStatus.SKIPPED
            node.error = "Skipped due to dependency failure (pre-replan)"
            skipped.append(tid)
        return skipped

    def merge_replan(self, new_plan: "TaskPlan") -> List[str]:
        """Merge tasks from a replan into this plan. Returns list of added task IDs."""
        added = []
        for tid, node in new_plan.tasks.items():
            if tid not in self.tasks:
                valid_deps = set()
                for dep_id in node.depends_on:
                    if dep_id in self.tasks or dep_id in new_plan.tasks:
                        valid_deps.add(dep_id)
                node.depends_on = valid_deps
                self.tasks[tid] = node
                added.append(tid)
        return added

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "root_query": self.root_query,
            "task_count": self.task_count,
            "layers": self.execution_layers,
            "tasks": {
                tid: {
                    "agent_type": n.agent_type,
                    "query": n.query,
                    "tool_name": n.tool_name,
                    "tool_arguments": n.tool_arguments,
                    "context_from": n.context_from,
                    "depends_on": list(n.depends_on),
                    "priority": n.priority,
                    "status": n.status.value,
                }
                for tid, n in self.tasks.items()
            },
        }


# ============================================================
# TaskPlanner — decomposition + tool-level DAG planning
# ============================================================

DECOMPOSE_SYSTEM_PROMPT = """\
You are a task decomposition engine for an AI crypto assistant.
Given a complex user query, break it into smaller sub-tasks that can be \
executed in parallel or sequentially.

Available agent types for sub-tasks:
- QUICK_REASONING: Simple lookups, basic Q&A
- DEEP_THINK: Analytical reasoning with tool calls

For each sub-task, specify:
- task_id: short unique id (e.g. "t1", "t2")
- agent_type: which agent handles it
- query: the sub-question to answer
- depends_on: list of task_ids that must complete first (empty if independent)
- priority: integer, higher = more important (default 0)

Rules:
1. Minimize the number of sub-tasks (2-5 is ideal).
2. Maximize parallelism — only add dependencies when truly needed.
3. The final sub-task should be a synthesis step that combines results.
4. Respond with ONLY a JSON object, no extra text.

Output format (strict JSON):
{
  "tasks": [
    {"task_id": "t1", "agent_type": "QUICK_REASONING", "query": "...", "depends_on": [], "priority": 1},
    {"task_id": "t2", "agent_type": "DEEP_THINK", "query": "...", "depends_on": ["t1"], "priority": 0}
  ],
  "reasoning": "brief explanation of decomposition strategy"
}
"""

TOOL_PLAN_SYSTEM_PROMPT = """\
You are a tool orchestration planner for an AI crypto assistant.
Given a user query and a list of available MCP tools, produce an execution \
plan that specifies which tools to call, with what arguments, and in what order.

**IMPORTANT**: The `query` field of each task is user-facing text. Write it in \
the same language as the user's query. If the user writes in Chinese, write task \
queries in Chinese. If in English, use English. Match the user's language.

## Available tools
{tools_description}

## Planning rules
1. Each task is either a **tool node** (calls a specific MCP tool) or a \
**synthesis node** (no tool_name; aggregates results from previous tasks via LLM).
2. Independent tool calls MUST be placed in the same layer (no artificial dependencies) \
so they execute in parallel.
3. Only add depends_on when a task genuinely needs the output of an earlier task.
4. Return a single task with tool_name=null ONLY for trivial chitchat: pure greetings \
("hi", "你好"), identity questions ("who are you", "你是谁"), or platform name \
questions ("what is KuCoin"). For ANY other query — prices, news, analysis, \
ETF/stock/crypto screening, weather, market trends, technical indicators, \
投资分析, 行情查询, 天气, 筛选币种, 走势分析, 市场动态 — ALWAYS use at least \
one tool (prefer web_search if no specific tool matches).
5. Keep plans small: 1-5 tasks. Do NOT over-decompose.
6. The final task should usually be a synthesis node that depends on all tool tasks, \
UNLESS there is only one tool call (then no synthesis needed).
7. Respond with ONLY a JSON object, no markdown fences, no extra text.
8. **Multi-angle search strategy**: For complex crypto analysis queries (market analysis, \
trading opportunities, investment strategies, contract long/short analysis), decompose \
into 2-3 parallel web_search calls with different query angles to gather comprehensive data. \
The query angles should cover multiple dimensions of the user's question. Common angles include: \
(a) price & technical data: "<coin> price support resistance levels technical analysis", \
(b) derivatives / on-chain data: "<coin> futures funding rate open interest data", \
(c) macro context: "central bank monetary policy crypto market impact". \
Replace <coin> with the actual cryptocurrency mentioned in the user's query. \
Each web_search call should be an independent task with no dependencies between them, \
so they execute in parallel. This ensures the final response has enough multi-dimensional \
data to provide specific, actionable trading insights rather than generic advice.

## Output format (strict JSON)
{{
  "tasks": [
    {{
      "task_id": "t1",
      "tool_name": "<tool name or null>",
      "tool_arguments": {{}},
      "query": "<what this task does — MUST match user's language>",
      "depends_on": [],
      "priority": 1
    }}
  ],
  "reasoning": "<brief explanation>"
}}
"""

REPLAN_SYSTEM_PROMPT = """\
You are a task replanning engine for an AI crypto assistant.
A previous execution plan partially failed. Your job is to create \
an alternative plan for the remaining work, leveraging what already succeeded.

## Available tools
{tools_description}

## Already completed (do NOT re-execute; reference their task_ids if needed)
{completed_context}

## Failed tasks
{failed_context}

## Replanning rules
1. Do NOT duplicate work that already succeeded.
2. Try alternative approaches for failed tasks — different tools, rephrased \
queries, or a simplified scope.
3. If a tool consistently fails, omit it and plan around the gap.
4. New tasks MAY list already-completed task_ids in depends_on to consume \
their results as context.
5. Keep plans small: 1-3 tasks. The final task should be a synthesis node \
(tool_name=null) ONLY if there are multiple new tool tasks.
6. Use task_id prefix "r" to avoid ID collisions (e.g. "r1", "r2").
7. Respond with ONLY a JSON object, no markdown fences, no extra text.

## Output format (strict JSON)
{{
  "tasks": [
    {{
      "task_id": "r1",
      "tool_name": "<tool name or null>",
      "tool_arguments": {{}},
      "query": "<what this task does>",
      "depends_on": [],
      "priority": 1
    }}
  ],
  "reasoning": "<brief explanation of replanning strategy>"
}}
"""

SYNTHESIS_SYSTEM_PROMPT = """\
You are a result synthesis engine. You receive the outputs of multiple \
sub-tasks that were executed to answer a user's original query.

Your job:
1. Merge and deduplicate the information from all sub-task results.
2. Produce a coherent, well-structured answer to the original query.
3. Preserve important details, data points, and citations.
4. Use the same language as the original query.
5. If any sub-task failed, note the gap but still provide the best answer from available results.

Respond with the synthesized answer directly, no JSON wrapper needed.
"""


class PlannedTask(BaseModel):
    """Schema for a single task in a replan."""
    task_id: str = Field(..., description="Unique task ID, prefixed with 'r'")
    tool_name: Optional[str] = Field(None, description="MCP tool name or null for synthesis")
    tool_arguments: Dict[str, Any] = Field(default_factory=dict, description="Tool arguments")
    query: str = Field(..., description="Task description or query")
    depends_on: List[str] = Field(default_factory=list, description="Dependency task IDs")
    priority: int = Field(default=1, description="Priority level")


class PlanResponse(BaseModel):
    """Schema for replan response from LLM."""
    tasks: List[PlannedTask] = Field(..., description="List of replanned tasks")
    reasoning: str = Field(..., description="Brief explanation of replanning strategy")



class TaskPlanner:
    """
    Produces a TaskPlan from a user query via LLM-based decomposition
    or tool-level DAG planning.

    Modes:
    - decompose(): break complex queries into parallel/sequential sub-tasks
    - plan_tools(): tool-aware planning with MCP tool catalogue
    - plan(): auto-select mode based on route result and tools_info
    """

    COMPLEXITY_KEYWORDS = {
        "compare", "comparison", "versus", "vs",
        "analyze", "analyse", "分析",
        "multiple", "several", "各",
        "report", "报告", "research", "研究",
        "comprehensive", "全面", "详细",
        "step by step", "分步",
    }

    def __init__(self, llm, model_name: str, extra_body: Optional[Dict] = None, timeout: float = 15.0):
        self.llm = llm
        self.model_name = model_name
        self.extra_body = extra_body
        self.timeout = timeout

    async def plan(
        self,
        query: str,
        route_result: Optional[Dict] = None,
        history: Optional[List[Dict]] = None,
        metadata: Optional[Dict] = None,
        tools_info=None,
    ) -> TaskPlan:
        """
        Auto-select planning mode and produce a TaskPlan.

        Args:
            query: User query.
            route_result: Pre-computed route result from Router (agent_type, needs_tools, etc.).
            history: Conversation history.
            metadata: Extra metadata.
            tools_info: ToolsInfo from mcp_client. If provided and needs_tools, triggers plan_tools().
        """
        metadata = metadata or {}
        route_result = route_result or {}

        agent_type = route_result.get("agent_type", "QUICK_REASONING")
        needs_tools = route_result.get("needs_tools", True)

        if metadata.get("eventId"):
            return self._build_single_task_plan(query, "EVENT_DELIVERY", metadata)

        if agent_type == "DEEP_RESEARCH":
            return self._build_single_task_plan(query, "DEEP_RESEARCH", metadata)

        if needs_tools and tools_info is not None:
            try:
                plan = await self.plan_tools(query, tools_info, history, metadata)
                plan.metadata["route_agent_type"] = agent_type
                return plan
            except Exception as e:
                logger.warning(
                    f"Tool planning failed, falling back to single-task plan: {e}"
                )
                return self._build_single_task_plan(query, agent_type, metadata)

        return self._build_single_task_plan(query, agent_type, metadata)

    async def decompose(
        self,
        query: str,
        history: Optional[List[Dict]] = None,
        metadata: Optional[Dict] = None,
    ) -> TaskPlan:
        start = time.time()
        messages = [
            {"role": "system", "content": DECOMPOSE_SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ]

        response = await self.llm.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=0.2,
            max_tokens=800,
            timeout=self.timeout,
            **({"extra_body": self.extra_body} if self.extra_body else {}),
        )
        content = response.choices[0].message.content or ""
        result = self._parse_json(content)

        plan = TaskPlan(root_query=query, metadata=metadata or {})
        raw_tasks = result.get("tasks", [])

        if not raw_tasks:
            logger.warning("Decomposition returned no tasks, falling back to single-task plan")
            return self._build_single_task_plan(query, "QUICK_REASONING", metadata or {})

        for t in raw_tasks:
            deps = set(t.get("depends_on", []))
            node = TaskNode(
                task_id=t.get("task_id", uuid.uuid4().hex[:6]),
                agent_type=t.get("agent_type", "QUICK_REASONING"),
                query=t.get("query", query),
                tool_name=t.get("tool_name"),
                tool_arguments=t.get("tool_arguments") or {},
                context_from=t.get("context_from", []),
                depends_on=deps,
                priority=t.get("priority", 0),
                metadata=metadata or {},
            )
            plan.add_task(node)

        elapsed = int((time.time() - start) * 1000)
        plan.metadata["decompose_reasoning"] = result.get("reasoning", "")
        plan.metadata["decompose_elapsed_ms"] = elapsed
        logger.info(f"TaskPlanner.decompose: {plan.task_count} tasks, layers={plan.execution_layers}, elapsed={elapsed}ms")
        return plan

    async def plan_tools(
        self,
        query: str,
        tools_info,
        history: Optional[List[Dict]] = None,
        metadata: Optional[Dict] = None,
    ) -> TaskPlan:
        start = time.time()

        tools_desc = self._format_tools_description(tools_info)
        system_prompt = TOOL_PLAN_SYSTEM_PROMPT.format(tools_description=tools_desc)

        messages = [
            {"role": "system", "content": system_prompt},
        ]
        if history:
            valid = [m for m in history[-6:] if isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)]
            messages.extend(valid)
        messages.append({"role": "user", "content": query})

        response = await self.llm.chat.completions.parse(
            model=self.model_name,
            messages=messages,
            temperature=0.1,
            max_tokens=2000,
            timeout=self.timeout,
            response_format=PlanResponse,
            **(({"extra_body": self.extra_body} if self.extra_body else {})),
        )
        parsed: PlanResponse = response.choices[0].message.parsed

        plan = TaskPlan(root_query=query, metadata=metadata or {})
        raw_tasks = parsed.tasks if parsed else []

        if not raw_tasks:
            logger.warning("Tool planning returned no tasks, building direct_response plan")
            return self._build_single_tool_plan(query, None, {}, metadata or {})

        for t in raw_tasks:
            deps = set(t.depends_on)
            node = TaskNode(
                task_id=t.task_id or uuid.uuid4().hex[:6],
                agent_type="TOOL_EXEC" if t.tool_name else "SYNTHESIS",
                query=t.query or query,
                tool_name=t.tool_name,
                tool_arguments=t.tool_arguments or {},
                context_from=list(deps),
                depends_on=deps,
                priority=t.priority,
                metadata=metadata or {},
            )
            plan.add_task(node)

        elapsed = int((time.time() - start) * 1000)
        plan.metadata["plan_mode"] = "tool_plan"
        plan.metadata["plan_reasoning"] = parsed.reasoning if parsed else ""
        plan.metadata["plan_elapsed_ms"] = elapsed
        logger.info(
            f"TaskPlanner.plan_tools: {plan.task_count} tasks, "
            f"layers={plan.execution_layers}, elapsed={elapsed}ms"
        )
        return plan

    async def replan(
        self,
        original_query: str,
        completed_context: Dict[str, str],
        failed_nodes: List[TaskNode],
        tools_info,
        history: Optional[List[Dict]] = None,
        metadata: Optional[Dict] = None,
    ) -> Optional[TaskPlan]:
        """
        Produce a new sub-plan to recover from task failures.

        Uses completed results as context and tries alternative approaches
        for the work that failed or was blocked.

        Returns None if replanning is not possible (e.g. LLM error).
        """
        start = time.time()

        tools_desc = self._format_tools_description(tools_info)

        completed_parts = []
        for tid, result_text in completed_context.items():
            completed_parts.append(f"- {tid}: {result_text[:500]}")
        completed_str = "\n".join(completed_parts) if completed_parts else "(none)"

        failed_parts = []
        for node in failed_nodes:
            failed_parts.append(
                f"- {node.task_id} (tool={node.tool_name}, query={node.query}): "
                f"error={node.error}"
            )
        failed_str = "\n".join(failed_parts)

        system_prompt = REPLAN_SYSTEM_PROMPT.format(
            tools_description=tools_desc,
            completed_context=completed_str,
            failed_context=failed_str,
        )

        messages = [
            {"role": "system", "content": system_prompt},
        ]
        if history:
            valid = [
                m for m in history[-4:]
                if isinstance(m, dict) and m.get("role") in ("user", "assistant")
                and isinstance(m.get("content"), str)
            ]
            messages.extend(valid)
        messages.append({"role": "user", "content": original_query})

        try:
            response = await self.llm.chat.completions.parse(
                model=self.model_name,
                messages=messages,
                temperature=0.2,
                max_tokens=2000,
                timeout=self.timeout,
                response_format=PlanResponse,
                **(({"extra_body": self.extra_body} if self.extra_body else {})),
            )
            parsed: PlanResponse = response.choices[0].message.parsed

            raw_tasks = parsed.tasks if parsed else []
            if not raw_tasks:
                logger.warning("Replan returned no tasks")
                return None

            plan = TaskPlan(root_query=original_query, metadata=metadata or {})
            for t in raw_tasks:
                deps = set(t.depends_on)
                node = TaskNode(
                    task_id=t.task_id or uuid.uuid4().hex[:6],
                    agent_type="TOOL_EXEC" if t.tool_name else "SYNTHESIS",
                    query=t.query or original_query,
                    tool_name=t.tool_name,
                    tool_arguments=t.tool_arguments or {},
                    context_from=list(deps),
                    depends_on=deps,
                    priority=t.priority,
                    metadata=metadata or {},
                )
                plan.add_task(node)

            elapsed = int((time.time() - start) * 1000)
            plan.metadata["replan_reasoning"] = parsed.reasoning if parsed else ""
            plan.metadata["replan_elapsed_ms"] = elapsed
            logger.info(
                f"TaskPlanner.replan: {plan.task_count} new tasks, "
                f"layers={plan.execution_layers}, elapsed={elapsed}ms"
            )
            return plan

        except Exception as e:
            logger.warning(f"Replan LLM call failed: {e}")
            return None

    # ----------------------------------------------------------
    # Internal helpers
    # ----------------------------------------------------------

    @staticmethod
    def _format_tools_description(tools_info) -> str:
        if not tools_info:
            return "(no tools available)"
        tools_list = getattr(tools_info, "tools", []) or []
        lines = []
        for tool_data in tools_list:
            if hasattr(tool_data, "model_dump"):
                td = tool_data.model_dump(mode="json")
            elif isinstance(tool_data, dict):
                td = tool_data
            else:
                continue
            name = td.get("name", "")
            desc = td.get("description", "")
            params = td.get("inputSchema", {}).get("properties", {})
            lines.append(f"- **tool_name: {name}**: {desc}  tool_arguments: ```json\n{params}\n```")
        return "---\n" + "\n\n".join(lines) if lines else "(no tools available)" + "\n---"

    def _build_single_tool_plan(
        self, query: str, tool_name: Optional[str], tool_arguments: Dict, metadata: Dict,
    ) -> TaskPlan:
        plan = TaskPlan(root_query=query, metadata=metadata)
        node = TaskNode(
            task_id="main",
            agent_type="TOOL_EXEC" if tool_name else "DIRECT_RESPONSE",
            query=query,
            tool_name=tool_name,
            tool_arguments=tool_arguments,
            metadata=metadata,
        )
        plan.add_task(node)
        return plan

    def _build_single_task_plan(self, query: str, agent_type: str, metadata: Dict) -> TaskPlan:
        plan = TaskPlan(root_query=query, metadata=metadata)
        node = TaskNode(
            task_id="main",
            agent_type=agent_type,
            query=query,
            metadata=metadata,
        )
        plan.add_task(node)
        return plan

    @staticmethod
    def _parse_json(text: str) -> Dict:
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass
        logger.warning(f"Failed to parse planner JSON: {text[:200]}")
        return {}


# ============================================================
# Tool-Aware Runner
# ============================================================

class ToolAwareRunner:
    """
    Executes individual TaskNodes by dispatching to the appropriate backend:
    - tool nodes → direct MCP call via mcp_client
    - synthesis / direct_response nodes → LLM call with context from prior tasks
    """

    _GRACEFUL_FAIL_TOOLS = {"recharge_and_withdraw"}

    def __init__(
        self,
        llm,
        model_name: str,
        plan: TaskPlan,
        extra_body: Optional[Dict] = None,
        context_provider: Optional[Callable[[], Dict[str, Any]]] = None,
        mcp_retries: int = 1,
    ):
        self.llm = llm
        self.model_name = model_name
        self.plan = plan
        self.extra_body = extra_body
        self._context_provider = context_provider or (lambda: {})
        self._mcp_retries = mcp_retries

    async def __call__(self, node: TaskNode) -> str:
        if node.is_tool_node:
            return await self._run_tool(node)
        return await self._run_synthesis(node)

    async def _run_tool(self, node: TaskNode) -> str:
        from mcp.mcp_http_client import mcp_client, CallToolRequestParams, CallToolError
        from agent.tools.primitive import _parse_mcp_result

        arguments = dict(node.tool_arguments)
        ctx = self._context_provider()
        # 强制注入真实 user_id，覆盖 LLM 根据 MCP schema 生成的 mock 值（LLM 无法获取请求层真实用户身份）
        if ctx.get("user_id"):
            arguments["user_id"] = ctx["user_id"]
            arguments["userId"] = ctx["user_id"]

        self._resolve_tool_arguments(node.tool_name, arguments, ctx)
        self._inject_dependency_context(node, arguments)

        logger.info(f"ToolAwareRunner: calling MCP tool '{node.tool_name}' for task {node.task_id}")
        try:
            result = await mcp_client.call_tool(
                CallToolRequestParams(name=node.tool_name, arguments=arguments),
                retries=self._mcp_retries,
            )
            content = _parse_mcp_result(result)
            if not content:
                content = json.dumps(result.model_dump(mode="json"), ensure_ascii=False) if result else ""
            return content
        except CallToolError as e:
            if node.tool_name in self._GRACEFUL_FAIL_TOOLS:
                logger.warning(
                    f"ToolAwareRunner: tool '{node.tool_name}' returned error but is "
                    f"in graceful-fail list, treating as completed with fallback payload"
                )
                return self._build_graceful_fallback(node.tool_name, arguments)
            raise RuntimeError(f"MCP tool '{node.tool_name}' error: {e}") from e

    async def _run_synthesis(self, node: TaskNode) -> str:
        dep_results = self._collect_context(node)
        if not dep_results:
            return ""

        parts = []
        for tid, text in dep_results.items():
            dep_node = self.plan.tasks.get(tid)
            label = dep_node.tool_name or dep_node.query if dep_node else tid
            parts.append(f"## {label}\n{text}")
        context_text = "\n\n---\n\n".join(parts)

        messages = [
            {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Original query: {self.plan.root_query}\n"
                    f"Sub-task instruction: {node.query}\n\n---\n\n"
                    f"Sub-task results:\n\n{context_text}"
                ),
            },
        ]

        response = await self.llm.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=0.3,
            max_tokens=2000,
            timeout=60.0,
            **({"extra_body": self.extra_body} if self.extra_body else {}),
        )
        return response.choices[0].message.content or ""

    @staticmethod
    def _build_graceful_fallback(tool_name: str, arguments: Dict) -> str:
        """Build a minimal valid response for tools that should not hard-fail."""
        if tool_name == "recharge_and_withdraw":
            return json.dumps({
                "tradeType": arguments.get("tradeType", "WITHDRAW"),
                "siteType": arguments.get("siteType", "global"),
                "paymentMethodList": [
                    {"paymentMethodCode": arguments.get("paymentMethodCode", "FAST_SELL")}
                ],
            }, ensure_ascii=False)
        return json.dumps(arguments, ensure_ascii=False)

    @staticmethod
    def _resolve_tool_arguments(tool_name: str, arguments: Dict, ctx: Dict) -> None:
        """Apply tool-specific argument overrides to match what each MCP tool expects."""
        reply_language = ctx.get("reply_language", "English")

        if tool_name and tool_name.lower() == "recharge_and_withdraw":
            from libs.language import ENGLISH_NAME_TO_CODE_LOCAL_MAP
            arguments.pop("detect_language", None)
            arguments["lang"] = ENGLISH_NAME_TO_CODE_LOCAL_MAP.get(reply_language, "en_US")
        elif tool_name and tool_name.lower() == "kb_search":
            from libs.language import KB_SEARCH_ENGLISH_NAME_TO_CODE_MAP
            arguments["target_language"] = KB_SEARCH_ENGLISH_NAME_TO_CODE_MAP.get(
                reply_language, "en"
            )
        elif tool_name and tool_name.lower() == "customer_service_kb_search":
            from libs.language import ENGLISH_NAME_TO_CODE_LOCAL_MAP as _LOCAL_MAP
            arguments["detect_language"] = _LOCAL_MAP.get(reply_language, "en_US")

    def _inject_dependency_context(self, node: TaskNode, arguments: Dict) -> None:
        dep_results = self._collect_context(node)
        if dep_results:
            context_str = "\n---\n".join(
                f"[{tid}]: {text[:2000]}" for tid, text in dep_results.items()
            )
            if "query" in arguments:
                arguments["query"] = f"{arguments['query']}\n\nContext from prior steps:\n{context_str}"
            else:
                arguments["context"] = context_str

    def _collect_context(self, node: TaskNode) -> Dict[str, str]:
        results = {}
        source_ids = node.context_from if node.context_from else list(node.depends_on)
        for tid in source_ids:
            dep = self.plan.tasks.get(tid)
            if dep and dep.status == TaskStatus.COMPLETED and dep.result:
                results[tid] = str(dep.result)
        return results


# ============================================================
# TaskOrchestrator — DAG execution engine
# ============================================================

class TaskOrchestrator:
    """
    Coordinates task planning and execution.

    Wraps TaskPlanner for planning and provides DAG execution
    with parallel sub-task dispatch.
    """

    def __init__(
        self,
        llm,
        model_name: str,
        extra_body: Optional[Dict] = None,
        planner_timeout: float = 15.0,
        synthesis_max_tokens: int = 2000,
        max_replans: int = 2,
    ):
        self.llm = llm
        self.model_name = model_name
        self.extra_body = extra_body
        self.synthesis_max_tokens = synthesis_max_tokens
        self._max_replans = max_replans
        self._tools_info = None
        self._history: Optional[List[Dict]] = None
        self.cache: Dict[str, Any] = {}

        self._planner = TaskPlanner(
            llm=llm,
            model_name=model_name,
            extra_body=extra_body,
            timeout=planner_timeout,
        )

    async def plan(
        self,
        query: str,
        history: Optional[List[Dict]] = None,
        metadata: Optional[Dict] = None,
        force_decompose: bool = False,
        tools_info=None,
        route_result: Optional[Dict] = None,
    ) -> TaskPlan:
        self._tools_info = tools_info
        self._history = history
        return await self._planner.plan(
            query=query,
            route_result=route_result,
            history=history,
            metadata=metadata,
            tools_info=tools_info,
        )

    def create_tool_runner(
        self,
        plan: TaskPlan,
        context_provider: Optional[Callable[[], Dict[str, Any]]] = None,
        mcp_retries: int = 1,
    ) -> ToolAwareRunner:
        return ToolAwareRunner(
            llm=self.llm,
            model_name=self.model_name,
            plan=plan,
            extra_body=self.extra_body,
            context_provider=context_provider,
            mcp_retries=mcp_retries,
        )

    async def execute(self, plan: TaskPlan, agent_runner=None) -> TaskPlan:
        start = time.time()
        replan_count = 0
        logger.info(f"Orchestrator executing plan {plan.plan_id}: {plan.task_count} tasks, layers={plan.execution_layers}")

        while not plan.is_complete:
            ready = plan.get_ready_tasks()
            if not ready:
                failed = plan.get_failed_tasks()
                if not failed:
                    break

                if replan_count < self._max_replans and self._should_replan(plan, failed):
                    replanned = await self._attempt_replan(plan, failed)
                    if replanned:
                        replan_count += 1
                        logger.info(
                            f"Replan #{replan_count} succeeded, "
                            f"plan now has {plan.task_count} tasks"
                        )
                        continue

                self._skip_dependents(plan, failed)
                break

            if len(ready) == 1:
                await self._execute_task(ready[0], plan, agent_runner)
            else:
                await asyncio.gather(
                    *(self._execute_task(t, plan, agent_runner) for t in ready)
                )

        elapsed = int((time.time() - start) * 1000)
        completed = sum(1 for t in plan.tasks.values() if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in plan.tasks.values() if t.status == TaskStatus.FAILED)
        replans = replan_count
        logger.info(
            f"Orchestrator plan {plan.plan_id} done: {completed} completed, "
            f"{failed} failed, {replans} replans, elapsed={elapsed}ms"
        )
        plan.metadata["replan_count"] = replan_count
        return plan

    async def execute_and_synthesize(self, plan: TaskPlan, agent_runner=None) -> str:
        await self.execute(plan, agent_runner)
        return await self._synthesize(plan)

    async def execute_streaming(
        self, plan: TaskPlan, agent_runner=None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        start = time.time()
        replan_count = 0
        yield {"event_type": "plan_start", "plan_id": plan.plan_id, "task_count": plan.task_count, "layers": plan.execution_layers}

        while not plan.is_complete:
            ready = plan.get_ready_tasks()
            if not ready:
                failed = plan.get_failed_tasks()
                if not failed:
                    break

                if replan_count < self._max_replans and self._should_replan(plan, failed):
                    yield {
                        "event_type": "replan_start",
                        "replan_attempt": replan_count + 1,
                        "failed_tasks": [n.task_id for n in failed],
                    }
                    replanned = await self._attempt_replan(plan, failed)
                    if replanned:
                        replan_count += 1
                        added_ids = [
                            tid for tid, n in plan.tasks.items()
                            if n.status == TaskStatus.PENDING
                        ]
                        yield {
                            "event_type": "replan_complete",
                            "replan_attempt": replan_count,
                            "new_tasks": added_ids,
                            "reasoning": plan.metadata.get("replan_reasoning", ""),
                        }
                        continue
                    else:
                        yield {"event_type": "replan_failed", "replan_attempt": replan_count + 1}

                skipped = self._skip_dependents(plan, failed)
                for tid in skipped:
                    yield {"event_type": "task_skipped", "task_id": tid, "reason": "dependency_failed"}
                break

            tasks_and_nodes = []
            for node in ready:
                node.status = TaskStatus.RUNNING
                yield {"event_type": "task_start", "task_id": node.task_id, "agent_type": node.agent_type, "tool_name": node.tool_name, "query": node.query}
                coro = self._run_task(node, agent_runner)
                tasks_and_nodes.append((asyncio.create_task(coro), node))

            pending = {t: n for t, n in tasks_and_nodes}
            while pending:
                done, _ = await asyncio.wait(pending.keys(), return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    node = pending.pop(task)
                    try:
                        task.result()
                    except Exception:
                        logger.debug("Task %s raised during execution (handled via node status)", node.task_id, exc_info=True)
                    if node.status == TaskStatus.COMPLETED:
                        yield {"event_type": "task_complete", "task_id": node.task_id, "agent_type": node.agent_type, "tool_name": node.tool_name, "result_preview": (str(node.result) or "")[:300], "elapsed_ms": node.elapsed_ms}
                    else:
                        yield {"event_type": "task_failed", "task_id": node.task_id, "agent_type": node.agent_type, "tool_name": node.tool_name, "error": node.error, "elapsed_ms": node.elapsed_ms}

        synthesis = await self._synthesize(plan)
        yield {"event_type": "synthesis", "content": synthesis}

        elapsed = int((time.time() - start) * 1000)
        yield {
            "event_type": "plan_complete",
            "plan_id": plan.plan_id,
            "elapsed_ms": elapsed,
            "tasks_completed": sum(1 for t in plan.tasks.values() if t.status == TaskStatus.COMPLETED),
            "tasks_failed": sum(1 for t in plan.tasks.values() if t.status == TaskStatus.FAILED),
            "replan_count": replan_count,
        }
        plan.metadata["replan_count"] = replan_count

    # ----------------------------------------------------------
    # Internal
    # ----------------------------------------------------------

    async def _execute_task(self, node: TaskNode, plan: TaskPlan, agent_runner) -> None:
        node.status = TaskStatus.RUNNING
        await self._run_task(node, agent_runner)

    async def _run_task(self, node: TaskNode, agent_runner) -> None:
        start = time.time()
        try:
            if agent_runner:
                node.result = await agent_runner(node)
            else:
                node.result = ""
            node.status = TaskStatus.COMPLETED
        except Exception as e:
            node.status = TaskStatus.FAILED
            node.error = f"{type(e).__name__}: {str(e)}"
            logger.exception(f"Task {node.task_id} failed: {node.error}")
        finally:
            node.elapsed_ms = int((time.time() - start) * 1000)

    def _skip_dependents(self, plan: TaskPlan, failed_nodes: List[TaskNode]) -> List[str]:
        failed_ids = {n.task_id for n in failed_nodes}
        skipped = []
        changed = True
        while changed:
            changed = False
            for node in plan.tasks.values():
                if node.status != TaskStatus.PENDING:
                    continue
                if node.depends_on & (failed_ids | set(skipped)):
                    node.status = TaskStatus.SKIPPED
                    node.error = "Skipped due to dependency failure"
                    skipped.append(node.task_id)
                    changed = True
        return skipped

    def _should_replan(self, plan: TaskPlan, failed_nodes: List[TaskNode]) -> bool:
        """
        Heuristic: replanning is viable when there is meaningful remaining work
        that could benefit from an alternative approach.
        """
        if self._tools_info is None:
            return False

        has_completed = any(
            n.status == TaskStatus.COMPLETED for n in plan.tasks.values()
        )
        has_pending = any(
            n.status == TaskStatus.PENDING for n in plan.tasks.values()
        )
        all_failed = all(
            n.status in (TaskStatus.FAILED, TaskStatus.SKIPPED)
            for n in plan.tasks.values()
            if n.status != TaskStatus.COMPLETED
        )

        only_tool_failures = all(n.is_tool_node for n in failed_nodes)

        if all_failed and not has_completed:
            return only_tool_failures

        return has_completed or has_pending

    async def _attempt_replan(
        self, plan: TaskPlan, failed_nodes: List[TaskNode],
    ) -> bool:
        """
        Try to replan around failures. Marks failed subtree as SKIPPED,
        asks the planner for a new sub-plan, and merges it into the current plan.

        Returns True if replanning succeeded and new tasks were added.
        """
        failed_ids = {n.task_id for n in failed_nodes}
        completed_ctx = plan.get_completed_context()

        plan.mark_subtree_skipped(failed_ids)

        new_plan = await self._planner.replan(
            original_query=plan.root_query,
            completed_context=completed_ctx,
            failed_nodes=failed_nodes,
            tools_info=self._tools_info,
            history=self._history,
            metadata=plan.metadata,
        )

        if not new_plan or not new_plan.tasks:
            logger.info("Replan produced no tasks, falling back to skip")
            return False

        added = plan.merge_replan(new_plan)
        if not added:
            logger.info("Replan produced tasks but none were mergeable")
            return False

        if new_plan.metadata.get("replan_reasoning"):
            plan.metadata["replan_reasoning"] = new_plan.metadata["replan_reasoning"]

        logger.info(
            f"Replan merged {len(added)} new tasks: {added}, "
            f"reasoning: {new_plan.metadata.get('replan_reasoning', 'N/A')}"
        )
        return True

    async def _synthesize(self, plan: TaskPlan) -> str:
        completed = [n for n in plan.tasks.values() if n.status == TaskStatus.COMPLETED and n.result]
        if not completed:
            return "Unable to produce an answer — all sub-tasks failed."

        if len(completed) == 1:
            return completed[0].result

        parts = []
        for node in completed:
            label = node.tool_name or node.query
            parts.append(f"## {label}\n{node.result}")
        context_text = "\n\n---\n\n".join(parts)

        messages = [
            {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
            {"role": "user", "content": f"Original query: {plan.root_query}\n\n---\n\nSub-task results:\n\n{context_text}"},
        ]

        try:
            response = await self.llm.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=0.3,
                max_tokens=self.synthesis_max_tokens,
                timeout=60.0,
                **({"extra_body": self.extra_body} if self.extra_body else {}),
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.warning(f"Synthesis LLM call failed: {e}, concatenating results")
            return "\n\n".join(str(n.result) for n in completed if n.result)


__all__ = [
    "TaskStatus",
    "TaskNode",
    "TaskPlan",
    "TaskPlanner",
    "TaskOrchestrator",
    "ToolAwareRunner",
]
