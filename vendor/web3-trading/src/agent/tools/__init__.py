# -*- coding: utf-8 -*-
"""
Agent Tools Package

Provides a unified tool system that wraps MCP tools and local tools
into a common interface for the ReAct agent loop.

Key components:
- BaseTool: Abstract base class for all tools
- ToolRegistry: Registry for tool registration, lookup, and execution
- MCPToolAdapter: Adapter that wraps MCP tools into BaseTool interface
"""

from agent.tools.base import BaseTool, ToolResult, DirectResponseTool
from agent.tools.registry import ToolRegistry
from agent.tools.mcp_adapter import MCPToolAdapter
from agent.tools.primitive import MCPExecuteTool, RespondTool
from agent.tools.loop import AgentLoop, LoopEvent, LoopEventType
from agent.tools.subagent import SubagentManager, SubagentResult

__all__ = [
    "BaseTool",
    "ToolResult",
    "ToolRegistry",
    "MCPToolAdapter",
    "DirectResponseTool",
    "MCPExecuteTool",
    "RespondTool",
    "AgentLoop",
    "LoopEvent",
    "LoopEventType",
    "SubagentManager",
    "SubagentResult",
]
