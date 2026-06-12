# -*- coding: utf-8 -*-
"""
OrchestrationMixin — Agent loop, tool registry, subagent, and skill-first pipeline.

Methods extracted from BaseAgent for readability.
"""

import json
import logging
import re
from datetime import datetime
from typing import List, Dict, Optional

from agent.schema import (
    StepType,
    StreamResponse,
    StreamStatusType,
)
from agent.tools.base import DirectResponseTool
from agent.tools.registry import ToolRegistry
from agent.tools.mcp_adapter import MCPToolAdapter
from agent.tools.primitive import MCPExecuteTool, RespondTool
from agent.tools.loop import AgentLoop, LoopEvent, LoopEventType
from agent.tools.subagent import SubagentManager, SubagentResult
from agent.utils import jinja_render
from agent.context.token_budget import estimate_tokens
from libs.language import get_localized_message, LANGUAGE_CODE_TO_NAME_MAP, ENGLISH_NAME_TO_CODE_MAP
from mcp.mcp_http_client import mcp_client
from web.config import config

logger = logging.getLogger(__name__)


class OrchestrationMixin:
    """Provides agent loop creation, skill-first pipeline, ReAct loop, and subagent management."""

    # ============================================================
    # Agent Orchestration Properties & Methods
    # ============================================================

    @property
    def tool_registry(self) -> ToolRegistry:
        """
        Lazy-initialized ToolRegistry that wraps MCP tools.
    
        On first access, creates a ToolRegistry, registers all MCP tools
        via MCPToolAdapter, and adds built-in tools (e.g. DirectResponseTool).
        """
        if self._tool_registry is None:
            self._tool_registry = ToolRegistry()
            from agent.tools.valuescan_open_api import ValueScanOpenAPITool
            from agent.tools.kucoin_openapi_public import KucoinOpenApiPublicTool
            from agent.tools.trading_decision import TradingDecisionTool
            from agent.tools.dexscan_open_api import DexScanOpenAPITool
            from agent.plan.tool_policy import get_allowed_tool_set

            _allowed = get_allowed_tool_set()
            if self._tools_info:
                if _allowed is None:
                    MCPToolAdapter.register_all(
                        self._tool_registry,
                        self._tools_info,
                        retries=1,
                    )
                else:
                    _exclude = [
                        n for n in (getattr(self._tools_info, "tools_name", None) or [])
                        if n not in _allowed
                    ]
                    MCPToolAdapter.register_all(
                        self._tool_registry,
                        self._tools_info,
                        retries=1,
                        exclude=_exclude,
                    )
            if _allowed is None or "valueScan_api" in _allowed:
                self._tool_registry.register(ValueScanOpenAPITool())
            if _allowed is None or "dexScan_api" in _allowed:
                self._tool_registry.register(DexScanOpenAPITool())
            if _allowed is None or "kucoin_openapi_public" in _allowed:
                self._tool_registry.register(KucoinOpenApiPublicTool())
            if _allowed is None or "trading_decision" in _allowed:
                self._tool_registry.register(TradingDecisionTool())
            self._tool_registry.register(DirectResponseTool())
            logger.info(f"ToolRegistry initialized with {self._tool_registry.tool_count} tools: {self._tool_registry.tool_names}")
        return self._tool_registry

    @property
    def subagent_manager(self) -> SubagentManager:
        """
        Lazy-initialized SubagentManager for spawning background tasks.
        """
        if self._subagent_manager is None:
            self._subagent_manager = SubagentManager(
                llm=self.llm,
                model_name=self.model_name,
                extra_body=None if config.use_azure_openai else {
                    "chat_template_kwargs": {"enable_thinking": False},
                },
            )
        return self._subagent_manager

    def create_agent_loop(
        self,
        max_iterations: int = 10,
        temperature: float = 0.2,
        max_tokens: int = 800,
        timeout: float = 30.0,
        tool_choice: str = "auto",
        exclude_tools: Optional[set] = None,
    ) -> AgentLoop:
        """
        Create a new AgentLoop with the current agent's LLM and tools.
    
        Args:
            max_iterations: Maximum ReAct loop iterations
            temperature: LLM temperature
            max_tokens: Max response tokens
            timeout: API call timeout
            tool_choice: Tool choice strategy
            exclude_tools: Tool names to exclude from this loop
        
        Returns:
            Configured AgentLoop instance
        """
        registry = self.tool_registry
        if exclude_tools:
            registry = registry.create_subset(exclude=exclude_tools)

        return AgentLoop(
            llm=self.llm,
            model_name=self.model_name,
            tool_registry=registry,
            max_iterations=max_iterations,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout or config.llm_api_timeout or 30.0,
            extra_body=None if config.use_azure_openai else {
                "chat_template_kwargs": {"enable_thinking": False},
            },
            tool_choice=tool_choice,
        )

    def create_skill_first_agent_loop(
        self,
        max_iterations: int = 10,
        temperature: float = 0.2,
        max_tokens: int = 800,
        timeout: float = 30.0,
        tool_choice: str = "auto",
    ) -> AgentLoop:
        """
        Create an AgentLoop with skill first primitive tools only.
        Used by QuickReasoningAgent and EventDeliveryAgent.
        """
        if not self._tools_info:
            raise RuntimeError("Tools info not loaded. Call _skill_first_run which loads it.")

        from agent.plan.tool_policy import _merge_mcp_tool_names, get_allowed_tool_set

        _allowed = get_allowed_tool_set()
        _names = list(getattr(self._tools_info, "tools_name", None) or [])
        if _allowed is not None:
            _names = [n for n in _names if n in _allowed]
        available_tools = _merge_mcp_tool_names(_names, _allowed)
        context_provider = lambda: {
            "user_id": getattr(self, "user_id", None) or "Unknown",
            "reply_language": self.cache.get("reply_language", "English"),
        }

        registry = ToolRegistry()
        registry.register(MCPExecuteTool(
            available_tools=available_tools,
            context_provider=context_provider,
            retries=1,
        ))
        registry.register(RespondTool())

        return AgentLoop(
            llm=self.llm,
            model_name=self.model_name,
            tool_registry=registry,
            max_iterations=max_iterations,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout or config.llm_api_timeout or 30.0,
            extra_body=None if config.use_azure_openai else {
                "chat_template_kwargs": {"enable_thinking": False},
            },
            tool_choice=tool_choice,
        )

    async def _skill_first_run(
        self,
        query: str,
        history: List,
        system_prompt: Optional[str] = None,
        max_iterations: int = 10,
        **kwargs,
    ):
        """
        Execute the query using skill first ReAct loop.
        Uses primitive tools (mcp_execute, respond) for autonomous orchestration.
        """
        if not self._tools_info:
            tools_info = await mcp_client.get_tools_info()
            self._tools_info = tools_info

        # Reset tool registry so create_skill_first_agent_loop builds fresh
        self._tool_registry = None

        loop = self.create_skill_first_agent_loop(
            max_iterations=max_iterations,
            temperature=kwargs.get("temperature", 0.2),
            max_tokens=kwargs.get("max_tokens", 800),
        )

        messages = []
        if history:
            context_payload = await self._prepare_context(
                history=history,
                history_turns=6,
                current_query_tokens=estimate_tokens(query or ""),
            )
            history_messages = context_payload.get("messages", [])
            if history_messages:
                messages.extend(history_messages)
        messages.append({"role": "user", "content": query})

        if not system_prompt:
            from agent.plan.tool_policy import _merge_mcp_tool_names, get_allowed_tool_set

            current_date = datetime.now().strftime("%Y-%m-%d")
            current_year = datetime.now().year
            _allowed_sf = get_allowed_tool_set()
            available_tools = list(getattr(self._tools_info, "tools_name", []) or [])
            if _allowed_sf is not None:
                available_tools = [n for n in available_tools if n in _allowed_sf]
            available_tools = _merge_mcp_tool_names(available_tools, _allowed_sf)
            try:
                system_prompt = await mcp_client.get_prompt(
                    name="skill_first_prompt",
                    data={
                        "current_date": current_date,
                        "current_year": current_year,
                        "available_mcp_tools": available_tools,
                        "supported_languages_list": [name for name in ENGLISH_NAME_TO_CODE_MAP.keys()],
                    },
                )
            except Exception:
                logger.warning("MCP prompt fetch failed, using local template", exc_info=True)
                system_prompt = jinja_render(
                    "skill_first_prompt",
                    data={
                        "current_date": current_date,
                        "current_year": current_year,
                        "available_mcp_tools": available_tools,
                        "supported_languages_list": [name for name in ENGLISH_NAME_TO_CODE_MAP.keys()],
                    },
                )

        tool_results_cache = []
        async for event in loop.run(messages, system_prompt=system_prompt):
            if event.type == LoopEventType.TOOL_CALL:
                for tc in event.tool_calls:
                    tool_name_display = tc.arguments.get("tool_name", tc.name) if tc.name == "mcp_execute" else tc.name
                    tool_name_display = get_localized_message(tool_name_display, self.system_lang_code) or tool_name_display
                    yield StreamResponse(
                        sessionId=self.session.id if self.session else "",
                        qaId=self.qa.id if self.qa else "",
                        status=StreamStatusType.START,
                        type=StepType.TOOL_EXECUTION,
                    ).model_dump_json(exclude={"save", "deliver"})

                    yield StreamResponse(
                        sessionId=self.session.id if self.session else "",
                        qaId=self.qa.id if self.qa else "",
                        status=StreamStatusType.PENDING,
                        type=StepType.TITLE,
                        content=get_localized_message("calling_tools_start", self.system_lang_code),
                    ).model_dump_json(exclude={"save", "deliver"})

                    content = tc.arguments.get("arguments", {}).get("query", "") if tc.name == "mcp_execute" else tc.arguments.get("suggested_response", "")
                    yield StreamResponse(
                        sessionId=self.session.id if self.session else "",
                        qaId=self.qa.id if self.qa else "",
                        status=StreamStatusType.PENDING,
                        type=StepType.CONTENT,
                        content=f"{tool_name_display}: {content}",
                    ).model_dump_json(exclude={"save", "deliver"})

            elif event.type == LoopEventType.TOOL_RESULT:
                for tr in event.tool_results:
                    tool_results_cache.append({
                        "name": tr.name,
                        "success": tr.result.success,
                        "content": tr.result.content,
                        "data": tr.result.data,
                    })
                    # Use actual_tool_name for mcp_execute; respond -> direct_response for compatibility
                    effective_tool_name = (
                        tr.result.metadata.get("actual_tool_name", tr.name)
                        if tr.name == "mcp_execute"
                        else ("direct_response" if tr.name == "respond" else tr.name)
                    )
                    if effective_tool_name != "direct_response":
                        self.cache.update({
                            "tool_name": effective_tool_name,
                            "tools_result": [{"text": tr.result.content}] if tr.result.content else None,
                        })
                        self._tool_call = {
                            "tool_call": {
                                "tool_call_id": tr.tool_call_id,
                                "name": effective_tool_name,
                                "arguments": json.dumps(tr.result.metadata.get("arguments", {}), ensure_ascii=False),
                            },
                            "content": "",
                        }
                    else:
                        self.cache.update({"tool_name": "direct_response"})
                        if tr.result.metadata.get("detect_language"):
                            self.cache.update({"reply_language": tr.result.metadata["detect_language"]})

                yield StreamResponse(
                    sessionId=self.session.id if self.session else "",
                    qaId=self.qa.id if self.qa else "",
                    status=StreamStatusType.PENDING,
                    type=StepType.TITLE_CORRECTION,
                    content=get_localized_message("calling_tools_end", self.system_lang_code),
                ).model_dump_json(exclude={"save", "deliver"})

                yield StreamResponse(
                    sessionId=self.session.id if self.session else "",
                    qaId=self.qa.id if self.qa else "",
                    status=StreamStatusType.END,
                    type=StepType.TOOL_EXECUTION,
                ).model_dump_json(exclude={"save", "deliver"})

            elif event.type == LoopEventType.FINAL_RESPONSE:
                self.cache.update({
                    "react_final_response": event.content,
                    "react_iterations": event.metadata.get("total_iterations", 0),
                    "react_tool_calls": event.metadata.get("total_tool_calls", 0),
                    "react_tool_results": tool_results_cache,
                })

            elif event.type == LoopEventType.ERROR:
                logger.error(f"Skill first loop error: {event.error}")
                yield StreamResponse(
                    sessionId=self.session.id if self.session else "",
                    qaId=self.qa.id if self.qa else "",
                    status=StreamStatusType.FAILED,
                    type=StepType.TOOL_EXECUTION,
                    log=event.error,
                ).model_dump_json(exclude={"save", "deliver"})

            elif event.type == LoopEventType.MAX_ITERATIONS:
                logger.warning(f"Skill first loop reached max iterations: {event.error}")

    _MARKET_ANALYSIS_KEYWORDS = re.compile(
        r"做[空多]|买[空多]|开[空多]|合约|杠杆|止[损盈]|机会[点]?|阻力|支撑|"
        r"short|long|futures|leverage|entry|resistance|support|"
        r"行情分析|技术分析|交易策略|趋势|价格预测|"
        r"market.?analysis|trading.?strateg|price.?predict",
        re.IGNORECASE,
    )
    # 加密货币相关：应走工具链（ValueScan / MCP 行情），禁止仅 web_search 快捷路径以免价格失真
    _CRYPTO_MARKET_CONTEXT_HINT = re.compile(
        r"\b(BTC|ETH|USDT|SOL|XRP|DOGE|BNB|ADA|DOT|LINK|LTC|BCH|KCS|TRX|AVAX|MATIC|SHIB)\b|"
        r"比特币|以太坊|狗狗币|山寨币|现货|合约|"
        r"上车|下车|抄底|梭哈|止盈|止损|开仓|平仓|多空|币价|k线|K线",
        re.IGNORECASE,
    )

    def _needs_web_search(self, query: str) -> bool:
        """Check if the query is a market/trading analysis that requires real-time data."""
        return bool(self._MARKET_ANALYSIS_KEYWORDS.search(query))

    def _use_market_analysis_web_search_shortcut(self, query: str) -> bool:
        """仅对「非加密货币标的」的行情类问题走 web_search 快捷路径；含 BTC/ETH/上车 等则用工具取数。"""
        if not self._needs_web_search(query):
            return False
        if self._CRYPTO_MARKET_CONTEXT_HINT.search(query):
            return False
        return True

    async def _run_skill_first_pipeline(
        self,
        user_query: str,
        max_iterations: int = 10,
        **kwargs,
    ):
        """
        Full skill first pipeline: analyze -> skill first loop -> generate response -> citations -> extract -> follow-up.
        Used by QuickReasoningAgent and EventDeliveryAgent.
        """
        # 1、分析问句
        async for event in self._analyz_query():
            yield event

        # 2、获取历史
        self.history = await self._get_history(self.session_id, self.user_id)

        # 3、获取回复语言（前置，后续分支都需要）
        reply_language = self.cache.get("reply_language")
        if not reply_language:
            reply_language = LANGUAGE_CODE_TO_NAME_MAP.get(
                self.system_lang_code, ("English", "英语")
            )[0]

        # 4、非加密货币的行情类 query 直接走 web_search；加密货币相关走下方 Skill/ReAct（可用 valueScan_api）
        if self._use_market_analysis_web_search_shortcut(user_query):
            logger.info(
                f"Market analysis query (non-crypto shortcut), skipping ReAct loop, "
                f"direct web_search pipeline for: {user_query[:80]}"
            )
            async for event in self._fallback_via_web_search(
                user_query, reply_language, include_follow_up=False,
            ):
                yield event

            async for event in self._generate_follow_up_questions(
                user_query, self.history, reply_language,
            ):
                yield event
            return

        # 5、Skill First ReAct 循环（非交易分析类 query）
        async for event in self._skill_first_run(
            query=user_query,
            history=self.history,
            max_iterations=max_iterations,
            **kwargs,
        ):
            yield event

        # 6、生成最终回复
        react_response = self.cache.get("react_final_response", "")
        tools_result = self.cache.get("tools_result")

        if tools_result or self.cache.get("tool_name"):
            async for event in self._generate_final_response(
                user_query,
                tools_result,
                self.history,
                reply_language,
            ):
                yield event
        elif react_response:
            async for event in self._generate_final_response(
                user_query,
                None,
                self.history,
                reply_language,
            ):
                yield event

        # 7、引用
        async for event in self._generate_final_citations(self.cache.get("full_response", "")):
            yield event

        # 8、币种提取
        async for event in self._extract_currency_suggestions(self.cache.get("full_response", "")):
            yield event

        # 9、推荐问句
        async for event in self._generate_follow_up_questions(user_query, self.history, reply_language):
            yield event

    async def _react_run(
        self,
        query: str,
        history: List,
        system_prompt: Optional[str] = None,
        max_iterations: int = 10,
        **kwargs,
    ):
        """
        Execute the query using the ReAct loop pattern.
    
        This is an alternative to the linear pipeline (_decide_tools + _call_tools).
        It supports multi-turn tool calling: the LLM can call tools, observe results,
        and decide to call more tools or produce a final response.
    
        Yields StreamResponse-compatible JSON strings for SSE streaming.
    
        Args:
            query: User query
            history: Conversation history
            system_prompt: Optional system prompt
            max_iterations: Max ReAct iterations
            **kwargs: Additional parameters
        """
        # Ensure tools are loaded
        if not self._tools_info:
            tools_info = await mcp_client.get_tools_info()
            self._tools_info = tools_info

        # Reset tool registry to pick up latest MCP tools
        self._tool_registry = None

        loop = self.create_agent_loop(
            max_iterations=max_iterations,
            temperature=kwargs.get("temperature", 0.2),
            max_tokens=kwargs.get("max_tokens", 800),
        )

        # Build messages
        messages = []
        if history:
            context_payload = await self._prepare_context(
                history=history,
                history_turns=6,
                current_query_tokens=estimate_tokens(query or ""),
            )
            history_messages = context_payload.get("messages", [])
            if history_messages:
                messages.extend(history_messages)
        messages.append({"role": "user", "content": query})

        # Get system prompt from MCP if not provided
        if not system_prompt:
            current_date = datetime.now().strftime("%Y-%m-%d")
            current_year = datetime.now().year
            system_prompt = await mcp_client.get_prompt(
                name="tool_decision_prompt",
                data={
                    "current_date": current_date,
                    "current_year": current_year,
                    "external_tools_list": self.tool_registry.tool_names,
                    "supported_languages_list": [name for name in ENGLISH_NAME_TO_CODE_MAP.keys()],
                },
            )

        # Run the ReAct loop and translate events to StreamResponse
        tool_results_cache = []
        async for event in loop.run(messages, system_prompt=system_prompt):
            if event.type == LoopEventType.TOOL_CALL:
                # Emit tool execution start
                for tc in event.tool_calls:
                    tool_name_display = get_localized_message(tc.name, self.system_lang_code) or tc.name
                    yield StreamResponse(
                        sessionId=self.session.id if self.session else "",
                        qaId=self.qa.id if self.qa else "",
                        status=StreamStatusType.START,
                        type=StepType.TOOL_EXECUTION,
                    ).model_dump_json(exclude={"save", "deliver"})

                    yield StreamResponse(
                        sessionId=self.session.id if self.session else "",
                        qaId=self.qa.id if self.qa else "",
                        status=StreamStatusType.PENDING,
                        type=StepType.TITLE,
                        content=get_localized_message("calling_tools_start", self.system_lang_code),
                    ).model_dump_json(exclude={"save", "deliver"})

                    yield StreamResponse(
                        sessionId=self.session.id if self.session else "",
                        qaId=self.qa.id if self.qa else "",
                        status=StreamStatusType.PENDING,
                        type=StepType.CONTENT,
                        content=f"{tool_name_display}: {tc.arguments.get('query', '')}",
                    ).model_dump_json(exclude={"save", "deliver"})

            elif event.type == LoopEventType.TOOL_RESULT:
                for tr in event.tool_results:
                    tool_results_cache.append({
                        "name": tr.name,
                        "success": tr.result.success,
                        "content": tr.result.content,
                        "data": tr.result.data,
                    })
                    # Store in cache for _generate_final_response compatibility
                    if tr.name != "direct_response":
                        self.cache.update({
                            "tool_name": tr.name,
                            "tools_result": [{"text": tr.result.content}] if tr.result.content else None,
                        })
                        self._tool_call = {
                            "tool_call": {
                                "tool_call_id": tr.tool_call_id,
                                "name": tr.name,
                                "arguments": json.dumps(tr.result.metadata.get("arguments", {}), ensure_ascii=False),
                            },
                            "content": "",
                        }
                    else:
                        self.cache.update({
                            "tool_name": "direct_response",
                        })
                        if tr.result.metadata.get("detect_language"):
                            self.cache.update({"reply_language": tr.result.metadata["detect_language"]})

                # Emit tool execution end
                yield StreamResponse(
                    sessionId=self.session.id if self.session else "",
                    qaId=self.qa.id if self.qa else "",
                    status=StreamStatusType.PENDING,
                    type=StepType.TITLE_CORRECTION,
                    content=get_localized_message("calling_tools_end", self.system_lang_code),
                ).model_dump_json(exclude={"save", "deliver"})

                yield StreamResponse(
                    sessionId=self.session.id if self.session else "",
                    qaId=self.qa.id if self.qa else "",
                    status=StreamStatusType.END,
                    type=StepType.TOOL_EXECUTION,
                ).model_dump_json(exclude={"save", "deliver"})

            elif event.type == LoopEventType.FINAL_RESPONSE:
                # Store the final content for downstream steps
                self.cache.update({
                    "react_final_response": event.content,
                    "react_iterations": event.metadata.get("total_iterations", 0),
                    "react_tool_calls": event.metadata.get("total_tool_calls", 0),
                    "react_tool_results": tool_results_cache,
                })

            elif event.type == LoopEventType.ERROR:
                logger.error(f"ReAct loop error: {event.error}")
                yield StreamResponse(
                    sessionId=self.session.id if self.session else "",
                    qaId=self.qa.id if self.qa else "",
                    status=StreamStatusType.FAILED,
                    type=StepType.TOOL_EXECUTION,
                    log=event.error,
                ).model_dump_json(exclude={"save", "deliver"})

            elif event.type == LoopEventType.MAX_ITERATIONS:
                logger.warning(f"ReAct loop reached max iterations: {event.error}")

    async def spawn_subagent(
        self,
        task: str,
        label: Optional[str] = None,
        callback: Optional[callable] = None,
        exclude_tools: Optional[set] = None,
        metadata: Optional[Dict] = None,
    ) -> str:
        """
        Spawn a background subagent task.
    
        Args:
            task: Task description
            label: Human-readable label
            callback: Async callback for results
            exclude_tools: Tools to exclude from the subagent
            metadata: Additional metadata
        
        Returns:
            task_id of the spawned subagent
        """
        # Create a scoped tool registry (no spawn capability)
        scoped_registry = self.tool_registry.create_subset(
            exclude=exclude_tools or set()
        )
        return await self.subagent_manager.spawn(
            task=task,
            tool_registry=scoped_registry,
            label=label,
            callback=callback,
            metadata=metadata,
        )
