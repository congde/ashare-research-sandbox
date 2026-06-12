# -*- coding: utf-8 -*-
"""
Tool Registry

Central registry for managing tools available to the agent.
Inspired by nanobot's ToolRegistry pattern.

The registry provides:
- Tool registration and lookup by name
- OpenAI function-calling schema generation
- Safe tool execution (never raises, returns error strings)
- Tool filtering for different agent contexts (main agent vs subagent)
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional, Set

from agent.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    Central registry for agent tools.
    
    Manages the lifecycle of tools: registration, lookup, schema generation,
    and execution. Designed to be shared across agent iterations within
    a single request, or scoped per subagent.
    
    Usage:
        registry = ToolRegistry()
        registry.register(MyTool())
        
        # Get OpenAI function schemas for LLM
        schemas = registry.get_definitions()
        
        # Execute a tool by name
        result = await registry.execute("my_tool", {"arg": "value"})
    """

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """
        Register a tool in the registry.
        
        Args:
            tool: Tool instance to register
            
        Raises:
            ValueError: If a tool with the same name is already registered
        """
        if tool.name in self._tools:
            logger.warning(f"Tool '{tool.name}' already registered, overwriting")
        self._tools[tool.name] = tool
        logger.debug(f"Registered tool: {tool.name}")

    def register_many(self, tools: List[BaseTool]) -> None:
        """Register multiple tools at once."""
        for tool in tools:
            self.register(tool)

    def unregister(self, name: str) -> None:
        """Remove a tool from the registry."""
        if name in self._tools:
            del self._tools[name]
            logger.debug(f"Unregistered tool: {name}")

    def get_tool(self, name: str) -> Optional[BaseTool]:
        """Get a tool by name."""
        return self._tools.get(name)

    def has_tool(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    @property
    def tool_names(self) -> List[str]:
        """Get all registered tool names."""
        return list(self._tools.keys())

    @property
    def tool_count(self) -> int:
        """Get the number of registered tools."""
        return len(self._tools)

    def get_definitions(self, exclude: Optional[Set[str]] = None) -> List[Dict[str, Any]]:
        """
        Get OpenAI function-calling schemas for all registered tools.
        
        Args:
            exclude: Optional set of tool names to exclude
            
        Returns:
            List of OpenAI tool schemas suitable for the `tools` parameter
        """
        definitions = []
        for name, tool in self._tools.items():
            if exclude and name in exclude:
                continue
            definitions.append(tool.to_openai_schema())
        return definitions

    async def execute(self, name: str, arguments: Dict[str, Any]) -> ToolResult:
        """
        Execute a tool by name with given arguments.
        
        This method NEVER raises exceptions. Errors are captured in the
        returned ToolResult. This is critical for the ReAct loop to remain
        stable across iterations.
        
        Args:
            name: Name of the tool to execute
            arguments: Arguments to pass to the tool
            
        Returns:
            ToolResult with execution outcome
        """
        tool = self._tools.get(name)
        if not tool:
            error_msg = f"Tool '{name}' not found. Available tools: {self.tool_names}"
            logger.error(error_msg)
            return ToolResult(success=False, error=error_msg)

        # Validate parameters
        errors = tool.validate_params(arguments)
        if errors:
            error_msg = f"Parameter validation failed for tool '{name}': {'; '.join(errors)}"
            logger.warning(error_msg)
            # Still try to execute - some tools may handle missing params gracefully

        start_time = time.time()
        try:
            result = await tool.execute(**arguments)
            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.info(f"Tool '{name}' executed in {elapsed_ms}ms, success={result.success}")
            return result
        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            error_msg = f"Tool '{name}' execution failed after {elapsed_ms}ms: {type(e).__name__}: {str(e)}"
            logger.exception(error_msg)
            return ToolResult(success=False, error=error_msg)

    def create_subset(self, include: Optional[Set[str]] = None, exclude: Optional[Set[str]] = None) -> "ToolRegistry":
        """
        Create a new registry with a subset of tools.
        
        Useful for creating scoped registries for subagents with
        limited tool access.
        
        Args:
            include: If provided, only include these tools
            exclude: If provided, exclude these tools
            
        Returns:
            New ToolRegistry with filtered tools
        """
        subset = ToolRegistry()
        for name, tool in self._tools.items():
            if include is not None and name not in include:
                continue
            if exclude is not None and name in exclude:
                continue
            subset._tools[name] = tool
        return subset

    def __repr__(self) -> str:
        return f"<ToolRegistry(tools={self.tool_names})>"

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools


default_registry = ToolRegistry()
from agent.tools.customer_service_kb import CustomerServiceKBTool
from agent.tools.kucoin_openapi_public import KucoinOpenApiPublicTool
from agent.tools.valuescan_open_api import ValueScanOpenAPITool
from agent.tools.trading_decision import TradingDecisionTool
from agent.tools.dexscan_open_api import DexScanOpenAPITool

default_registry.register(CustomerServiceKBTool())
default_registry.register(KucoinOpenApiPublicTool())
default_registry.register(ValueScanOpenAPITool())
default_registry.register(TradingDecisionTool())
default_registry.register(DexScanOpenAPITool())
