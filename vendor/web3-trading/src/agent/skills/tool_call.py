# -*- coding: utf-8 -*-
"""
MCP Tool Call Skill

LangGraph 工作流节点：从 state 读取 tool_calls，委托 ToolRegistry 执行。

本模块是 Skill 层（面向 LangGraph 工作流）与 Tool 层（底层执行引擎）之间
的适配器。MCP 调用的实际逻辑统一在 agent.tools 中，本模块只负责：
1. 从 state dict 读取 tool_calls
2. 委托 ToolRegistry 执行
3. 将 ToolResult 写回 state dict
"""

import logging
import asyncio
from typing import Any, Dict, List, Optional

from agent.skills.base import BaseSkill
from agent.tools.registry import ToolRegistry
from agent.tools.mcp_adapter import MCPToolAdapter, MCPToolWrapper

logger = logging.getLogger(__name__)


class MCPToolCallSkill(BaseSkill):
    """
    MCP 工具调用技能 — LangGraph 节点适配器
    
    从 state["tool_calls"] 读取要调用的工具列表，
    通过 ToolRegistry 统一执行，结果写入 state["tool_results"]。

    支持两种模式：
    1. 预注册模式：传入已有的 ToolRegistry（推荐，复用已加载的工具）
    2. 自动模式：不传 registry，skill 内部按需创建临时 registry
    """
    name = "mcp_tool_call"
    description = "Call MCP tools via ToolRegistry and process results"

    def __init__(self, registry: Optional[ToolRegistry] = None, retries: int = 2):
        """
        Args:
            registry: 预注册的 ToolRegistry。若为 None 则每次执行时临时创建。
            retries: MCP 工具调用重试次数（仅在自动模式下生效）
        """
        self._registry = registry
        self._retries = retries

    async def _get_registry(self, tool_names: List[str]) -> ToolRegistry:
        """
        获取 ToolRegistry 实例。

        如果构造时传入了 registry 则直接使用；
        否则按 tool_names 按需创建临时 registry。
        """
        if self._registry is not None:
            return self._registry

        # 自动模式：从 MCP 获取工具并注册
        registry = ToolRegistry()
        wrappers = await MCPToolAdapter.from_mcp_client(
            retries=self._retries,
            available_tools=tool_names if tool_names else None,
        )
        registry.register_many(wrappers)
        return registry

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行工具调用并更新 state。

        读取 state["tool_calls"]，并发执行，结果写入
        state["tool_results"] 和 state["messages"]。
        """
        tool_calls = state.get("tool_calls", [])
        state.setdefault("tool_results", [])
        state.setdefault("messages", [])

        if not tool_calls:
            return state

        # 收集要调用的工具名
        tool_names = [tc.get("name") for tc in tool_calls if tc.get("name")]
        registry = await self._get_registry(tool_names)

        # 并发执行所有工具调用
        tasks = [
            self._call_tool(
                registry=registry,
                tool_name=tc.get("name", ""),
                arguments=tc.get("arguments", {}),
                tool_call_id=tc.get("tool_call_id", ""),
            )
            for tc in tool_calls
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理结果写入 state
        for i, result in enumerate(results):
            tc = tool_calls[i]
            tool_name = tc.get("name", "")
            tool_call_id = tc.get("tool_call_id", "")

            if isinstance(result, Exception):
                logger.exception(f"Tool call failed with exception: {result}")
                content = str(result)
                state["tool_results"].append({
                    "tool": tool_name,
                    "success": False,
                    "data": content,
                })
            else:
                content = result.get("data", "")
                state["tool_results"].append(result)

            # 追加 tool message 供后续 LLM 使用
            state["messages"].append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": content if isinstance(content, str) else str(content),
            })

        return state

    @staticmethod
    async def _call_tool(
        registry: ToolRegistry,
        tool_name: str,
        arguments: Dict[str, Any],
        tool_call_id: str,
    ) -> Dict[str, Any]:
        """
        通过 ToolRegistry 调用单个工具。

        Returns:
            统一结构: {"tool": name, "success": bool, "data": str}
        """
        logger.info(f"Executing tool via ToolRegistry: {tool_name}")
        result = await registry.execute(tool_name, arguments)
        return {
            "tool": tool_name,
            "success": result.success,
            "data": result.content if result.success else (result.error or ""),
        }


class ToolCallSkill(BaseSkill):
    name = "mcp_tool_call"
    description = "Call MCP tools via ToolRegistry and process results"

    def __init__(self, registry: Optional[ToolRegistry] = None, retries: int = 2):
        """
        Args:
            registry: 预注册的 ToolRegistry。若为 None 则每次执行时临时创建。
            retries: MCP 工具调用重试次数（仅在自动模式下生效）
        """
        self._registry = registry
        self._retries = retries

    async def _get_registry(self, tool_names: List[str]) -> ToolRegistry:
        """
        获取 ToolRegistry 实例。

        如果构造时传入了 registry 则直接使用；
        否则按 tool_names 按需创建临时 registry。
        """
        if self._registry is not None:
            return self._registry

        registry = ToolRegistry()
        wrappers = await MCPToolAdapter.from_mcp_client(
            retries=self._retries,
            available_tools=tool_names if tool_names else None,
        )
        registry.register_many(wrappers)
        return registry

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行工具调用并更新 state。
        """
        tools = state.get("tools") or []

        if not tools:
            return state

        tool_names = [tc.name for tc in tools if tc.name]
        registry = await self._get_registry(tool_names)
        tasks = [
            self._call_tool(
                registry=registry,
                tool_name=tc.name,
                arguments=tc.parameters,
                tool=tc
            )
            for tc in tools
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

        for tool in tools:
            state["messages"].append({
                "role": "tool",
                "tool_call_id": tool.tool_call_id,
                "name": tool.name,
                "content": tool.result
            })

        return state

    @staticmethod
    async def _call_tool(
        registry: ToolRegistry,
        tool_name: str,
        arguments: Dict[str, Any],
        tool
    ) -> Dict[str, Any]:
        logger.info(f"Executing tool via ToolRegistry: {tool_name}")
        result = await registry.execute(tool_name, arguments)
        tool.status = result.success
        tool.result = result.content if result.success else (result.error or "")
        return tool
