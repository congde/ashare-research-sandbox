# -*- coding: utf-8 -*-
"""
MCP Tool Adapter

Bridges the MCP tool system with the agent's ToolRegistry.
Wraps MCP tools (fetched from the MCP HTTP client) into BaseTool instances
that can be registered in the ToolRegistry.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from agent.tools.base import BaseTool, ToolResult
from mcp.mcp_http_client import mcp_client, CallToolRequestParams, CallToolError
from agent.tools.registry import default_registry

logger = logging.getLogger(__name__)


class MCPToolWrapper(BaseTool):
    """
    Wraps a single MCP tool as a BaseTool.
    
    This adapter converts MCP tool definitions into the BaseTool interface,
    allowing MCP tools to be used transparently in the ToolRegistry.
    """

    def __init__(
        self,
        tool_name: str,
        tool_description: str,
        tool_input_schema: Dict[str, Any],
        retries: int = 1,
    ):
        self._name = tool_name
        self._description = tool_description or ""
        self._input_schema = tool_input_schema or {"type": "object", "properties": {}}
        self._retries = retries

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> Dict[str, Any]:
        return self._input_schema

    async def execute(self, **kwargs) -> ToolResult:
        """
        Execute the MCP tool via the MCP HTTP client.
        
        Args:
            **kwargs: Arguments to pass to the MCP tool
            
        Returns:
            ToolResult with the MCP tool's response
        """
        try:
            if default_registry.has_tool(self._name):
                logger.info(f"Tool '{self._name}' found in default_registry, executing directly")
                tool = default_registry.get_tool(self._name)
                if tool:
                    return await tool.execute(**kwargs)
            logger.info(f"Executing MCP tool: {self._name}")
            result = await mcp_client.call_tool(
                CallToolRequestParams(name=self._name, arguments=kwargs),
                retries=self._retries,
            )
            # Parse the result content
            content = self._parse_result(result)
            return ToolResult(
                success=True,
                content=content,
                data=result.model_dump(mode="json") if result else {},
                metadata={"tool_name": self._name},
            )
        except CallToolError as e:
            error_msg = f"MCP tool '{self._name}' call failed: {str(e)}"
            logger.warning(error_msg)
            return ToolResult(success=False, error=error_msg)
        except Exception as e:
            error_msg = f"MCP tool '{self._name}' unexpected error: {type(e).__name__}: {str(e)}"
            logger.exception(error_msg)
            return ToolResult(success=False, error=error_msg)

    def _parse_result(self, result) -> str:
        """Extract text content from MCP CallToolResult."""
        if not result or not result.content:
            return ""
        parts = []
        for item in result.content:
            if hasattr(item, "text") and item.text:
                if isinstance(item.text, str):
                    parts.append(item.text)
                elif isinstance(item.text, dict):
                    parts.append(json.dumps(item.text, ensure_ascii=False))
        return "\n".join(parts) if parts else ""


class MCPToolAdapter:
    """
    Adapter for batch-converting MCP tools into BaseTool instances 
    and registering them in a ToolRegistry.
    
    Usage:
        registry = ToolRegistry()
        tools_info = await mcp_client.get_tools_info()
        MCPToolAdapter.register_all(registry, tools_info)
    """

    @staticmethod
    def from_mcp_tool(tool_data: Dict[str, Any], retries: int = 1) -> MCPToolWrapper:
        """
        Create a MCPToolWrapper from MCP tool data.
        
        Args:
            tool_data: MCP tool dict with 'name', 'description', 'inputSchema'
            retries: Number of retries for tool calls
            
        Returns:
            MCPToolWrapper instance
        """
        return MCPToolWrapper(
            tool_name=tool_data.get("name", ""),
            tool_description=tool_data.get("description", ""),
            tool_input_schema=tool_data.get("inputSchema", {}),
            retries=retries,
        )

    @staticmethod
    def register_all(
        registry: "ToolRegistry",
        tools_info: Any,
        retries: int = 1,
        exclude: Optional[List[str]] = None,
    ) -> int:
        """
        Register all MCP tools from a ToolsInfo object into the registry.
        
        Args:
            registry: Target ToolRegistry
            tools_info: ToolsInfo object from mcp_client.get_tools_info()
            retries: Number of retries for tool calls
            exclude: Tool names to exclude
            
        Returns:
            Number of tools registered
        """
        if not tools_info:
            logger.warning("No tools_info provided, skipping MCP tool registration")
            return 0

        exclude_set = set(exclude) if exclude else set()
        count = 0

        # tools_info.tools is a list of tool dicts or Tool objects
        tools_list = tools_info.tools if hasattr(tools_info, "tools") else []
        for tool_data in tools_list:
            # Handle both dict and Pydantic model
            if hasattr(tool_data, "model_dump"):
                tool_dict = tool_data.model_dump(mode="json") if hasattr(tool_data, "model_dump") else tool_data
            elif isinstance(tool_data, dict):
                tool_dict = tool_data
            else:
                continue

            tool_name = tool_dict.get("name", "")
            if not tool_name or tool_name in exclude_set:
                continue

            wrapper = MCPToolWrapper(
                tool_name=tool_name,
                tool_description=tool_dict.get("description", ""),
                tool_input_schema=tool_dict.get("inputSchema", {}),
                retries=retries,
            )
            registry.register(wrapper)
            count += 1

        logger.info(f"Registered {count} MCP tools into ToolRegistry")
        return count

    @staticmethod
    async def from_mcp_client(
        retries: int = 1,
        available_tools: Optional[List[str]] = None,
    ) -> List[MCPToolWrapper]:
        """
        Fetch tools from MCP client and create MCPToolWrapper instances.
        
        Args:
            retries: Number of retries for tool calls
            available_tools: If specified, only include these tools
            
        Returns:
            List of MCPToolWrapper instances
        """
        tools_info = await mcp_client.get_tools_info()
        if not tools_info:
            return []

        wrappers = []
        for tool_data in tools_info.tools:
            tool_dict = tool_data if isinstance(tool_data, dict) else (
                tool_data.model_dump(mode="json") if hasattr(tool_data, "model_dump") else {}
            )
            tool_name = tool_dict.get("name", "")
            if available_tools and tool_name not in available_tools:
                continue
            wrappers.append(MCPToolWrapper(
                tool_name=tool_name,
                tool_description=tool_dict.get("description", ""),
                tool_input_schema=tool_dict.get("inputSchema", {}),
                retries=retries,
            ))

        return wrappers
