# -*- coding: utf-8 -*-
"""
Customer Service MCP Aggregator

场景化聚合入口：
1. 根据 scene 路由到对应 MCP 子工具
2. 根据场景过滤必填参数
3. 统一返回格式，供上层 RAG 使用
"""

import json
import logging
from typing import Dict, List, Tuple

from mcp.mcp_http_client import mcp_client, CallToolRequestParams, McpError

logger = logging.getLogger(__name__)


class CustomerServiceMcpAggregator:
    """聚合客服场景的 MCP 子工具调用。"""

    # 6个MCP全量工具规范（可持续补充必填参数）
    TOOL_SPECS: Dict[str, Dict[str, List[str] | str]] = {
        "p2p-query": {
            "scene": "p2p",
            "required": ["userId", "siteType", "orderId", "currency"],
        },
        "asset-query": {
            "scene": "asset",
            "required": ["userId", "currency"],
        },
        "kyc-kyb-query": {
            "scene": "kyc",
            "required": ["userId"],
        },
        "user-query": {
            "scene": "account",
            "required": ["userId"],
        },
        "deposit-abnormal": {
            "scene": "deposit",
            "required": ["siteType", "txId", "chainId", "currency"],
        },
        "withdrawal-abnormal": {
            "scene": "withdraw",
            "required": ["siteType", "userId"],
        },
    }

    # 场景到当前主路由工具映射（保持单场景单工具行为）
    SCENE_PRIMARY_TOOL: Dict[str, str] = {
        "deposit":  "deposit-abnormal",
        "withdraw": "withdrawal-abnormal",
        "p2p":      "p2p-query",
        "asset":    "asset-query",
        "kyc":      "kyc-kyb-query",
        "account":  "user-query",
    }

    DEFAULT_SCENE = "account"

    def required_slots_for_scene(self, scene: str) -> List[str]:
        tool_name = self.SCENE_PRIMARY_TOOL.get(scene, self.SCENE_PRIMARY_TOOL[self.DEFAULT_SCENE])
        return list(self.TOOL_SPECS[tool_name]["required"])

    async def call_scene_tool(self, scene: str, slots: Dict[str, str]) -> dict:
        tool_name = self.SCENE_PRIMARY_TOOL.get(scene, self.SCENE_PRIMARY_TOOL[self.DEFAULT_SCENE])
        arg_keys = list(self.TOOL_SPECS[tool_name]["required"])
        args = {key: slots.get(key) for key in arg_keys if slots.get(key)}

        # Skip call if tool is not exposed by MCP server (e.g. kyc-kyb-query not deployed)
        tools_info = await mcp_client.get_tools_info()
        if tools_info and tool_name not in (tools_info.tools_name or []):
            logger.warning(
                "[CustomerServiceMcpAggregator] tool not available on MCP server, scene=%s, tool=%s",
                scene, tool_name
            )
            return {
                "scene": scene,
                "tool": tool_name,
                "arguments": args,
                "error": "tool not available",
                "data": {},
            }

        try:
            result = await mcp_client.call_tool(CallToolRequestParams(name=tool_name, arguments=args))
            if result and getattr(result, "content", None):
                first = result.content[0]
                text = first.text if hasattr(first, "text") else str(first)
                try:
                    parsed = json.loads(text)
                except Exception:
                    parsed = text

                # 剥离上游统一包装层（success/code/msg/retry），只透传业务 data
                if isinstance(parsed, dict) and "data" in parsed:
                    success = parsed.get("success", True)
                    if not success:
                        error_msg = parsed.get("msg") or parsed.get("message") or "upstream error"
                        return {
                            "scene": scene,
                            "tool": tool_name,
                            "arguments": args,
                            "error": error_msg,
                            "data": {},
                        }
                    data = self._clean_data(parsed["data"])
                else:
                    data = parsed

                return {
                    "scene": scene,
                    "tool": tool_name,
                    "arguments": args,
                    "data": data,
                }

            return {
                "scene": scene,
                "tool": tool_name,
                "arguments": args,
                "data": {},
            }
        except McpError as e:
            err_msg = str(e)
            if "tool not found" in err_msg.lower():
                logger.warning(
                    "[CustomerServiceMcpAggregator] MCP tool not found, scene=%s, tool=%s",
                    scene, tool_name
                )
            else:
                logger.exception(
                    "[CustomerServiceMcpAggregator] MCP call failed, scene=%s, args=%s, err=%s",
                    scene, args, e
                )
            return {
                "scene": scene,
                "tool": tool_name,
                "arguments": args,
                "error": err_msg,
                "data": {},
            }
        except Exception as e:
            logger.exception(f"[CustomerServiceMcpAggregator] call failed, scene={scene}, args={args}, err={e}")
            return {
                "scene": scene,
                "tool": tool_name,
                "arguments": args,
                "error": str(e),
                "data": {},
            }

    @staticmethod
    def _clean_data(data) -> dict:
        """递归过滤 null/None 字段，减少传入 LLM 的无效信息"""
        if isinstance(data, dict):
            return {
                k: CustomerServiceMcpAggregator._clean_data(v)
                for k, v in data.items()
                if v is not None
            }
        if isinstance(data, list):
            return [CustomerServiceMcpAggregator._clean_data(i) for i in data if i is not None]
        return data
