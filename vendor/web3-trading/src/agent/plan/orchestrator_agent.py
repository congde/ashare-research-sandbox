# -*- coding: utf-8 -*-
"""
OrchestratorAgent - Dynamic task orchestration agent.

When the client sends agentType=AUTO, this agent:
1. Fetches available MCP tools
2. Uses TaskPlanner.plan_tools() to build a tool-level DAG
3. Executes the DAG via TaskOrchestrator with ToolAwareRunner
4. Streams execution progress to the client
5. Generates a final response from collected tool results

Subclasses (QuickReasoningAgent, EventDeliveryAgent, DeepThinkAgent) share the
same Plan → Execute → Response pipeline; they only override policy hooks:
    _DELEGATABLE_AGENTS  – which agent types can be delegated to
    _resolve_enable_think()  – whether the deep-think panel is shown
"""

import asyncio
import json
import logging

from agent.base import BaseAgent, AgentType
from agent.dag_execution import DAGExecutionMixin
from agent.context.token_budget import estimate_tokens
from agent.schema import StepType, StreamResponse, StreamStatusType, StepModel
from agent.plan.task_graph import TaskOrchestrator, TaskStatus
from libs.language import (
    LANGUAGE_CODE_TO_NAME_MAP,
    ENGLISH_NAME_TO_CODE_MAP,
    get_localized_message,
)

logger = logging.getLogger(__name__)


class OrchestratorAgent(DAGExecutionMixin, BaseAgent):
    NAME = AgentType.AUTO

    _DELEGATABLE_AGENTS = {"DEEP_RESEARCH"}

    # ----------------------------------------------------------
    # Policy hooks (override in subclasses)
    # ----------------------------------------------------------

    def _resolve_enable_think(self, route_agent_type: str) -> bool:
        """Whether to activate the deep-think panel for this request."""
        return route_agent_type == "DEEP_THINK" or getattr(self, '_FORCE_ENABLE_THINK', False)

    def _resolve_reply_language(self) -> str:
        """Resolve reply language from *system_lang_code* (used on fallback path
        before the planner has a chance to detect language)."""
        if self.system_lang_code:
            return LANGUAGE_CODE_TO_NAME_MAP.get(
                self.system_lang_code, ("English",)
            )[0]
        return "English"

    # ----------------------------------------------------------
    # Main execution flow
    # ----------------------------------------------------------

    async def _run(self):
        user_query = self.query

        # Pre-try: history & language must be available for fallback path
        self.history = await self._get_history(self.session_id, self.user_id)
        reply_language = self._resolve_reply_language()

        try:
            orchestrator = self._create_orchestrator()
            tools_info = await self._fetch_tools_info()

            if tools_info is None:
                raise RuntimeError("MCP tools unavailable")

            async for event in self._analyz_query():
                yield event

            history_messages = None
            if self.history:
                context_payload = await self._prepare_context(
                    history=self.history,
                    history_turns=6,
                    current_query_tokens=estimate_tokens(user_query or ""),
                )
                history_messages = context_payload.get("messages", [])
            plan = await orchestrator.plan(
                query=user_query,
                history=history_messages,
                metadata=self._build_plan_metadata(),
                tools_info=tools_info,
            )

            route_agent = plan.tasks.get("main")
            route_agent_type = route_agent.agent_type if route_agent else "QUICK_REASONING"
            needs_tools = plan.metadata.get("route_needs_tools", True)

            logger.info(
                f"{self.__class__.__name__}: route_agent_type={route_agent_type}, "
                f"needs_tools={needs_tools}, task_count={plan.task_count}, "
                f"layers={plan.execution_layers}"
            )

            if route_agent_type in self._DELEGATABLE_AGENTS:
                async for event in self._delegate_to_agent(route_agent_type, user_query):
                    yield event
                return

            reply_language = self._detect_language_from_plan(plan)
            enable_think = self._resolve_enable_think(route_agent_type)

            if plan.task_count == 1 and not self._single_node_needs_tool(plan):
                async for event in self._generate_final_response(
                    user_query, None, self.history, reply_language,
                    enable_think=enable_think,
                ):
                    yield event
            else:
                # DAG Pipeline（含 catalog skills：crypto_insight/crypto_evaluation/crypto_comparison）
                async for event in self._run_dag_pipeline(
                    user_query=user_query,
                    max_iterations=3,
                    enable_think=enable_think,
                    skip_analyz_query=True,
                ):
                    yield event

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(
                f"{self.__class__.__name__} orchestration failed, "
                f"falling back to web_search: {e}"
            )
            async for event in self._fallback_via_web_search(
                user_query, reply_language,
                enable_think=self._resolve_enable_think(""),
            ):
                yield event
            return

        # Post-processing (only reached on success; fallback path handles its own)
        async for event in self._generate_final_citations(
            self.cache.get("full_response", ""),
        ):
            yield event

        async for event in self._extract_currency_suggestions(
            self.cache.get("full_response", ""),
        ):
            yield event

        async for event in self._generate_follow_up_questions(
            user_query, self.history, reply_language,
        ):
            yield event

    # ----------------------------------------------------------
    # Internal helpers
    # ----------------------------------------------------------

    async def _delegate_to_agent(self, agent_type_str: str, user_query: str):
        from agent import ALL_AGENTS
        from agent.schema import AgentType

        try:
            target_type = AgentType(agent_type_str)
        except ValueError:
            target_type = AgentType.QUICK_REASONING

        TargetAgent = ALL_AGENTS.get(target_type)
        if not TargetAgent:
            logger.warning(f"No agent registered for {agent_type_str}, falling back to QUICK_REASONING")
            from agent import QuickReasoningAgent
            TargetAgent = QuickReasoningAgent

        logger.info(f"OrchestratorAgent delegating to {TargetAgent.__name__}")

        delegate = TargetAgent(
            query=user_query,
            extra_body=self.extra_body,
            user_id=self.user_id,
            session_id=self.session_id,
            **self.kwargs,
        )
        delegate.session = self.session
        delegate.qa = self.qa
        delegate.llm = self.llm
        delegate.model_name = self.model_name
        delegate.system_lang_code = self.system_lang_code
        delegate.memory = self.memory
        delegate.cache = self.cache
        delegate.history = self.history

        async for event in delegate._run():
            yield event

    async def _fetch_tools_info(self):
        from mcp.mcp_http_client import mcp_client
        try:
            tools_info = await mcp_client.get_tools_info()
            if tools_info:
                self._tools_info = tools_info
            return tools_info
        except Exception as e:
            logger.warning(f"Failed to fetch MCP tools: {e}")
            return None

    def _create_orchestrator(self) -> TaskOrchestrator:
        from web.config import config
        extra_body = None if config.use_azure_openai else {
            "chat_template_kwargs": {"enable_thinking": False},
        }
        return TaskOrchestrator(
            llm=self.llm,
            model_name=self.model_name,
            extra_body=extra_body,
            planner_timeout=60
        )

    def _build_plan_metadata(self) -> dict:
        meta = {}
        if self.extra_body and getattr(self.extra_body, "eventId", None):
            meta["eventId"] = self.extra_body.eventId
        return meta

    def _detect_language_from_plan(self, plan) -> str:
        """Resolve reply language: prefer cache (set by Phase 1 detect_language),
        then fall back to system_lang_code."""
        cached = self.cache.get("reply_language")
        if cached:
            return cached
        if self.system_lang_code:
            return LANGUAGE_CODE_TO_NAME_MAP.get(
                self.system_lang_code, ("English",)
            )[0]
        return "English"

    @staticmethod
    def _single_node_needs_tool(plan) -> bool:
        main = next(iter(plan.tasks.values()), None)
        return main is not None and main.is_tool_node

    async def _execute_plan(self, orchestrator: TaskOrchestrator, plan) -> str:
        reply_language = self._detect_language_from_plan(plan)
        runner = orchestrator.create_tool_runner(
            plan=plan,
            context_provider=lambda: {
                "user_id": self.user_id or "Unknown",
                "reply_language": reply_language,
            },
        )

        await orchestrator.execute(plan, agent_runner=runner)

        completed = [
            n for n in plan.tasks.values()
            if n.status == TaskStatus.COMPLETED and n.result
        ]
        if not completed:
            return ""

        self._postprocess_tool_results(completed, reply_language)

        parts = []
        for node in completed:
            label = node.tool_name or node.query
            parts.append(f"[{label}]\n{node.result}")
        return "\n\n---\n\n".join(parts)

    _CARD_TOOL_META = {
        "recharge_and_withdraw": {"ref_type": "CUSTOM_CARD", "tag_name": "custom_card"},
        "coin_screener": {"ref_type": "CUSTOM_TABLE", "tag_name": "custom_table"},
    }

    def _postprocess_tool_results(self, completed_nodes, reply_language: str) -> None:
        """Populate cache entries that _generate_final_response needs for
        RESOURCE_REFERENCE cards.  Supports multiple card-producing tools in
        a single plan by collecting them into ``resource_references``."""
        refs: list[dict] = []

        for node in completed_nodes:
            if not node.tool_name:
                continue

            if node.tool_name == "recharge_and_withdraw":
                try:
                    tools_data_map = json.loads(node.result)
                except (json.JSONDecodeError, TypeError):
                    tools_data_map = {}

                payment_method_list = tools_data_map.get("paymentMethodList", [])
                if len(payment_method_list) > 1:
                    priority_order = ["FAST_SELL", "WITHDRAW", "OTC_SELL", "CRYPTO_WITHDRAW"]
                    selected = next(
                        (m for code in priority_order
                         for m in payment_method_list
                         if m.get("paymentMethodCode") == code),
                        payment_method_list[0],
                    )
                    tools_data_map["paymentMethodList"] = [selected]
                self.cache["recharge_withdraw_card_data"] = tools_data_map

                refs.append({
                    "tool_name": node.tool_name,
                    "tool_call_id": node.tool_call_id,
                    "ref_type": "CUSTOM_CARD",
                    "tag_name": "custom_card",
                    "data": tools_data_map,
                })

            elif node.tool_name == "coin_screener":
                try:
                    reply_language_code = ENGLISH_NAME_TO_CODE_MAP.get(
                        reply_language, self.system_lang_code or "en"
                    )
                    web_title_name = get_localized_message("recommend_crypto_table_web_title_name", reply_language_code)
                    web_title_price = get_localized_message("recommend_crypto_table_web_title_price", reply_language_code)
                    web_title_change = get_localized_message("recommend_crypto_table_web_title_24_change", reply_language_code)
                    web_title_volume = get_localized_message("recommend_crypto_table_web_title_24_volume", reply_language_code)
                    web_title_action = get_localized_message("recommend_crypto_table_web_title_action", reply_language_code)
                    web_title_trade = get_localized_message("recommend_crypto_table_web_title_trade", reply_language_code)
                    web_title_details = get_localized_message("recommend_crypto_table_web_title_details", reply_language_code)
                    app_title_coin = get_localized_message("recommend_crypto_table_app_title_coin", reply_language_code)
                    app_title_vol = get_localized_message("recommend_crypto_table_app_title_vol", reply_language_code)
                    app_title_price = get_localized_message("recommend_crypto_table_app_title_price", reply_language_code)
                    app_title_change = get_localized_message("recommend_crypto_table_web_title_24_change", reply_language_code)
                    try:
                        tools_data_list = json.loads(node.result)
                        for tool_data in tools_data_list:
                            tool_data["coinButtonName"] = web_title_details
                            tool_data["tradeButtonName"] = web_title_trade
                    except (json.JSONDecodeError, TypeError):
                        logger.error(f"Parse coin_screener result JSON error")
                        tools_data_list = []
                    table_data = {
                        "webTitle": [web_title_name, web_title_price, web_title_change, web_title_volume, web_title_action],
                        "appTitle": [f"{app_title_coin} / {app_title_vol}", app_title_price, app_title_change],
                        "data": tools_data_list,
                    }
                    self.cache["recommend_crypto_table_data"] = table_data
                except Exception as e:
                    logger.error(f"Failed to parse coin_screener data for RESOURCE_REFERENCE: {e}")
                    table_data = {}

                refs.append({
                    "tool_name": node.tool_name,
                    "tool_call_id": node.tool_call_id,
                    "ref_type": "CUSTOM_TABLE",
                    "tag_name": "custom_table",
                    "data": table_data,
                })

        if refs:
            self.cache["resource_references"] = refs
            first = refs[0]
            self.cache["tool_name"] = first["tool_name"]
            self._tool_call = {
                "tool_call": {
                    "tool_call_id": first["tool_call_id"],
                    "name": first["tool_name"],
                },
                "content": "",
            }

    @staticmethod
    def _format_execution_summary(plan) -> str:
        completed = sum(1 for n in plan.tasks.values() if n.status == TaskStatus.COMPLETED)
        failed = sum(1 for n in plan.tasks.values() if n.status == TaskStatus.FAILED)
        tools_used = [
            n.tool_name for n in plan.tasks.values()
            if n.tool_name and n.status == TaskStatus.COMPLETED
        ]
        summary_parts = []
        if tools_used:
            summary_parts.append(f"Tools: {', '.join(tools_used)}")
        summary_parts.append(f"{completed} completed")
        if failed:
            summary_parts.append(f"{failed} failed")
        return " | ".join(summary_parts)
