# -*- coding: utf-8 -*-
"""
Primitive Tools for Skill First Architecture

Minimal set of tools for the skill first paradigm:
- mcp_execute: Execute any MCP tool by name
- respond: Direct response without external tools (alias for DirectResponseTool)
"""

import json
import logging
from typing import Any, Callable, Dict, List, Optional

from agent.tools.base import BaseTool, ToolResult
from mcp.mcp_http_client import mcp_client, CallToolRequestParams, CallToolError

logger = logging.getLogger(__name__)


def _parse_mcp_result(result) -> str:
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


class MCPExecuteTool(BaseTool):
    """
    Primitive tool: execute any MCP tool by name.
    
    Reduces token usage by exposing a single unified interface instead of
    individual schemas for each MCP tool.
    """

    def __init__(
        self,
        available_tools: List[str],
        context_provider: Optional[Callable[[], Dict[str, Any]]] = None,
        retries: int = 1,
    ):
        """
        Args:
            available_tools: List of MCP tool names the LLM can call
            context_provider: Optional callback returning {user_id, reply_language}
                             for tool-specific argument injection
            retries: Number of retries for MCP calls
        """
        self._available_tools = available_tools or []
        self._context_provider = context_provider or (lambda: {})
        self._retries = retries

    @property
    def name(self) -> str:
        return "mcp_execute"

    @property
    def description(self) -> str:
        tools_str = ", ".join(self._available_tools[:15])
        if len(self._available_tools) > 15:
            tools_str += f", ... and {len(self._available_tools) - 15} more"
        return (
            "Execute an MCP tool by name. Use this when you need external data "
            f"(search, lookup, etc.). Available tools: {tools_str}. "
            "Pass tool_name and the arguments that tool expects."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        props = {
            "tool_name": {
                "type": "string",
                "description": f"Name of the MCP tool to call. Must be one of: {', '.join(self._available_tools)}",
            },
            "arguments": {
                "type": "object",
                "description": "Arguments for the tool (e.g. {'query': '...'}). Include query, detect_language, etc. as needed.",
            },
        }
        if self._available_tools:
            props["tool_name"]["enum"] = self._available_tools
        return {
            "type": "object",
            "properties": props,
            "required": ["tool_name", "arguments"],
        }

    def _resolve_arguments(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Apply tool-specific argument overrides (kb_search, recharge_and_withdraw, etc.)."""
        ctx = self._context_provider()
        user_id = ctx.get("user_id") or "Unknown"
        reply_language = ctx.get("reply_language", "English")

        args = dict(arguments)
        # 强制注入真实 user_id，覆盖 LLM 根据 MCP schema 生成的 mock 值（LLM 无法获取请求层真实用户身份）
        args["user_id"] = user_id
        args["userId"] = user_id

        if tool_name.lower() == "kb_search":
            from libs.language import KB_SEARCH_ENGLISH_NAME_TO_CODE_MAP
            args["target_language"] = KB_SEARCH_ENGLISH_NAME_TO_CODE_MAP.get(
                reply_language, "en"
            )
        elif tool_name.lower() == "recharge_and_withdraw":
            from libs.language import ENGLISH_NAME_TO_CODE_LOCAL_MAP
            args.pop("detect_language", None)
            args["lang"] = ENGLISH_NAME_TO_CODE_LOCAL_MAP.get(reply_language, "en_US")

        return args

    async def execute(self, tool_name: str, arguments: Dict[str, Any], **kwargs) -> ToolResult:
        """
        Execute the MCP tool.
        
        Args:
            tool_name: Name of the MCP tool
            arguments: Tool arguments (dict)
        """
        if tool_name not in self._available_tools:
            return ToolResult(
                success=False,
                error=f"Unknown tool '{tool_name}'. Available: {', '.join(self._available_tools)}",
                metadata={"actual_tool_name": tool_name},
            )

        resolved = self._resolve_arguments(tool_name, arguments)

        # Local tools registered on default_registry (e.g. valueScan_api, kucoin_openapi_public) run in-process.
        from agent.tools.registry import default_registry

        if default_registry.has_tool(tool_name):
            local_tool = default_registry.get_tool(tool_name)
            if local_tool:
                logger.info(f"Executing local tool via mcp_execute: {tool_name}")
                return await local_tool.execute(**resolved)

        try:
            logger.info(f"Executing MCP tool via mcp_execute: {tool_name}")
            result = await mcp_client.call_tool(
                CallToolRequestParams(name=tool_name, arguments=resolved),
                retries=self._retries,
            )
            content = _parse_mcp_result(result)
            return ToolResult(
                success=True,
                content=content,
                data=result.model_dump(mode="json") if result else {},
                metadata={
                    "actual_tool_name": tool_name,
                    "arguments": resolved,
                },
            )
        except CallToolError as e:
            error_msg = f"MCP tool '{tool_name}' failed: {str(e)}"
            logger.warning(error_msg)
            return ToolResult(
                success=False,
                error=error_msg,
                metadata={"actual_tool_name": tool_name},
            )
        except Exception as e:
            error_msg = f"MCP tool '{tool_name}' error: {type(e).__name__}: {str(e)}"
            logger.exception(error_msg)
            return ToolResult(
                success=False,
                error=error_msg,
                metadata={"actual_tool_name": tool_name},
            )


class RespondTool(BaseTool):
    """
    Primitive tool: respond directly without calling external tools.
    
    Alias for DirectResponseTool with skill-first naming.
    """

    @property
    def name(self) -> str:
        return "respond"

    @property
    def description(self) -> str:
        return (
            "Respond directly to the user when no external tools are needed. "
            "Provide your intended response in suggested_response and detect the query language."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "suggested_response": {
                    "type": "string",
                    "description": (
                        "Your intended response content. Keep it brief (one sentence or key points). "
                        "The system will refine it for the final response."
                    ),
                },
                "detect_language": {
                    "type": "string",
                    "description": (
                        "Detect the writing language of the user's query. "
                        "If the user requests a specific language, use that."
                    ),
                },
            },
            "required": ["suggested_response", "detect_language"],
        }

    async def execute(self, **kwargs) -> ToolResult:
        """Direct response - no external call."""
        return ToolResult(
            success=True,
            content=kwargs.get("suggested_response", ""),
            data=kwargs,
            metadata={"detect_language": kwargs.get("detect_language", "English")},
        )
