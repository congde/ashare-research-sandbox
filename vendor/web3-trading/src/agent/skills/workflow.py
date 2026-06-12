# -*- coding: utf-8 -*-
"""
Generalized Workflow Engine

Provides base classes and utilities for creating LangGraph-based workflows.
Generalizes the CurrencyInsight workflow pattern so new business workflows
can be created by composing reusable nodes.

Key components:
- BaseWorkflowState: Common state fields for all workflows
- Reusable node functions: plan, execute_tools, synthesize, callback
- WorkflowBuilder: Factory for creating common workflow patterns
- WorkflowRunner: Utility for executing workflows with error handling

Usage:
    # Define a custom workflow
    class MyWorkflowState(BaseWorkflowState):
        custom_field: str = ""
    
    # Create using the builder
    builder = WorkflowBuilder(MyWorkflowState)
    builder.add_plan_node(my_planner)
    builder.add_tool_execution_node()
    builder.add_synthesis_node(my_synthesizer)
    builder.add_callback_node()
    workflow = builder.build()
    
    # Or use pre-built patterns
    workflow = create_plan_execute_synthesize_workflow(
        state_class=MyWorkflowState,
        planner=my_planner,
        synthesizer=my_synthesizer,
    )
"""

import asyncio
import logging
import time
import uuid
from typing import (
    Any, Callable, Coroutine, Dict, List, Literal, 
    Optional, Type, TypedDict, TypeVar, Union,
)

from langgraph.graph import StateGraph, END

from agent.skills.base import BaseSkill
from agent.skills.tool_call import MCPToolCallSkill
from agent.skills.callback import CallbackSkill
from agent.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=TypedDict)


# ============================================================
# Base Workflow State
# ============================================================

class BaseWorkflowState(TypedDict, total=False):
    """
    Common state fields shared across all workflows.
    
    Workflows extend this with domain-specific fields.
    All fields are optional (total=False) to allow partial initialization.
    """
    # Input
    user_id: str
    source: str
    callback_url: str
    extra: dict

    # Agent decisions
    tool_calls: List[dict]
    
    # Tool execution results
    tool_results: List[dict]
    
    # LLM messages for multi-turn context
    messages: List[dict]
    
    # Output
    output_data: Optional[dict]
    
    # Status tracking
    status: str           # "Ok", "Failed", "Pending"
    reason: str           # Error reason if failed
    error: Optional[str]  # Exception message
    
    # Workflow metadata
    workflow_id: str
    started_at: float
    completed_at: Optional[float]


# ============================================================
# Reusable Node Functions
# ============================================================

class ToolExecutionNode:
    """
    Reusable LangGraph node that executes tool calls from state.
    
    Reads tool_calls from state, executes them (in parallel by default),
    and stores results in tool_results.
    
    Delegates to MCPToolCallSkill, which internally uses ToolRegistry
    as the single source of truth for tool execution logic.
    
    Supports two modes:
    1. 传入 ToolRegistry（推荐）: 复用已加载的工具，避免重复初始化
    2. 自动模式: skill 内部按需从 MCP 获取工具
    """

    def __init__(
        self,
        registry: Optional[ToolRegistry] = None,
        skill: Optional[MCPToolCallSkill] = None,
    ):
        """
        Args:
            registry: Pre-built ToolRegistry to reuse. Takes priority over skill.
            skill: MCPToolCallSkill instance. If neither registry nor skill
                   is provided, a default skill is created.
        """
        if registry is not None:
            self.skill = MCPToolCallSkill(registry=registry)
        elif skill is not None:
            self.skill = skill
        else:
            self.skill = MCPToolCallSkill()

    async def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute tools and update state."""
        return await self.skill.execute(state)


class CallbackNode:
    """
    Reusable node that sends results to a callback URL.
    
    Uses the existing CallbackSkill for HTTP callback.
    """

    def __init__(self, skill: Optional[CallbackSkill] = None):
        self.skill = skill or CallbackSkill()

    async def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute callback and update state."""
        await self.skill.execute(state)
        return state


# Type aliases for node functions
NodeFunc = Callable[[Dict[str, Any]], Coroutine[Any, Any, Dict[str, Any]]]
ConditionalFunc = Callable[[Dict[str, Any]], str]


# ============================================================
# Workflow Builder
# ============================================================

class WorkflowBuilder:
    """
    Builder for creating LangGraph workflows.
    
    Provides a fluent API for composing workflow nodes and edges.
    Handles common patterns like plan -> execute -> synthesize -> callback.
    
    Usage:
        builder = WorkflowBuilder(MyState)
        builder.add_node("plan", plan_func)
        builder.add_node("execute", execute_func)
        builder.add_edge("plan", "execute")
        builder.set_entry("plan")
        builder.set_finish("execute")
        workflow = builder.build()
    """

    def __init__(self, state_class: Type = None):
        """
        Initialize the workflow builder.
        
        Args:
            state_class: TypedDict class for the workflow state.
                         Defaults to BaseWorkflowState.
        """
        self._state_class = state_class or BaseWorkflowState
        self._nodes: Dict[str, NodeFunc] = {}
        self._edges: List[tuple] = []
        self._conditional_edges: List[tuple] = []
        self._entry_point: Optional[str] = None
        self._finish_nodes: List[str] = []

    def add_node(self, name: str, func: NodeFunc) -> "WorkflowBuilder":
        """Add a node to the workflow."""
        self._nodes[name] = func
        return self

    def add_edge(self, from_node: str, to_node: str) -> "WorkflowBuilder":
        """Add a direct edge between nodes."""
        self._edges.append((from_node, to_node))
        return self

    def add_conditional_edge(
        self, 
        from_node: str, 
        condition: ConditionalFunc,
        path_map: Dict[str, str],
    ) -> "WorkflowBuilder":
        """
        Add a conditional edge that routes based on state.
        
        Args:
            from_node: Source node name
            condition: Function that takes state and returns a key
            path_map: Mapping from condition return values to target node names
        """
        self._conditional_edges.append((from_node, condition, path_map))
        return self

    def set_entry(self, node_name: str) -> "WorkflowBuilder":
        """Set the entry point node."""
        self._entry_point = node_name
        return self

    def set_finish(self, *node_names: str) -> "WorkflowBuilder":
        """Set nodes that lead to END."""
        self._finish_nodes.extend(node_names)
        return self

    # --- Convenience methods for common node types ---

    def add_plan_node(self, planner: NodeFunc, name: str = "plan") -> "WorkflowBuilder":
        """Add a planning node."""
        return self.add_node(name, planner)

    def add_tool_execution_node(self, name: str = "execute_tools") -> "WorkflowBuilder":
        """Add the standard tool execution node."""
        node = ToolExecutionNode()
        return self.add_node(name, node)

    def add_synthesis_node(self, synthesizer: NodeFunc, name: str = "synthesize") -> "WorkflowBuilder":
        """Add a synthesis/aggregation node."""
        return self.add_node(name, synthesizer)

    def add_callback_node(self, name: str = "callback") -> "WorkflowBuilder":
        """Add the standard callback node."""
        node = CallbackNode()
        return self.add_node(name, node)

    def build(self) -> Any:
        """
        Build and compile the LangGraph workflow.
        
        Returns:
            Compiled LangGraph workflow ready for execution
        """
        if not self._entry_point:
            raise ValueError("Entry point must be set before building")

        graph = StateGraph(self._state_class)

        # Add nodes
        for name, func in self._nodes.items():
            graph.add_node(name, func)

        # Set entry point
        graph.set_entry_point(self._entry_point)

        # Add edges
        for from_node, to_node in self._edges:
            graph.add_edge(from_node, to_node)

        # Add conditional edges
        for from_node, condition, path_map in self._conditional_edges:
            graph.add_conditional_edges(from_node, condition, path_map)

        # Add finish edges
        for node_name in self._finish_nodes:
            graph.add_edge(node_name, END)

        return graph.compile()


# ============================================================
# Pre-built Workflow Patterns
# ============================================================

def create_plan_execute_synthesize_workflow(
    state_class: Type = None,
    planner: NodeFunc = None,
    synthesizer: NodeFunc = None,
    with_callback: bool = True,
) -> Any:
    """
    Create a standard plan -> execute_tools -> synthesize -> callback workflow.
    
    This is the most common pattern, used by CurrencyInsight and similar workflows.
    
    Args:
        state_class: TypedDict class for workflow state
        planner: Async function for the planning node
        synthesizer: Async function for the synthesis node
        with_callback: Whether to include a callback node
        
    Returns:
        Compiled LangGraph workflow
    """
    if not planner or not synthesizer:
        raise ValueError("Both planner and synthesizer functions are required")

    builder = WorkflowBuilder(state_class or BaseWorkflowState)
    builder.add_plan_node(planner)
    builder.add_tool_execution_node()
    builder.add_synthesis_node(synthesizer)
    builder.set_entry("plan")
    builder.add_edge("plan", "execute_tools")
    builder.add_edge("execute_tools", "synthesize")

    if with_callback:
        builder.add_callback_node()
        builder.add_edge("synthesize", "callback")
        builder.set_finish("callback")
    else:
        builder.set_finish("synthesize")

    return builder.build()


def create_conditional_workflow(
    state_class: Type = None,
    planner: NodeFunc = None,
    condition: ConditionalFunc = None,
    branches: Dict[str, NodeFunc] = None,
    synthesizer: NodeFunc = None,
    with_callback: bool = True,
) -> Any:
    """
    Create a workflow with conditional branching after planning.
    
    Pattern: plan -> [condition] -> branch_a or branch_b -> synthesize -> callback
    
    Useful for workflows that need different processing based on the plan result.
    
    Args:
        state_class: TypedDict class for workflow state
        planner: Planning node function
        condition: Function that determines which branch to take
        branches: Mapping of branch names to their node functions
        synthesizer: Synthesis node function
        with_callback: Whether to include callback
        
    Returns:
        Compiled LangGraph workflow
    """
    if not planner or not condition or not branches or not synthesizer:
        raise ValueError("planner, condition, branches, and synthesizer are all required")

    builder = WorkflowBuilder(state_class or BaseWorkflowState)
    builder.add_plan_node(planner)
    builder.set_entry("plan")

    # Add branch nodes and edges to synthesize
    path_map = {}
    for branch_name, branch_func in branches.items():
        builder.add_node(branch_name, branch_func)
        builder.add_edge(branch_name, "synthesize")
        path_map[branch_name] = branch_name

    builder.add_conditional_edge("plan", condition, path_map)
    builder.add_synthesis_node(synthesizer)

    if with_callback:
        builder.add_callback_node()
        builder.add_edge("synthesize", "callback")
        builder.set_finish("callback")
    else:
        builder.set_finish("synthesize")

    return builder.build()


# ============================================================
# Workflow Runner
# ============================================================

class WorkflowRunner:
    """
    Utility for executing workflows with consistent error handling,
    logging, and state initialization.
    
    Usage:
        runner = WorkflowRunner(workflow)
        result = await runner.run({
            "user_id": "123",
            "symbol": "BTC",
            ...
        })
    """

    def __init__(self, workflow: Any, workflow_name: str = "workflow"):
        """
        Args:
            workflow: Compiled LangGraph workflow
            workflow_name: Name for logging purposes
        """
        self.workflow = workflow
        self.workflow_name = workflow_name

    async def run(self, initial_state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the workflow with error handling.
        
        Ensures common state fields are initialized and provides
        consistent error handling/logging.
        
        Args:
            initial_state: Initial workflow state
            
        Returns:
            Final workflow state
        """
        # Initialize common fields
        state = {
            "workflow_id": uuid.uuid4().hex[:16],
            "started_at": time.time(),
            "status": "Ok",
            "reason": "",
            "error": None,
            "tool_calls": [],
            "tool_results": [],
            "messages": [],
            **initial_state,
        }

        logger.info(
            f"Starting workflow '{self.workflow_name}' "
            f"(id={state['workflow_id']})"
        )
        start_time = time.time()

        try:
            result = await self.workflow.ainvoke(state)
            elapsed_ms = int((time.time() - start_time) * 1000)
            result["completed_at"] = time.time()

            logger.info(
                f"Workflow '{self.workflow_name}' completed in {elapsed_ms}ms, "
                f"status={result.get('status', 'unknown')}"
            )
            return result

        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            error_msg = f"{type(e).__name__}: {str(e)}"
            
            logger.exception(
                f"Workflow '{self.workflow_name}' failed after {elapsed_ms}ms: {error_msg}"
            )

            return {
                **state,
                "status": "Failed",
                "reason": error_msg,
                "error": error_msg,
                "completed_at": time.time(),
            }

    async def run_in_background(
        self, 
        initial_state: Dict[str, Any],
        callback: Optional[Callable] = None,
    ) -> asyncio.Task:
        """
        Execute the workflow as a background task.
        
        Args:
            initial_state: Initial workflow state
            callback: Optional callback when workflow completes
            
        Returns:
            asyncio.Task that can be awaited or cancelled
        """
        async def _run():
            result = await self.run(initial_state)
            if callback:
                await callback(result)
            return result

        task = asyncio.create_task(_run())
        logger.info(f"Workflow '{self.workflow_name}' started in background")
        return task


__all__ = [
    "BaseWorkflowState",
    "ToolExecutionNode",
    "CallbackNode",
    "WorkflowBuilder",
    "WorkflowRunner",
    "create_plan_execute_synthesize_workflow",
    "create_conditional_workflow",
]
