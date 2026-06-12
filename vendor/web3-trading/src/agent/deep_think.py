import asyncio
import json
import logging
import re

from web.config import config
from agent.plan.task_graph import TaskStatus
from agent.plan.orchestrator_agent import OrchestratorAgent
from agent.base import AgentType
from agent.schema import StepType, StreamResponse, StreamStatusType
from agent.context.token_budget import estimate_tokens
from libs.language import LANGUAGE_CODE_TO_NAME_MAP, get_localized_message

logger = logging.getLogger(__name__)


class DeepThinkAgent(OrchestratorAgent):
    """DEEP_THINK — 深度思考 Agent（带 DAG 动态编排 + 降级兜底）

    前端传 agentType=AUTO 或 DEEP_THINK 时均由此 Agent 处理。是否走自动编排（plan + 工具 DAG）
    由本 Agent 内部根据 plan() 结果自动判断，不依赖前端传的类型：
    - plan.task_count == 1 且无需工具 → 快速通道，直接 LLM 深度思考
    - 否则 → plan 模式，执行 _execute_plan() 后再生成回答

    继承 OrchestratorAgent 的完整 DAG 编排能力，始终开启深度思考面板。

    执行流程 (SSE 标题事件绑定到实际工作):
        正常路径 (自动判断走 plan 模式):
            "正在分析问题..." ← plan()  意图分类 + DAG 规划
            "正在搜索关键信息..." ← _execute_plan()  工具 DAG 并行执行
            "正在深度思考..." ← _generate_final_response(enable_think=True)
            → citations → currency → follow_up

        快速通道 (自动判断无需工具):
            "正在分析问题..." ← plan()
            "正在深度思考..." ← _generate_final_response(enable_think=True)
            → citations → currency → follow_up

        降级路径 (MCP 不可用 / plan 失败 / DAG 执行异常):
            web_search 兜底 → _generate_final_response(enable_think=True)
            → citations → currency → follow_up

    与其他 Agent 的关系:
        - 继承自 OrchestratorAgent，复用其 DAG 编排、工具调用、委派等能力
        - _FORCE_ENABLE_THINK=True 使 enable_think 始终为 True
        - DEEP_RESEARCH 类型的查询会通过 _DELEGATABLE_AGENTS 委派给 DeepResearchAgent
        - 降级方案复用 BaseAgent._fallback_via_web_search 统一降级
    """
    NAME = AgentType.DEEP_THINK
    _FORCE_ENABLE_THINK = True

    async def _run(self):
        user_query = self.query

        # 1. 获取历史 & 预设回复语言（用于降级路径）
        self.history = await self._get_history(self.session_id, self.user_id)
        reply_language = self._resolve_reply_language()

        try:
            # 2. 创建编排器 & 获取 MCP 工具信息
            orchestrator = self._create_orchestrator()
            tools_info = await self._fetch_tools_info()

            if tools_info is None:
                raise RuntimeError("MCP tools unavailable")

            # 3. 分析问句（与 BaseAgent / OrchestratorAgent 一致，便于会话记忆与 step 落库）
            async for event in self._analyz_query():
                yield event

            # 转为 {role, content} 对话格式，否则 plan_tools 会把 QA 对象当 messages 发给 LLM 导致 400
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
                f"DeepThinkAgent: route_agent_type={route_agent_type}, "
                f"needs_tools={needs_tools}, task_count={plan.task_count}, "
                f"layers={plan.execution_layers}"
            )

            # 4. 如果意图匹配专属 Agent（如 DEEP_RESEARCH），委派执行
            if route_agent_type in self._DELEGATABLE_AGENTS:
                async for event in self._delegate_to_agent(route_agent_type, user_query):
                    yield event
                return

            reply_language = self._detect_language_from_plan(plan)

            # 5. 根据计划执行
            use_plan_mode = not (plan.task_count == 1 and not self._single_node_needs_tool(plan))
            tools_planned = [n.tool_name for n in plan.tasks.values() if n.tool_name]

            if not use_plan_mode:
                # 无需工具 — 直接 LLM 深度思考回答（快速通道）
                logger.info(
                    "DeepThinkAgent: quick path (no tools), task_count=1"
                )
                async for event in self._generate_final_response(
                    user_query, None, self.history, reply_language,
                    enable_think=True,
                ):
                    yield event
            else:
                # Plan 模式：优先可选路径 — TauricResearch TradingAgents 多智能体图（配置 use_trading_agents）
                ta_done = False
                if getattr(config, "use_trading_agents", False):
                    from agent.trading_agents.pipeline import (
                        stream_trading_agents_analysis,
                    )
                    async for event in stream_trading_agents_analysis(
                        self, user_query, reply_language, plan
                    ):
                        yield event
                    ta_done = bool(self.cache.get("trading_agents_completed"))

                if ta_done:
                    logger.info(
                        "DeepThinkAgent: TradingAgents graph completed, skipping MCP tool DAG"
                    )
                else:
                    # 默认 / 回退：MCP 工具 DAG（含 catalog skills：crypto_insight/crypto_evaluation/…）
                    logger.info(
                        f"DeepThinkAgent: DAG plan mode, task_count={plan.task_count}, "
                        f"layers={plan.execution_layers}, tools_planned={tools_planned}"
                    )
                    async for event in self._run_dag_pipeline(
                        user_query=user_query,
                        max_iterations=3,
                        enable_think=True,
                        skip_analyz_query=True,
                    ):
                        yield event

        except asyncio.CancelledError:
            raise
        except Exception as e:
            # 降级: 编排失败时回退到 web_search + LLM
            logger.warning(f"DeepThinkAgent orchestration failed, falling back to web_search: {e}")
            async for event in self._fallback_via_web_search(
                user_query, reply_language, enable_think=True,
            ):
                yield event
            return

        # 6. 后处理: 引用提取、币种提取、推荐追问
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

    # ------------------------------------------------------------------

    def _resolve_reply_language(self) -> str:
        """从 system_lang_code 解析回复语言，用于降级路径（plan 不可用时）。"""
        if self.system_lang_code:
            return LANGUAGE_CODE_TO_NAME_MAP.get(
                self.system_lang_code, ("English",)
            )[0]
        return "English"

    # ------------------------------------------------------------------
    # Tool result quality gate
    # ------------------------------------------------------------------

    _ABSURD_PRICE_THRESHOLD = 1e12  # $1 trillion — no single crypto is worth this
    _PLACEHOLDER_PATTERNS = re.compile(
        r"9{6,}|0{6,}|1{6,}|placeholder|N/?A|null|undefined|error",
        re.IGNORECASE,
    )

    @classmethod
    def _is_tools_result_usable(cls, tools_result: str, plan) -> bool:
        """Check whether tool results contain meaningful data worth passing to the LLM.

        Returns False (= should fallback) when:
        - tools_result is empty / blank
        - ALL completed tool nodes returned data that looks like placeholder / absurd values
        - Every numeric "value" field exceeds the absurd-price threshold

        Returns True as soon as any single tool node appears to have real data,
        so the gate is intentionally lenient — it only blocks the obviously broken case.
        """
        if not tools_result or not tools_result.strip():
            return False

        completed_nodes = [
            n for n in plan.tasks.values()
            if n.status == TaskStatus.COMPLETED and n.result
        ]
        if not completed_nodes:
            return False

        nodes_with_bad_data = 0
        for node in completed_nodes:
            if cls._node_result_looks_bad(str(node.result)):
                nodes_with_bad_data += 1

        if nodes_with_bad_data == len(completed_nodes):
            logger.warning(
                "All %d completed tool nodes returned suspicious data",
                len(completed_nodes),
            )
            return False

        return True

    @classmethod
    def _node_result_looks_bad(cls, text: str) -> bool:
        """Heuristic check on a single tool-node result string."""
        if cls._PLACEHOLDER_PATTERNS.search(text):
            nums = cls._extract_numeric_values(text)
            if nums and all(abs(v) >= cls._ABSURD_PRICE_THRESHOLD for v in nums):
                return True

        try:
            obj = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            obj = None

        if isinstance(obj, dict):
            return cls._dict_looks_bad(obj)

        return False

    @classmethod
    def _dict_looks_bad(cls, d: dict) -> bool:
        """Recursively check a parsed JSON dict for absurd numeric values."""
        value_fields = ("latest_value", "value", "price", "close", "last")
        for key, val in d.items():
            if isinstance(val, dict):
                if cls._dict_looks_bad(val):
                    return True
            elif isinstance(val, (int, float)) and key.lower() in value_fields:
                if abs(val) >= cls._ABSURD_PRICE_THRESHOLD:
                    return True
            elif isinstance(val, str) and key == "overall_summary":
                nums = cls._extract_numeric_values(val)
                if nums and all(abs(v) >= cls._ABSURD_PRICE_THRESHOLD for v in nums):
                    return True
        return False

    @staticmethod
    def _extract_numeric_values(text: str) -> list:
        """Pull out all dollar-amount or plain-number values from a text snippet."""
        matches = re.findall(r"\$?([\d,]+(?:\.\d+)?)", text)
        results = []
        for m in matches:
            try:
                results.append(float(m.replace(",", "")))
            except ValueError:
                continue
        return results
