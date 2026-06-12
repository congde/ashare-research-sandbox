# -*- coding: utf-8 -*-
"""
Tool Policy — per-agent-type tool access control.

Determines which tools each AgentType is allowed to use and builds
a scoped ToolRegistry accordingly. This is the security / filtering
layer between the MCP tool catalogue and the Agent.
"""

import logging
from typing import Any, Callable, Dict, List, Optional, Set

from agent.tools.registry import ToolRegistry
from agent.tools.mcp_adapter import MCPToolAdapter
from agent.tools.base import DirectResponseTool
from agent.tools.primitive import MCPExecuteTool, RespondTool
from agent.tools.valuescan_open_api import ValueScanOpenAPITool
from agent.tools.kucoin_openapi_public import KucoinOpenApiPublicTool
from agent.tools.trading_decision import TradingDecisionTool
from agent.tools.dexscan_open_api import DexScanOpenAPITool

logger = logging.getLogger(__name__)

# Tool names implemented locally (not required to exist on MCP)
_LOCAL_TOOL_NAMES = ("valueScan_api", "kucoin_openapi_public", "trading_decision", "dexScan_api")


def get_allowed_tool_set() -> Optional[Set[str]]:
    """Return None if unrestricted; otherwise allowed MCP/local tool names from config."""
    from web.config import config as _cfg

    if _cfg is None:
        return None
    raw = getattr(_cfg, "agent_allowed_tools", None)
    if not raw:
        return None
    return set(raw)


def _merge_mcp_tool_names(mcp_names: list, allowed: Optional[Set[str]] = None) -> list:
    out = list(mcp_names or [])
    if allowed is not None:
        out = [n for n in out if n in allowed]
    for t in _LOCAL_TOOL_NAMES:
        if allowed is None or t in allowed:
            if t not in out:
                out.append(t)
    return out


class ToolPolicy:
    """
    Determines which tools each agent type can use and builds scoped registries.

    Supports three modes per agent type:
    - "primitive": only MCPExecuteTool (unified dispatcher) + RespondTool
    - "full": all MCP tools registered individually + DirectResponseTool
    - "scoped": only specific MCP tools listed in `allow`
    """

    AGENT_TOOL_CONFIG: Dict[str, Dict[str, Any]] = {
        "QUICK_REASONING": {"mode": "primitive"},
        "DEEP_THINK": {"mode": "full"},
        "DEEP_RESEARCH": {"mode": "full"},
        "AUTO": {"mode": "full"},
        "EVENT_DELIVERY": {"mode": "primitive"},
        "currency_insights": {
            "mode": "scoped",
            "allow": ["get_crypto_investment_outlook", "get_crypto_market_data"],
        },
    }

    DEFAULT_CONFIG: Dict[str, Any] = {"mode": "primitive"}

    def __init__(self, config_overrides: Optional[Dict[str, Dict[str, Any]]] = None):
        """
        Args:
            config_overrides: Optional overrides merged on top of AGENT_TOOL_CONFIG.
        """
        self._config = dict(self.AGENT_TOOL_CONFIG)
        if config_overrides:
            self._config.update(config_overrides)

    def get_config(self, agent_type: str) -> Dict[str, Any]:
        return self._config.get(agent_type, self.DEFAULT_CONFIG)

    def build_registry(
        self,
        agent_type: str,
        tools_info: Any = None,
        context_provider: Optional[Callable[[], Dict[str, Any]]] = None,
    ) -> ToolRegistry:
        """
        Build a ToolRegistry scoped to the agent type's allowed tools.

        Args:
            agent_type: The AgentType string (e.g. "QUICK_REASONING", "DEEP_THINK").
            tools_info: ToolsInfo from mcp_client.get_tools_info(). Required for
                        "full" and "scoped" modes; for "primitive" mode only the
                        tools_name list is needed.
            context_provider: Callback returning runtime context (user_id, reply_language)
                              for primitive tool argument injection.

        Returns:
            A configured ToolRegistry instance.
        """
        cfg = self.get_config(agent_type)
        mode = cfg.get("mode", "primitive")

        registry = ToolRegistry()

        allowed = get_allowed_tool_set()

        if mode == "primitive":
            names = self._extract_tool_names(tools_info)
            if allowed is not None:
                names = [n for n in names if n in allowed]
            available_tools = _merge_mcp_tool_names(names, allowed)
            registry.register(MCPExecuteTool(
                available_tools=available_tools,
                context_provider=context_provider,
                retries=1,
            ))
            registry.register(RespondTool())

        elif mode == "full":
            if tools_info:
                if allowed is None:
                    MCPToolAdapter.register_all(registry, tools_info, retries=1)
                else:
                    exclude = [
                        name for name in self._extract_tool_names(tools_info)
                        if name not in allowed
                    ]
                    MCPToolAdapter.register_all(registry, tools_info, retries=1, exclude=exclude)
            if allowed is None or "valueScan_api" in allowed:
                registry.register(ValueScanOpenAPITool())
            if allowed is None or "dexScan_api" in allowed:
                registry.register(DexScanOpenAPITool())
            if allowed is None or "kucoin_openapi_public" in allowed:
                registry.register(KucoinOpenApiPublicTool())
            if allowed is None or "trading_decision" in allowed:
                registry.register(TradingDecisionTool())
            registry.register(DirectResponseTool())

        elif mode == "scoped":
            allow_list: List[str] = list(cfg.get("allow", []))
            if allowed is not None:
                allow_list = [n for n in allow_list if n in allowed]
            if tools_info:
                MCPToolAdapter.register_all(
                    registry, tools_info, retries=1,
                    exclude=[
                        name for name in self._extract_tool_names(tools_info)
                        if name not in allow_list
                    ],
                )
            if "valueScan_api" in allow_list:
                registry.register(ValueScanOpenAPITool())
            if "dexScan_api" in allow_list:
                registry.register(DexScanOpenAPITool())
            if "kucoin_openapi_public" in allow_list:
                registry.register(KucoinOpenApiPublicTool())
            if "trading_decision" in allow_list:
                registry.register(TradingDecisionTool())
            registry.register(DirectResponseTool())

        else:
            logger.warning(f"Unknown tool policy mode '{mode}' for {agent_type}, falling back to primitive")
            _names = self._extract_tool_names(tools_info)
            if allowed is not None:
                _names = [n for n in _names if n in allowed]
            available_tools = _merge_mcp_tool_names(_names, allowed)
            registry.register(MCPExecuteTool(
                available_tools=available_tools,
                context_provider=context_provider,
                retries=1,
            ))
            registry.register(RespondTool())

        logger.info(
            f"ToolPolicy: built registry for {agent_type} (mode={mode}), "
            f"{registry.tool_count} tools: {registry.tool_names}"
        )
        return registry

    @staticmethod
    def _extract_tool_names(tools_info) -> List[str]:
        if not tools_info:
            return []
        return getattr(tools_info, "tools_name", None) or []


__all__ = ["ToolPolicy", "get_allowed_tool_set", "_merge_mcp_tool_names"]
