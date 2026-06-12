# -*- coding: utf-8 -*-
"""
BaseAgent DAG Execution Extension

为 BaseAgent 添加 Plan & DAG Execute 能力，支持复杂多工具调用场景。
支持两阶段按需加载: Phase 1 选择 → Phase 2 规划
"""

import json
import logging
import re
import time
import asyncio
import uuid
import json_repair
from typing import List, Optional, Dict, Any, AsyncGenerator

from agent.catalog import ToolSkillCatalog, CatalogItem, TOOL_SUMMARIES
from agent.dag_executor import DAGPlan, DAGExecutor, DAGTask
from agent.schema import StreamResponse, StepType, StreamStatusType, StepModel, StepStatusType, HistoryStepType
from agent.utils import jinja_render, truncate_web_search_query, strip_think_content
from mcp.mcp_http_client import mcp_client
from libs.language import get_localized_message, LANGUAGE_CODE_TO_NAME_MAP, ENGLISH_NAME_TO_CODE_MAP
from llm.llm import stream_llm
from web.context import context
from web.config import config
from agent.schema import ResourceReference, ReferenceType
from agent.plan.task_graph import TaskStatus
from libs.crypto_extractor import crypto_extractor
from agent.context.token_budget import estimate_tokens

logger = logging.getLogger(__name__)

class DAGExecutionMixin:
    """
    DAG 执行 Mixin，为 BaseAgent 添加 Plan & Execute 能力
    
    使用方式：
    ```python
    from agent.base import BaseAgent
    from agent.dag_execution import DAGExecutionMixin
    
    class MyAgent(DAGExecutionMixin, BaseAgent):
        async def _run(self):
            async for event in self._run_dag_pipeline(
                user_query=self.query,
                max_iterations=3
            ):
                yield event
    ```
    """
    
    # ================================================================
    # Catalog 初始化
    # ================================================================

    async def _init_catalog(self) -> ToolSkillCatalog:
        """
        初始化工具与技能目录（含 MCP 工具 + YAML 技能）
        
        Returns:
            已加载的 ToolSkillCatalog
        """
        if hasattr(self, '_catalog') and self._catalog is not None:
            return self._catalog
        
        catalog = ToolSkillCatalog()
        _allowed = getattr(config, "agent_allowed_tools", None)
        _allowed_set = set(_allowed) if _allowed else None

        # 加载 MCP 工具
        if self._tools_info:
            catalog.load_tools(self._tools_info)
        if _allowed_set:
            catalog.apply_tool_allowlist(_allowed_set)

        # 加载 YAML 技能（支持多 document YAML 合并）
        catalog.load_skills()

        # 注册虚拟工具: direct_response（不调用外部工具，直接走 final_response_prompt）
        if _allowed_set is None or "direct_response" in _allowed_set:
            if "direct_response" not in catalog.all_names:
                catalog._items["direct_response"] = CatalogItem(
                    name="direct_response",
                    kind="tool",
                    summary=TOOL_SUMMARIES.get("direct_response", "Directly respond without external tools."),
                    description="Directly respond without any external tool. ONLY for trivial chitchat (greetings, clarifications, simple identity questions). Do NOT use for queries involving assets, markets, prices, analysis, weather, or factual data.",
                )

        # 本地 ValueScan / KuCoin 公开 API：用进程内 schema 覆盖 MCP 同名条目（若有）
        from agent.tools.registry import default_registry

        if _allowed_set is None or "valueScan_api" in _allowed_set:
            vs_tool = default_registry.get_tool("valueScan_api")
            if vs_tool:
                catalog._items["valueScan_api"] = CatalogItem(
                    name="valueScan_api",
                    kind="tool",
                    summary=TOOL_SUMMARIES.get("valueScan_api", ""),
                    description=vs_tool.description,
                    parameters=ToolSkillCatalog._parse_parameters(vs_tool.parameters),
                )
        if _allowed_set is None or "dexScan_api" in _allowed_set:
            dx_tool = default_registry.get_tool("dexScan_api")
            if dx_tool:
                catalog._items["dexScan_api"] = CatalogItem(
                    name="dexScan_api",
                    kind="tool",
                    summary=TOOL_SUMMARIES.get("dexScan_api", ""),
                    description=dx_tool.description,
                    parameters=ToolSkillCatalog._parse_parameters(dx_tool.parameters),
                )
        if _allowed_set is None or "kucoin_openapi_public" in _allowed_set:
            ko_tool = default_registry.get_tool("kucoin_openapi_public")
            if ko_tool:
                catalog._items["kucoin_openapi_public"] = CatalogItem(
                    name="kucoin_openapi_public",
                    kind="tool",
                    summary=TOOL_SUMMARIES.get("kucoin_openapi_public", ""),
                    description=ko_tool.description,
                    parameters=ToolSkillCatalog._parse_parameters(ko_tool.parameters),
                )
        if _allowed_set is None or "trading_decision" in _allowed_set:
            td_tool = default_registry.get_tool("trading_decision")
            if td_tool:
                catalog._items["trading_decision"] = CatalogItem(
                    name="trading_decision",
                    kind="tool",
                    summary=TOOL_SUMMARIES.get("trading_decision", ""),
                    description=td_tool.description,
                    parameters=ToolSkillCatalog._parse_parameters(td_tool.parameters),
                )

        self._catalog = catalog
        logger.info(f"[Catalog] Initialized: {len(catalog.tool_names)} tools, {len(catalog.skill_names)} skills")
        return catalog

    # ================================================================
    # Phase 1: 选择阶段
    # ================================================================

    async def _select_tools(self, query: str, history: List, catalog: ToolSkillCatalog) -> tuple:
        """
        Phase 1: 让 LLM 从简短目录中选择需要的 tool/skill，并识别 primary_intent
        
        只给 LLM 看每个 tool/skill 的名称 + 摘要（~3句话），
        LLM 返回 {"selected": [...], "primary_intent": "..."} 格式。
        
        Args:
            query: 用户查询
            history: 对话历史
            catalog: 工具技能目录
            
        Returns:
            (selected_items, primary_intent) 元组
            - selected_items: 选中的 tool/skill 名称列表
            - primary_intent: 最能代表用户核心意图的一项名称
        """
        select_start = time.time()
        
        # 生成简短目录
        brief_list = catalog.get_brief_list()
        
        # 构建历史
        history_str = self._format_history_for_prompt(history) if history else "No previous conversation"
        reply_language = self.cache.get("reply_language", "English")
        
        from datetime import datetime, timezone, timedelta
        tz_cst = timezone(timedelta(hours=8))
        now = datetime.now(tz_cst)
        current_time = now.strftime("%Y-%m-%d %H:%M:%S (%A)") + " (UTC+8)"
        
        # 渲染 Phase 1 prompt
        try:
            select_prompt = await mcp_client.get_prompt(
                name="select_tools_prompt",
                data={
                    "current_time": current_time,
                    "reply_language": reply_language,
                    "catalog_brief": brief_list,
                    "user_query": query,
                    "history": history_str,
                    "supported_languages": ", ".join(ENGLISH_NAME_TO_CODE_MAP.keys()),
                },
            )
        except Exception:
            select_prompt = jinja_render(
                "select_tools_prompt",
                data={
                    "current_time": current_time,
                    "reply_language": reply_language,
                    "catalog_brief": brief_list,
                    "user_query": query,
                    "history": history_str,
                    "supported_languages": ", ".join(ENGLISH_NAME_TO_CODE_MAP.keys()),
                },
            )
        
        logger.info(f"[Phase1-Select] ========== Phase 1 Input ==========")
        logger.info(f"[Phase1-Select] System Prompt ({len(select_prompt)} chars):\n{select_prompt}")
        logger.info(f"[Phase1-Select] User Query: {query}")
        logger.info(f"[Phase1-Select] ====================================")
        
        # 调用 LLM (非流式，因为输出很短)
        from llm.llm import qwen_extra_body
        extra_body = qwen_extra_body(self.model_name or "", enable_thinking=False)
        
        full_content = ""
        async for chunk in stream_llm(
            client=self.llm,
            messages=[
                {"role": "system", "content": select_prompt},
                {"role": "user", "content": query},
            ],
            model=self.model_name,
            temperature=0.1,
            max_tokens=200,  # 选择列表很短
            timeout=30,
            extra_body=extra_body,
        ):
            full_content += chunk
        
        elapsed = int((time.time() - select_start) * 1000)
        logger.info(f"[Phase1-Select] ========== Phase 1 Output ==========")
        logger.info(f"[Phase1-Select] LLM raw response ({elapsed}ms, {len(full_content)} chars):\n{full_content.strip()}")
        logger.info(f"[Phase1-Select] =====================================")
        
        # 解析 JSON — 支持新格式 {"selected": [...], "primary_intent": "...", "detect_language": "..."} 和旧格式 [...]
        primary_intent = ""
        detected_language = ""
        try:
            parsed = json.loads(full_content.strip())
            if isinstance(parsed, dict):
                # 新格式: {"selected": [...], "primary_intent": "...", "detect_language": "..."}
                selected = parsed.get("selected", [])
                primary_intent = parsed.get("primary_intent", "")
                detected_language = parsed.get("detect_language", "")
                if not isinstance(selected, list):
                    selected = [selected]
            elif isinstance(parsed, list):
                # 旧格式兼容: [...]
                selected = parsed
            else:
                selected = [parsed]
        except json.JSONDecodeError:
            try:
                parsed = json_repair.loads(full_content.strip())
                if isinstance(parsed, dict):
                    selected = parsed.get("selected", [])
                    primary_intent = parsed.get("primary_intent", "")
                    detected_language = parsed.get("detect_language", "")
                    if not isinstance(selected, list):
                        selected = [selected]
                elif isinstance(parsed, list):
                    selected = parsed
                else:
                    selected = [parsed]
            except Exception:
                logger.warning(f"[Phase1-Select] Failed to parse selection, using all tools")
                selected = catalog.all_names
        
        # ---- 语种检测：直接使用 Phase 1 LLM 识别的 detect_language ----
        if detected_language:
            reply_language = detected_language
            self.cache.update({"reply_language": reply_language})
            logger.info(f"[Phase1-Select] Language detected: '{detected_language}'")
        else:
            fallback_lang = LANGUAGE_CODE_TO_NAME_MAP.get(self.system_lang_code, ("English",))[0]
            self.cache.update({"reply_language": fallback_lang})
            logger.info(f"[Phase1-Select] No detect_language from LLM, fallback to system_lang_code: '{fallback_lang}'")
        
        # 验证名称有效性
        valid = [n for n in selected if catalog.get_item(n)]
        invalid = [n for n in selected if not catalog.get_item(n)]
        if invalid:
            logger.warning(f"[Phase1-Select] Unknown items: {invalid}")
        
        # 验证 primary_intent 有效性
        if primary_intent and primary_intent not in valid:
            logger.warning(f"[Phase1-Select] primary_intent '{primary_intent}' not in valid items, will auto-derive")
            primary_intent = ""
        
        # 自动推导 primary_intent（如果 LLM 未返回或无效）
        if not primary_intent and valid:
            # 优先级: skill > 工具专用模板 > 第一个
            for name in valid:
                item = catalog.get_item(name)
                if item and item.kind == "skill":
                    primary_intent = name
                    break
            if not primary_intent:
                for name in valid:
                    item = catalog.get_item(name)
                    if item and item.response_prompt_name:
                        primary_intent = name
                        break
            if not primary_intent:
                primary_intent = valid[0]
        
        logger.info(f"[Phase1-Select] Selected {len(valid)} items in {elapsed}ms: {valid}, primary_intent={primary_intent}")
        
        # 兜底：Phase 1 未能选出有效的工具时，默认使用 web_search
        if not valid:
            default_tool = "web_search"
            if catalog.get_item(default_tool):
                logger.warning(f"[Phase1-Select] No valid selection, fallback to '{default_tool}'")
                valid = [default_tool]
                primary_intent = default_tool
            else:
                # web_search 也不在 catalog 中，使用全部工具
                logger.warning(f"[Phase1-Select] No valid selection, fallback to all items")
                valid = catalog.all_names
                primary_intent = valid[0] if valid else ""
        
        return valid, primary_intent

    # ================================================================
    # Phase 2: 规划阶段 (改造自原 _plan_dag)
    # ================================================================

    async def _plan_dag(self, query: str, history: List, iteration: int = 1,
                        selected_items: Optional[List[str]] = None) -> Optional[DAGPlan]:
        """
        Phase 2: 让 LLM 流式生成 DAG 执行计划，并通过回调实时通知前端
        
        只加载 selected_items 中的工具/技能完整详情，而非全部工具。
        如果 selected_items 为 None，则回退为加载全部工具（兼容旧逻辑）。
        
        Args:
            query: 用户查询
            history: 对话历史
            iteration: 当前迭代次数
            selected_items: Phase 1 选中的 tool/skill 名称列表
            
        Returns:
            DAGPlan 或 None（如果解析失败）
        """
        logger.info(f"[DAG-Plan] Iteration {iteration} - Planning for query: {query[:100]}")
        plan_start_time = time.time()
        
        # 构建 messages
        messages = []
        
        history_source = "none"
        history_str = "No previous conversation"

        # 添加历史消息（短期记忆）
        if history:
            context_payload = await self._prepare_context(
                history=history,
                history_turns=6,
                current_query_tokens=estimate_tokens(query or ""),
            )
            history_messages = context_payload.get("messages", [])
            history_source = context_payload.get("source", "legacy")
            history_str = context_payload.get("prompt_string") or "No previous conversation"
            # Guardrail: avoid duplicate history injection.
            # _plan_dag already injects history via system prompt variable `history`,
            # so here we only append history messages when prompt_string is unavailable.
            if not history_str and history_messages:
                messages.extend(history_messages)
        
        # 添加当前query
        messages.append({"role": "user", "content": query})
        
        # 构建可用工具描述 —— 按需加载
        if selected_items and hasattr(self, '_catalog') and self._catalog:
            # Phase 2: 只加载选中的工具/技能完整详情
            available_tools_str = self._catalog.get_detail(selected_items)
            logger.info(f"[DAG-Plan] Phase 2 loaded detail for {len(selected_items)} items: {selected_items}")
        else:
            # 回退: 加载全部工具（兼容没有 catalog 的场景）
            available_tools_str = self._build_full_tools_description()
            logger.info(f"[DAG-Plan] Fallback: loaded all tools description")
        
        # 获取 plan prompt
        from datetime import datetime, timezone, timedelta
        tz_cst = timezone(timedelta(hours=8))
        now = datetime.now(tz_cst)
        current_time = now.strftime("%Y-%m-%d %H:%M:%S (%A)") + " (UTC+8)"
        reply_language = self.cache.get("reply_language", "English")
        
        # 调试日志：记录历史数据
        logger.info(f"[DAG-Plan] History records count: {len(history) if history else 0}")
        logger.info(f"[DAG-Plan] Formatted history length: {len(history_str)} chars")
        logger.info(f"[DAG-Plan] Context source: {history_source}")
        if history:
            logger.info(f"[DAG-Plan] History preview: {history_str[:200]}...")
        
        try:
            system_prompt = await mcp_client.get_prompt(
                name="plan_dag_prompt",
                data={
                    "current_time": current_time,
                    "current_year": now.year,
                    "reply_language": reply_language,
                    "available_tools": available_tools_str,
                    "user_query": query,
                    "history": history_str
                },
            )
        except Exception:
            # Fallback to local template
            system_prompt = jinja_render(
                "plan_dag_prompt",
                data={
                    "current_time": current_time,
                    "current_year": now.year,
                    "reply_language": reply_language,
                    "available_tools": available_tools_str,
                    "user_query": query,
                    "history": history_str
                },
            )
        
        # 调用 LLM 流式生成 DAG plan
        try:
            logger.info(f"[DAG-Plan] ========== System Prompt (Iteration {iteration}) ==========")
            logger.info(f"[DAG-Plan] Prompt length: {len(system_prompt)} chars")
            logger.info(f"[DAG-Plan] System Prompt (first 5000 chars):\n{system_prompt[:5000]}...\n")
            logger.info(f"[DAG-Plan] =========================================================")
            logger.info(f"[DAG-Plan] Calling LLM (streaming) to generate DAG plan...")
            llm_start = time.time()
            
            from llm.llm import qwen_extra_body
            extra_body = qwen_extra_body(self.model_name or "", enable_thinking=False)
            
            # 流式收集 LLM 输出，同时动态解析 task 节点
            full_content = ""
            notified_tasks = set()  # 已通知前端的 task id
            
            async for chunk in stream_llm(
                client=self.llm,
                messages=[
                    {"role": "system", "content": system_prompt},
                    *messages
                ],
                model=self.model_name,
                temperature=0.1,
                max_tokens=10000,
                timeout=90.0,
                extra_body=extra_body,
            ):
                full_content += chunk
                
                # 动态解析：尝试从已收集的内容中提取 task 信息
                new_tasks = self._extract_tasks_incrementally(full_content, notified_tasks)
                for task_info in new_tasks:
                    notified_tasks.add(task_info["id"])
                    # 通过 _plan_stream_callback 通知前端
                    if hasattr(self, '_plan_stream_callback') and self._plan_stream_callback:
                        await self._plan_stream_callback(
                            "task_planned",
                            task_id=task_info["id"],
                            task_name=task_info["name"],
                            tool=task_info["tool"],
                            index=len(notified_tasks),
                        )
            
            llm_elapsed = int((time.time() - llm_start) * 1000)
            logger.info(f"[DAG-Plan] LLM streaming completed in {llm_elapsed}ms, {llm_elapsed/1000:.2f}s")
            
            plan_json_str = full_content.strip()
            
            # 检测并移除思考标签（兜底）— 兼容 Qwen3 (<think>...</think>) 与 Qwen3.5 (仅 </think>)
            plan_json_str, stripped = strip_think_content(plan_json_str)
            if stripped:
                logger.info(f"[DAG-Plan] ⚠️ Detected think tag, extracted JSON content")

            "<think> in plan_json_str and </think>"
            " in plan_json_str and </think>"
            
            # 打印Plan JSON
            logger.info(f"[DAG-Plan] ========== LLM Generated Plan (Iteration {iteration}) ==========")
            logger.info(f"[DAG-Plan] JSON length: {len(plan_json_str)} chars")
            if len(plan_json_str) <= 2000:
                logger.info(f"[DAG-Plan] Full JSON:\n{plan_json_str}")
            else:
                logger.info(f"[DAG-Plan] Full JSON:\n{plan_json_str}")
            
            logger.info(f"[DAG-Plan] =========================================================")
            
            # 解析 JSON
            try:
                plan_dict = json.loads(plan_json_str)
                logger.info(f"[DAG-Plan] ✅ JSON parsed successfully")
            except json.JSONDecodeError as e:
                logger.warning(f"[DAG-Plan] ⚠️ JSON parsing failed: {e}, trying json_repair")
                plan_dict = json_repair.loads(plan_json_str)
                logger.info(f"[DAG-Plan] ✅ JSON repaired and parsed")
            
            # 构建 DAGPlan
            tasks = [DAGTask(**task) for task in plan_dict.get("tasks", [])]
            plan = DAGPlan(
                dag_id=f"dag_iter_{iteration}",  # 自动生成，不依赖LLM输出
                description=plan_dict.get("description", ""),
                tasks=tasks,
                max_parallel=plan_dict.get("max_parallel", 10)  # 使用默认值10
            )
            
            # 验证 DAG
            is_valid, error_msg = DAGExecutor.validate_dag(plan)
            if not is_valid:
                logger.error(f"[DAG-Plan] ❌ Invalid DAG: {error_msg}")
                return None
            
            # 打印DAG结构信息
            plan_total_elapsed = int((time.time() - plan_start_time) * 1000)
            logger.info(f"[DAG-Plan] ✅ Generated valid DAG with {len(tasks)} tasks")
            logger.info(f"[DAG-Plan] Total planning time: {plan_total_elapsed}ms (LLM: {llm_elapsed}ms)")
            logger.info(f"[DAG-Plan] DAG ID: {plan.dag_id}")
            logger.info(f"[DAG-Plan] Description: {plan.description}")
            logger.info(f"[DAG-Plan] Max Parallel: {plan.max_parallel}")
            logger.info(f"[DAG-Plan] Tasks structure:")
            for task in tasks:
                deps_str = f"depends_on={task.depends_on}" if task.depends_on else "[no dependencies]"
                logger.info(f"[DAG-Plan]   - {task.id}: {task.name} (tool={task.tool}, {deps_str})")

            self.cache["plan"] = plan
            return plan
            
        except Exception as e:
            logger.exception(f"[DAG-Plan] Failed to generate plan: {e}")
            _dr_task = DAGTask(
                id="task_1", name="Direct response", tool="direct_response",
                output_key="direct_response_output",
                status=TaskStatus.COMPLETED
            )
            self.cache["plan"] = DAGPlan(
                dag_id="direct_response", description="direct response",
                tasks=[_dr_task],
            )
            return None
    
    @staticmethod
    def _extract_tasks_incrementally(partial_json: str, already_notified: set) -> List[Dict]:
        """
        从不完整的 JSON 流中增量提取已完成的 task 节点
        
        使用正则匹配已经完整输出的 task 对象，避免解析不完整 JSON 异常。
        每个 task 至少需要 id、name、tool 三个字段才算有效。
        字段顺序不固定，兼容 LLM 输出的各种排列。
        
        Args:
            partial_json: 当前已收集的 JSON 字符串（可能不完整）
            already_notified: 已经通知过的 task id 集合
            
        Returns:
            新发现的 task 信息列表
        """
        import re
        new_tasks = []

        _field_re = re.compile(r'"(id|name|tool)"\s*:\s*"([^"]+)"')
        # Match {...} blocks allowing one level of nested braces (e.g. "arguments": {})
        _block_re = re.compile(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', re.DOTALL)

        for block_match in _block_re.finditer(partial_json):
            block = block_match.group()
            fields = {k: v for k, v in _field_re.findall(block)}
            task_id = fields.get("id")
            task_name = fields.get("name")
            tool = fields.get("tool")
            if task_id and task_name and tool and task_id not in already_notified:
                new_tasks.append({
                    "id": task_id,
                    "name": task_name,
                    "tool": tool,
                })

        return new_tasks
    
    def _build_dag_tool_registry(self):
        """
        为 DAG 执行构建包含个体工具的 ToolRegistry。
        
        DAGExecutor 按工具名（如 web_search）查找工具，但 Gateway 可能注入了
        "primitive" 注册表（仅含 MCPExecuteTool 统一调度器）。此方法确保
        DAG 执行始终拥有个体工具注册表。
        
        策略：
        1. 如果当前 tool_registry 已包含 DAG 计划中工具名 → 直接复用
        2. 否则从 _tools_info 重建 full registry
        3. 兜底返回当前 tool_registry
        """
        from agent.tools import ToolRegistry, MCPToolAdapter
        from agent.tools.base import DirectResponseTool
        from agent.plan.tool_policy import ToolPolicy, get_allowed_tool_set
        from agent.tools.valuescan_open_api import ValueScanOpenAPITool
        from agent.tools.kucoin_openapi_public import KucoinOpenApiPublicTool
        from agent.tools.trading_decision import TradingDecisionTool
        from agent.tools.dexscan_open_api import DexScanOpenAPITool

        current_registry = self.tool_registry
        _allowed = get_allowed_tool_set()

        # 检查当前 registry 是否已含有个体 MCP 工具
        if self._tools_info:
            sample_tools = getattr(self._tools_info, 'tools', [])
            if sample_tools:
                sample_name = sample_tools[0].name if hasattr(sample_tools[0], 'name') else None
                if sample_name and not current_registry.get_tool(sample_name):
                    # 当前 registry 缺少个体工具 → 重建
                    dag_registry = ToolRegistry()
                    _names = ToolPolicy._extract_tool_names(self._tools_info)
                    if _allowed is None:
                        MCPToolAdapter.register_all(dag_registry, self._tools_info, retries=1)
                    else:
                        _exclude = [n for n in _names if n not in _allowed]
                        MCPToolAdapter.register_all(
                            dag_registry, self._tools_info, retries=1, exclude=_exclude
                        )
                    if _allowed is None or "valueScan_api" in _allowed:
                        dag_registry.register(ValueScanOpenAPITool())
                    if _allowed is None or "dexScan_api" in _allowed:
                        dag_registry.register(DexScanOpenAPITool())
                    if _allowed is None or "kucoin_openapi_public" in _allowed:
                        dag_registry.register(KucoinOpenApiPublicTool())
                    if _allowed is None or "trading_decision" in _allowed:
                        dag_registry.register(TradingDecisionTool())
                    dag_registry.register(DirectResponseTool())
                    logger.info(
                        f"[DAG-Execute] Rebuilt full tool registry for DAG execution: "
                        f"{dag_registry.tool_count} tools: {dag_registry.tool_names}"
                    )
                    return dag_registry

        return current_registry

    async def _execute_dag_with_streaming(
        self,
        plan: DAGPlan,
        iteration: int = 1
    ):
        """
        执行 DAG 计划并流式输出结果（不含 TOOL_EXECUTION 开始/结束包装）
        
        由外层 _run_dag_pipeline 统一管理 TOOL_EXECUTION step 的生命周期。
        
        Args:
            plan: DAG 执行计划
            iteration: 当前迭代次数
            
        Yields:
            StreamResponse JSON strings
        """
        logger.info(f"[DAG-Execute] Iteration {iteration} - Executing DAG: {plan.dag_id}")
        session_id = self.session.id if self.session else ""
        qa_id = self.qa.id if self.qa else ""
        
        # DAG 执行需要按工具名查找个体工具（如 web_search），
        # 但 Gateway 可能注入了 "primitive" 注册表（只含统一调度器 MCPExecuteTool）。
        # 因此这里从 _tools_info 构建包含个体工具的 full registry。
        dag_tool_registry = self._build_dag_tool_registry()

        # 创建 DAG 执行器（带流式回调 + 关键任务重试）
        try:
            from agent.thinking_quality import ThinkingQualityConfig
            _tq = ThinkingQualityConfig.from_config(config)
            _crit_retries = _tq.critical_task_max_retries if _tq.enable_criticality_gating else 0
            _crit_delay = _tq.critical_task_retry_delay_s
        except Exception:
            _crit_retries, _crit_delay = 0, 0.5

        executor = DAGExecutor(
            tool_registry=dag_tool_registry,
            max_parallel=plan.max_parallel,
            critical_max_retries=_crit_retries,
            critical_retry_delay=_crit_delay,
        )

        # ---- 执行前注入工具专属参数 ----
        # DAGExecutor 不经过 task_graph.ToolAwareRunner，需要在这里统一注入
        reply_language = self.cache.get("reply_language", "English")
        user_id = self.user_id or "Unknown"
        from libs.language import (
            ENGLISH_NAME_TO_CODE_LOCAL_MAP as _LOCAL_MAP,
            KB_SEARCH_ENGLISH_NAME_TO_CODE_MAP as _KB_MAP,
        )
        for _task in plan.tasks:
            _args = _task.arguments
            _tool = (_task.tool or "").lower()
            # 通用：强制注入真实 user_id，覆盖模型可能生成的 mock 值。
            # 源头：DAG 规划 LLM 或工具调用 LLM 根据 MCP schema 生成 arguments 时，schema 中
            # 若含 userId 参数，LLM 无法获取请求层真实用户身份，会填占位符（如 user_12345）。
            # 此处必须强制覆盖，确保 downstream MCP 调用使用真实 user_id（来自 X-USER-ID 请求头）。
            _args["user_id"] = user_id
            _args["userId"] = user_id
            # 工具专属
            if _tool == "recharge_and_withdraw":
                _args.pop("detect_language", None)
                _args["lang"] = _LOCAL_MAP.get(reply_language, "en_US")
            elif _tool == "kb_search":
                # target_language 对 LLM 可见（不在 INJECTED_PARAMS），LLM 可能已正确填写，仅做 fallback
                # target_language在灵库描述没有针对的描述，LLM可能不清楚这个参数的作用，因此在这里注入一个合理的默认值，确保工具调用时有语言环境信息。
                _args["target_language"] = _KB_MAP.get(reply_language, "en")
            elif _tool == "customer_service_kb_search":
                _args["detect_language"] = _LOCAL_MAP.get(reply_language, "en_US")
        # ---- 注入完毕 ----

        # 任务进度回调 → 实时推送到前端 CONTENT（按 layer 分组，结构清晰）
        async def task_progress_callback(
            event_type: str, task_id: str, task_name: str, **kwargs
        ):
            tool_display = ""
            if task_id:
                task = next((t for t in plan.tasks if t.id == task_id), None)
                if task:
                    reply_language = self.cache.get("reply_language")
                    lang_code = ENGLISH_NAME_TO_CODE_MAP.get(reply_language, self.system_lang_code or "en")
                    tool_display = get_localized_message(task.tool, lang_code) or task.tool
            
            if event_type == "layer_start":
                layer = kwargs.get("layer", 0)
                task_count = kwargs.get("task_count", 0)
                parallel_hint = "parallel" if task_count > 1 else ""
                content = f"\n Layer {layer}: {parallel_hint} executing {task_count} tasks\n"
            elif event_type == "task_start":
                content = f"   {tool_display}: {task_name}\n"
            elif event_type == "task_complete":
                elapsed = kwargs.get("elapsed_ms", 0)
                content = f"   {tool_display}: {task_name} ({elapsed/1000:.2f}s)\n"
            elif event_type == "task_failed":
                error = kwargs.get("error", "")
                content = f" will retry {tool_display}: {task_name}\n"
            elif event_type == "layer_complete":
                layer = kwargs.get("layer", 0)
                elapsed = kwargs.get("elapsed_ms", 0)
                content = f"   Layer {layer} completed in {elapsed/1000:.2f}s\n"
            else:
                return
            
            yield StreamResponse(
                sessionId=session_id, qaId=qa_id,
                status=StreamStatusType.PENDING,
                type=StepType.CONTENT,
                content=content,
                checkSensitive=False,
            ).model_dump_json(exclude={"save", "deliver"})
        
        # 执行 DAG（带进度回调）
        start_time = time.time()
        async for progress_event in executor.execute_with_progress(plan, task_progress_callback):
            if progress_event:
                yield progress_event
        
        # 获取最终结果
        result = executor.get_last_result()
        elapsed_ms = int((time.time() - start_time) * 1000)
        
        # 保存结果到cache
        dag_results_key = f"dag_iteration_{iteration}"
        self.cache[dag_results_key] = {
            "plan": plan.model_dump(),
            "result": result.model_dump(),
            "elapsed_ms": elapsed_ms
        }
        
        # 合并所有工具结果
        tools_info = {}
        all_tool_results = []
        for task_id in result.completed_tasks:
            task = next((t for t in plan.tasks if t.id == task_id), None)
            if task and task.output_key in result.context:
                task_result = result.context[task.output_key]
                if isinstance(task_result, dict) and task_result.get("success"):
                    all_tool_results.append({
                        "task_id": task_id,
                        "task_name": task.name,
                        "tool": task.tool,
                        "text": task_result.get("content", ""),
                        "data": task_result.get("data"),
                        "metadata": task_result.get("metadata", {}),
                    })
                    value = tools_info.get(task.tool, "")
                    if value:
                        value += f"\n{task_result.get('content', '')}"
                        tools_info[task.tool] = value
                    else:
                        tools_info[task.tool] = task_result.get('content', '')

        # 保存到主cache（用于后续回复生成）
        self.cache.setdefault("tools_result", []).extend(all_tool_results)
        self.cache["tools_info"] = tools_info
        
        # 推送执行汇总
        success_count = len(result.completed_tasks)
        fail_count = len(result.failed_tasks)
        total = len(plan.tasks)
        if fail_count > 0:
            summary = f" {success_count}/{total} done,  {fail_count} failed, ⏱ {elapsed_ms/1000:.2f}s\n"
        else:
            summary = f" {success_count}/{total} done, ⏱ {elapsed_ms/1000:.2f}s\n"
        yield StreamResponse(
            sessionId=session_id, qaId=qa_id,
            status=StreamStatusType.PENDING,
            type=StepType.CONTENT,
            content=summary,
            checkSensitive=False,
        ).model_dump_json(exclude={"save", "deliver"})
        
        logger.info(f"[DAG-Execute] Completed in {elapsed_ms/1000:.2f}s - Success: {success_count}/{total}, Failed: {fail_count}")
    
    async def _run_dag_pipeline(
        self,
        user_query: str,
        max_iterations: int = 3,
        enable_think: bool = False,
        skip_analyz_query: bool = False,
        **kwargs,
    ):
        """
        完整的 DAG Pipeline（两阶段按需加载）
        
        流程：
        1. 分析问句（可跳过，如 DeepThinkAgent 已执行）
        2. 获取历史
        3. 初始化 Catalog（MCP 工具 + YAML 技能）
        4. Phase 1: LLM 从简短目录中选择需要的 tool/skill
        5. Phase 2: 只加载选中项的详情，生成 DAG Plan
        6. Execute DAG（最多 max_iterations 次）
        7. 生成最终回复
        8. 引用、币种提取、推荐问句
        
        Args:
            user_query: 用户查询
            max_iterations: 最大规划执行次数（默认3次）
            skip_analyz_query: 为 True 时跳过 _analyz_query（供 DeepThink 等已执行过分析问句的 Agent 使用）
            **kwargs: 其他参数
        """
        # 1、分析问句（可跳过，如 DeepThinkAgent 已执行）
        catalog_task = asyncio.create_task(self._init_catalog())
        history_task = asyncio.create_task(self._get_history(self.session_id, self.user_id))
        
        if not skip_analyz_query:
            async for event in self._analyz_query():
                yield event
        
        # 2、等待后台任务完成（通常已完成，因为 _analyz_query 很快）
        self.history = await history_task
        catalog = await catalog_task
        
        # 3、获取回复语言（写入 cache，供 Phase 1 prompt 读取，避免恒为 English）
        reply_language = self.cache.get("reply_language")
        if not reply_language:
            reply_language = LANGUAGE_CODE_TO_NAME_MAP.get(
                self.system_lang_code, ("English", "英语")
            )[0]
            self.cache["reply_language"] = reply_language
        reply_language_code = ENGLISH_NAME_TO_CODE_MAP.get(reply_language, self.system_lang_code or "en")
        if reply_language_code not in LANGUAGE_CODE_TO_NAME_MAP:
            reply_language_code = "en"
        self.cache["reply_language_code"] = reply_language_code
        # ============================================================
        # 开始工具执行 Step（前端展示为可折叠的工具调用卡片）
        # 整个 Phase 1 + Phase 2 + DAG Execute 都在这个 step 内
        # ============================================================
        session_id = self.session.id if self.session else ""
        qa_id = self.qa.id if self.qa else ""
        
        # TOOL_EXECUTION START
        yield StreamResponse(
            sessionId=session_id, qaId=qa_id,
            status=StreamStatusType.START,
            type=StepType.TOOL_EXECUTION,
        ).model_dump_json(exclude={"save", "deliver"})
        
        # 标题：搜寻关键信息（复用已有 i18n key）
        title = get_localized_message("calling_tools_start", reply_language_code)
        yield StreamResponse(
            sessionId=session_id, qaId=qa_id,
            status=StreamStatusType.PENDING,
            type=StepType.TITLE,
            content=title,
        ).model_dump_json(exclude={"save", "deliver"})
        
        # ---- Phase 1: 工具选择 ----
        # 检查是否通过 extraBody.skillName 显式指定了 skill
        explicit_skill_name = getattr(self.extra_body, 'skillName', None)
        if explicit_skill_name and explicit_skill_name in catalog.all_names:
            logger.info(f"[DAG-Pipeline] Explicit skillName specified: {explicit_skill_name}, skipping Phase 1 selection")
            selected_items = [explicit_skill_name]
            primary_intent = explicit_skill_name
        else:
            # 选择工具/技能（catalog 已在 step 1 并行加载完成）
            selected_items, primary_intent = await self._select_tools(user_query, self.history, catalog)
        
        # Phase 1 会通过 detect_language 更新 cache["reply_language"]，刷新本地变量
        reply_language = self.cache.get("reply_language", reply_language)
        
        # ---- direct_response 快速通道 ----
        # 选了 direct_response（可能还带其他工具）→ 只保留真实工具
        has_direct_response = "direct_response" in selected_items
        real_tools = [t for t in selected_items if t != "direct_response"]
        
        if has_direct_response and not real_tools:
            # 纯直接回复：跳过 TOOL_EXECUTION + Phase 2 + DAG 执行
            logger.info("[DAG-Pipeline] direct_response selected, skipping tool execution")

            # response_mixin 依赖 cache["plan"]，写入最小占位 plan
            if "plan" not in self.cache:
                _dr_task = DAGTask(
                    id="task_1", name="Direct response", tool="direct_response",
                    output_key="direct_response_output",
                    status=TaskStatus.COMPLETED
                )
                self.cache["plan"] = DAGPlan(
                    dag_id="direct_response", description="direct response",
                    tasks=[_dr_task],
                )

            # 关闭 TOOL_EXECUTION step（未产生实质内容，直接 END）
            title_correction = get_localized_message("calling_tools_end", reply_language_code)
            yield StreamResponse(
                sessionId=session_id, qaId=qa_id,
                status=StreamStatusType.PENDING,
                type=StepType.TITLE_CORRECTION,
                content=title_correction,
            ).model_dump_json(exclude={"save", "deliver"})
            yield StreamResponse(
                sessionId=session_id, qaId=qa_id,
                status=StreamStatusType.END,
                type=StepType.TOOL_EXECUTION,
            ).model_dump_json(exclude={"save", "deliver"})
            
            # 直接跳到最终回复（无工具结果）
            async for event in self._generate_final_response(
                user_query, [], self.history, reply_language,
                enable_think=enable_think,
            ):
                yield event
            
            # 后续步骤
            async for event in self._generate_final_citations(self.cache.get("full_response", "")):
                yield event
            async for event in self._extract_currency_suggestions(self.cache.get("full_response", "")):
                yield event
            async for event in self._generate_follow_up_questions(user_query, self.history, reply_language):
                yield event
            return
        
        # 有 direct_response + 其他真实工具 → 忽略 direct_response，只保留真实工具
        if has_direct_response and real_tools:
            logger.info(f"[DAG-Pipeline] direct_response ignored, using real tools: {real_tools}")
            selected_items = real_tools
            # primary_intent 如果是 direct_response 则重新推导
            if primary_intent == "direct_response":
                primary_intent = real_tools[0]
        
        # 确定最终回复使用的 prompt 名称
        # 优先级: primary_intent 对应的 prompt > skill 专用 prompt（非混合查询） > 通用
        response_prompt_name = None

        # 1. 优先使用 primary_intent 对应的 response_prompt
        if primary_intent:
            intent_item = catalog.get_item(primary_intent)
            if intent_item and intent_item.response_prompt_name:
                # 如果 primary_intent 是 skill，检查是否为混合查询
                if intent_item.kind == "skill":
                    skill_sub_tools = set(intent_item.sub_tools or [])
                    other_items = [n for n in selected_items if n != primary_intent]
                    non_skill_items = [n for n in other_items if n not in skill_sub_tools]
                    if not non_skill_items:
                        response_prompt_name = intent_item.response_prompt_name
                        logger.info(f"[DAG-Pipeline] primary_intent skill '{primary_intent}' -> response prompt: {response_prompt_name}")
                    else:
                        logger.info(
                            f"[DAG-Pipeline] Skill '{primary_intent}' has response prompt "
                            f"but mixed with other tools {non_skill_items}, using default final_response_prompt"
                        )
                else:
                    # tool 类型直接使用
                    response_prompt_name = intent_item.response_prompt_name
                    logger.info(f"[DAG-Pipeline] primary_intent tool '{primary_intent}' -> response prompt: {response_prompt_name}")
        
        if response_prompt_name:
            self.cache["dag_response_prompt_name"] = response_prompt_name
        
        # 保存 primary_intent 到 cache，供 _generate_final_response 使用
        self.cache["dag_primary_intent"] = primary_intent
        logger.info(f"[DAG-Pipeline] primary_intent={primary_intent}, response_prompt={response_prompt_name or 'final_response_prompt'}")
        reply_language = self.cache.get("reply_language")
        reply_language_code = ENGLISH_NAME_TO_CODE_MAP.get(reply_language, self.system_lang_code or "en")
        # Phase 1 选完 → 立即推送选中的工具名到前端（消除等待感）
        selected_display_parts = []
        for name in selected_items:
            display = get_localized_message(name, reply_language_code) or name
            selected_display_parts.append(display)
        if selected_display_parts:
            yield StreamResponse(
                sessionId=session_id, qaId=qa_id,
                status=StreamStatusType.PENDING,
                type=StepType.CONTENT,
                content=" · ".join(selected_display_parts) + "\n",
                checkSensitive=False,
            ).model_dump_json(exclude={"save", "deliver"})
        
        # ---- Phase 2 + Execute: 规划和执行 ----
        current_query = user_query
        for iteration in range(1, max_iterations + 1):
            logger.info(f"[DAG-Pipeline] Starting iteration {iteration}/{max_iterations}")
            
            # ---- Phase 2: 规划 DAG（实时推送发现的任务） ----
            planning_start_msg = get_localized_message("dag_planning_start", reply_language_code) or "Kia is planning tasks for you, this might take a few moments..."
            yield StreamResponse(
                sessionId=session_id, qaId=qa_id,
                status=StreamStatusType.PENDING,
                type=StepType.CONTENT,
                content=f"\n {planning_start_msg}\n",
                checkSensitive=False,
            ).model_dump_json(exclude={"save", "deliver"})
            
            # 用 Queue 实现规划期间的实时推送
            _plan_queue = asyncio.Queue()
            _PLAN_DONE = object()
            
            async def _on_task_discovered(event_type, **kwargs):
                """规划阶段增量回调：每发现一个 task 就推到 queue"""
                task_name = kwargs.get("task_name", "")
                tool = kwargs.get("tool", "")
                index = kwargs.get("index", 0)
                tool_display = get_localized_message(tool, reply_language_code) or tool
                task_prefix = get_localized_message("dag_task_prefix", reply_language_code, index=index) or f"Task {index}"
                await _plan_queue.put(f"   {task_prefix}: {tool_display} - {task_name}\n")
            
            self._plan_stream_callback = _on_task_discovered
            
            async def _do_plan():
                try:
                    return await self._plan_dag(
                        current_query, self.history, iteration,
                        selected_items=selected_items,
                    )
                except Exception as e:
                    logger.exception(f"[DAG-Pipeline] Plan task error: {e}")
                    return None
                finally:
                    await _plan_queue.put(_PLAN_DONE)
            
            plan_task = asyncio.create_task(_do_plan())
            
            # 边规划边推送（含心跳保活，防止前端/代理超时断连）
            while True:
                try:
                    item = await asyncio.wait_for(_plan_queue.get(), timeout=8.0)
                except asyncio.TimeoutError:
                    # 超过 8s 没有新任务发现 → 推送心跳
                    still_planning_msg = get_localized_message("dag_still_planning", reply_language_code) or "Still planning..."
                    yield StreamResponse(
                        sessionId=session_id, qaId=qa_id,
                        status=StreamStatusType.PENDING,
                        type=StepType.CONTENT,
                        content=f"  ⏳ {still_planning_msg}\n",
                        checkSensitive=False,
                    ).model_dump_json(exclude={"save", "deliver"})
                    continue
                if item is _PLAN_DONE:
                    break
                # 推送发现的任务
                yield StreamResponse(
                    sessionId=session_id, qaId=qa_id,
                    status=StreamStatusType.PENDING,
                    type=StepType.CONTENT,
                    content=item,
                    checkSensitive=False,
                ).model_dump_json(exclude={"save", "deliver"})
            
            plan = await plan_task
            
            if not plan:
                logger.warning(f"[DAG-Pipeline] Failed to generate plan at iteration {iteration}")
                break
            
            # --- 空 tasks 兜底：LLM 返回了 tasks=[] 时注入 direct_response ---
            if not plan.tasks:
                logger.warning("[DAG-Pipeline] LLM returned empty tasks, injecting direct_response fallback")
                plan.tasks = [
                    DAGTask(
                        id="task_1",
                        name="Direct response",
                        tool="direct_response",
                        arguments={},
                        depends_on=[],
                        output_key="direct_output",
                        status=TaskStatus.COMPLETED,
                    )
                ]
                self.cache["plan"] = plan

            
            # --- 节点关键性标注（纯拓扑分析，无 LLM 调用） ---
            try:
                from agent.thinking_quality import TaskCriticalityAnalyzer
                crit_map = TaskCriticalityAnalyzer.analyze(plan)
                for task in plan.tasks:
                    task.criticality = crit_map.get(task.id, "normal")
                crit_summary = {c: sum(1 for v in crit_map.values() if v == c) for c in ("critical", "normal", "low") if any(v == c for v in crit_map.values())}
                logger.info(f"[DAG-Pipeline] Criticality annotation: {crit_summary} | detail={crit_map}")
            except Exception as e:
                logger.warning(f"[DAG-Pipeline] Criticality annotation skipped: {e}")
            
            # 推送规划摘要
            task_count = len(plan.tasks)
            in_deg = {t.id: len(t.depends_on) for t in plan.tasks}
            layers = 0
            remaining = set(in_deg.keys())
            while remaining:
                layer_tasks = [tid for tid in remaining if in_deg[tid] == 0]
                if not layer_tasks:
                    break
                layers += 1
                for tid in layer_tasks:
                    remaining.discard(tid)
                    for t in plan.tasks:
                        if tid in t.depends_on:
                            in_deg[t.id] -= 1
            plan_summary = f"{task_count} tasks"
            if layers > 1:
                plan_summary += f", {layers} layers"
            yield StreamResponse(
                sessionId=session_id, qaId=qa_id,
                status=StreamStatusType.PENDING,
                type=StepType.CONTENT,
                content=plan_summary + "\n",
                checkSensitive=False,
            ).model_dump_json(exclude={"save", "deliver"})
            
            # 执行 DAG
            async for event in self._execute_dag_with_streaming(plan, iteration):
                yield event
            
            # 检查是否需要继续迭代
            dag_result = self.cache.get(f"dag_iteration_{iteration}", {}).get("result", {})
            failed_tasks = dag_result.get("failed_tasks", [])
            
            if not failed_tasks:
                logger.info(f"[DAG-Pipeline] All tasks succeeded, stopping at iteration {iteration}")
                break
            
            if iteration == max_iterations:
                logger.info(f"[DAG-Pipeline] Max iterations reached, stopping")
                break
            
            # ---- 失败任务 web_search 补救 ----
            # 提取失败任务的查询意图，用 web_search 代替
            failed_task_names = []
            for ftid in failed_tasks:
                ft = next((t for t in plan.tasks if t.id == ftid), None)
                if ft:
                    failed_task_names.append(ft.name)
            
            if failed_task_names and catalog.get_item("web_search"):
                logger.warning(f"[DAG-Pipeline] {len(failed_task_names)} tasks failed, retrying with web_search: {failed_task_names}")
                # 构造 web_search 补救 DAG：每个失败任务 → 一个 web_search task
                rescue_tasks = []
                for idx, name in enumerate(failed_task_names, 1):
                    rescue_tasks.append(DAGTask(
                        id=f"rescue_{idx}",
                        name=name,
                        tool="web_search",
                        arguments={"query": truncate_web_search_query(name)},
                        depends_on=[],
                        output_key=f"rescue_result_{idx}",
                    ))
                if rescue_tasks:
                    rescue_plan = DAGPlan(
                        dag_id=f"dag_rescue_{iteration}",
                        description=f"Web search fallback for {len(rescue_tasks)} failed tasks",
                        tasks=rescue_tasks,
                        max_parallel=plan.max_parallel,
                    )
                    # 推送补救提示
                    yield StreamResponse(
                        sessionId=session_id, qaId=qa_id,
                        status=StreamStatusType.PENDING,
                        type=StepType.CONTENT,
                        content=f"\n🔄 {len(rescue_tasks)} tasks failed, retrying with web search\n",
                        checkSensitive=False,
                    ).model_dump_json(exclude={"save", "deliver"})
                    # 执行补救 DAG
                    async for event in self._execute_dag_with_streaming(rescue_plan, iteration):
                        yield event
            
            # 不再继续迭代（补救已完成）
            break
        
        # ============================================================
        # 结束工具执行 Step
        # ============================================================
        title_correction = get_localized_message("calling_tools_end", reply_language_code)
        yield StreamResponse(
            sessionId=session_id, qaId=qa_id,
            status=StreamStatusType.PENDING,
            type=StepType.TITLE_CORRECTION,
            content=title_correction,
        ).model_dump_json(exclude={"save", "deliver"})
        
        yield StreamResponse(
            sessionId=session_id, qaId=qa_id,
            status=StreamStatusType.END,
            type=StepType.TOOL_EXECUTION,
        ).model_dump_json(exclude={"save", "deliver"})
        
        # 5、提取 KB_search / customer_service_kb_search 结果（与 skill-first 管道行为一致）
        tools_result = self.cache.get("tools_result", [])
        _kb_tools = {"kb_search", "customer_service_kb_search"}
        for tr in tools_result:
            _tr_tool = tr.get("tool", "")
            if _tr_tool.lower() in _kb_tools or _tr_tool in _kb_tools:
                try:
                    data_map = json.loads(tr.get("text", "{}"))
                    disable_llm = data_map.get("disable_llm", False)
                    # customer_service_kb_search 的 results 字段在 answer_response 中
                    results = data_map.get("results", [])
                    answer_response = data_map.get("answer_response", "")
                    if not results and answer_response:
                        results = [answer_response]
                    self.cache["kb_search_info"] = {
                        "disable_llm": disable_llm,
                        "results": results,
                    }
                    logger.info(
                        f"[DAG-Pipeline] {_tr_tool} disable_llm={disable_llm}, "
                        f"results_count={len(results)}, answer_len={len(answer_response)}"
                    )
                    # disable_llm=True 但结果为空 → 标记需要 web_search 兜底
                    if disable_llm and not results and not answer_response:
                        logger.warning(
                            f"[DAG-Pipeline] {_tr_tool} returned disable_llm=True but empty results, "
                            f"will fallback to web_search"
                        )
                        self.cache["_kb_empty_fallback"] = True
                except Exception as e:
                    logger.error(f"[DAG-Pipeline] {_tr_tool} parse error: {e}")
                break

        # 5.5、disable_llm=True 但结果为空时，fallback 到 web_search
        if self.cache.pop("_kb_empty_fallback", False):
            logger.warning("[DAG-Pipeline] KB tool returned empty, falling back to web_search")
            # 清空不可用的 KB 结果
            self.cache.pop("kb_search_info", None)
            self.cache.pop("tools_result", None)

            # 走统一降级路径: web_search → LLM → 后处理
            async for event in self._fallback_via_web_search(
                user_query, reply_language,
                enable_think=enable_think,
            ):
                yield event
            return

        # 后处理所有工具结果（URL风险过滤 + 引用表构建），与 skill-first 路径行为对齐
        await self._post_process_dag_tools()
        # 重新读取（可能被后处理更新）
        tools_result = self.cache.get("tools_result", [])

        # 5.6、为 DAG 路径生成 tool_call_id + cache["tool_name"]，与 skill-first 路径行为对齐
        # 使用 Phase 1 的 primary_intent 作为主导工具名，而非依赖 DAG 执行结果推测
        _dag_tool_call_id = f"call_{uuid.uuid4().hex[:24]}"
        _dag_tool_names = [r.get('tool', '') for r in tools_result if r.get('tool')]
        _dag_primary_intent = self.cache.get("dag_primary_intent", "")
        # primary_intent 优先；如果所有任务只用了同一工具则用该工具；否则标记为多工具
        _dag_primary_tool = _dag_primary_intent or (_dag_tool_names[0] if len(set(_dag_tool_names)) == 1 else "")
        self._tool_call = {
            "tool_call": {
                "name": _dag_primary_tool or "dag_multi_tool",
                "tool_call_id": _dag_tool_call_id,
            },
            "content": ""
        }
        # 设置 cache["tool_name"] 以便 _generate_final_response 正确触发
        # RESOURCE_REFERENCE / CustomTableStreamProcessor 等逻辑
        # 只在真正单工具时设置，多工具场景走 multi-tool 分支避免预处理破坏数据
        if _dag_primary_tool and len(set(_dag_tool_names)) <= 1:
            self.cache["tool_name"] = _dag_primary_tool

        # 特殊工具数据构建（coin_screener / recharge_and_withdraw），复用 base 共用方法
        # 同时收集 resource_references 供 response_mixin 渲染多卡片
        _plan_tasks = {task.id:task for task in self.cache["plan"].tasks}
        _card_refs: list[dict] = []
        for _r in tools_result:
            _t = _r.get('tool', '')
            # _task_id = _r.get('task_id', '')
            tool_call_id = _plan_tasks.get(_r["task_id"]).tool_call_id
            if _t == 'coin_screener' and _r.get('text'):
                self._build_coin_screener_data(_r['text'], reply_language)
                data = self.cache.get("recommend_crypto_table_data", {})
                if data:
                    self._append_card_ref(_card_refs, _t, tool_call_id, "CUSTOM_TABLE", "custom_table", data)

            elif _t == 'recharge_and_withdraw' and _r.get('text'):
                if _r.get("metadata", {}).get("graceful_fallback"):
                    continue
                card_data = self._build_recharge_withdraw_card_data_from_text(_r["text"])
                if card_data and card_data.get("paymentMethodList"):
                    self._append_card_ref(_card_refs, _t, tool_call_id, "CUSTOM_CARD", "custom_card", card_data)

            elif _t == 'recommend_financial_product' and _r.get('text'):
                await self._build_earn_product_data(_r['text'], reply_language)
                data = self.cache.get("recommend_earn_table_data", {})
                if data:
                    self._append_card_ref(_card_refs, _t, tool_call_id, "CUSTOM_TABLE", "custom_table", data)

        # 仅当存在唯一一张充值/提现卡片时写入 cache，供依赖该 key 的逻辑使用
        _recharge_refs = [c for c in _card_refs if c.get("tool_name") == "recharge_and_withdraw"]
        if len(_recharge_refs) == 1:
            self.cache["recharge_withdraw_card_data"] = _recharge_refs[0].get("data", {})

        if _card_refs:
            self.cache["resource_references"] = _card_refs
            first_card = _card_refs[0]
            self._tool_call = {
                "tool_call": {
                    "name": first_card["tool_name"],
                    "tool_call_id": first_card["tool_call_id"],
                },
                "content": "",
            }
            # Only use the card-specific prompt when it is the sole tool.
            # When multiple tools ran (card + non-card), keep tool_name empty
            # so response_mixin enters the DAG multi-tool path and uses
            # final_response_prompt for a comprehensive answer.
            _card_tool_names = {c["tool_name"] for c in _card_refs}
            _result_tool_names = set(_dag_tool_names)
            if _result_tool_names == _card_tool_names and len(_card_refs) == 1:
                self.cache["tool_name"] = first_card["tool_name"]

        logger.info(f"[DAG-Pipeline] Set tool_call_id={_dag_tool_call_id}, tool_name={self.cache.get('tool_name','')}, tools={_dag_tool_names}, cards={len(_card_refs)}")

        # 6、生成最终回复
        if tools_result:
            # 格式化为标准格式，保留 tool key 供 response_mixin 多工具分支使用
            formatted_results = [
                {"tool": result.get("tool", ""), "text": result.get("text", "")}
                for result in tools_result
            ]
            
            async for event in self._generate_final_response(
                user_query,
                formatted_results,
                self.history,
                reply_language,
                enable_think=enable_think,
            ):
                yield event
        else:
            # 没有工具结果，直接生成回复
            async for event in self._generate_final_response(
                user_query,
                [],
                self.history,
                reply_language,
                enable_think=enable_think,
            ):
                yield event
        
        # 6、引用
        async for event in self._generate_final_citations(self.cache.get("full_response", "")):
            yield event

        # 7、币种提取（以 plan 实际执行的 symbol 为来源，供「您可能对以下内容感兴趣」使用）
        if self.cache.get("dag_response_prompt_name") == "currency_comparison_synthesis_prompt":
            _plan = self.cache.get("plan")
            if _plan and _plan.tasks:
                _seen, _pairs = set(), []
                for _t in _plan.tasks:
                    for _k in ("symbol_list", "symbols", "symbol"):
                        _v = (_t.arguments or {}).get(_k)
                        if _v is None:
                            continue
                        for _s in (_v if isinstance(_v, list) else [_v]):
                            if not _s or not isinstance(_s, str):
                                continue
                            _b = _s.split("-")[0].split("/")[0].upper().strip()
                            if _b in crypto_extractor.crypto_symbols and _b not in _seen:
                                _seen.add(_b)
                                _pairs.append(f"{_b}-USDT" if "-" not in _s and "/" not in _s else _s.replace("/", "-"))
                if _pairs:
                    self.cache["currency_suggestions_symbols"] = crypto_extractor.adjust_crypto_list(_pairs)
                    logger.info(f"[DAG-Pipeline] currency_suggestions_symbols from plan: {self.cache['currency_suggestions_symbols']}")

        async for event in self._extract_currency_suggestions(self.cache.get("full_response", "")):
            yield event
        
        # 8、推荐问句
        async for event in self._generate_follow_up_questions(user_query, self.history, reply_language):
            yield event
    
    async def _post_process_dag_tools(self):
        """
        DAG 工具结果后处理，补齐 skill-first 路径中 _call_tools 承担的功能：
        
        1. web_search 结果 URL 风险前置过滤（与 _filter_risky_web_search_results 等价）
        2. 构建 search_id_to_url_map，供 _generate_final_response 的 citation 处理使用
        
        必须在 _generate_final_response 调用前执行。
        """
        tools_result = self.cache.get("tools_result", [])
        if not tools_result:
            return
        
        merged_url_map = {}
        url_idx = 1
        
        for result in tools_result:
            tool = result.get("tool", "")
            text = result.get("text", "")
            if not text:
                continue
            
            if tool == "web_search":
                try:
                    data = json.loads(text)
                    all_items = list(data.get("results", []))
                    
                    # ---- URL 风险前置过滤（对应 skill-first 的 _filter_risky_web_search_results） ----
                    from web.config import is_risk_control_enabled

                    url_risk_enable = is_risk_control_enabled() and getattr(config, 'url_risk_enable', True)
                    if url_risk_enable and all_items and hasattr(self, '_url_checker') and self._url_checker:
                        all_urls = [item.get("url", "") for item in all_items if item.get("url")]
                        if all_urls:
                            try:
                                url_check = await self._url_checker.check_urls(all_urls)
                                if url_check.has_risk:
                                    risky_domains = set()
                                    for url in url_check.risky_urls:
                                        domain = self._url_checker.extract_domain(url)
                                        if domain:
                                            risky_domains.add(domain)
                                    safe_items = [
                                        item for item in all_items
                                        if self._url_checker.extract_domain(item.get("url", "")) not in risky_domains
                                    ]
                                    logger.warning(
                                        f"[DAG post-process] web_search: filtered "
                                        f"{len(all_items) - len(safe_items)} risky URLs"
                                    )
                                    all_items = safe_items
                                    # 更新 cache 中的 text（让 LLM 只看到安全结果）
                                    data["results"] = all_items
                                    result["text"] = json.dumps(data, ensure_ascii=False)
                            except Exception as url_err:
                                logger.warning(f"[DAG post-process] URL check failed (non-fatal): {url_err}")
                    
                    # ---- 构建 search_id_to_url_map（对应 skill-first 的 _build_links_message） ----
                    for item in all_items:
                        url = item.get("url")
                        if url:
                            item["search_id"] = url_idx
                            merged_url_map[url_idx] = {
                                "index": url_idx,
                                "url": url,
                                "title": item.get("title", ""),
                            }
                            url_idx += 1

                    # 将注入 search_id 后的数据回写，让 LLM 看到带编号的结果
                    data["results"] = all_items
                    result["text"] = json.dumps(data, ensure_ascii=False)
                    result["data"] = data
                            
                except Exception as e:
                    logger.error(f"[DAG post-process] Failed to process web_search result: {e}")
        
        if merged_url_map:
            self.cache["search_id_to_url_map"] = merged_url_map
            logger.info(f"[DAG post-process] Built search_id_to_url_map: {len(merged_url_map)} URLs")

    def _format_history_for_prompt(self, history: List) -> str:
        """格式化历史记录为 Prompt 字符串"""
        if not history:
            return "No previous conversation"
        
        formatted = []
        for qa in history[-3:]:  # 只取最近3轮
            query = ""
            answer_content = ""
            
            if isinstance(qa, dict):
                query = qa.get("query", "")
                for step in qa.get("answer", []):
                    if step.get("type") == "ANSWER_RESPONSE":
                        answer_content = step.get("step", {}).get("CONTENT", "")
                        break
            else:
                # QAModel 对象 —— answer 是 List[StepModel]
                query = getattr(qa, "query", "")
                answer_list = getattr(qa, "answer", [])
                for step in answer_list:
                    # StepModel 对象: step.type 是 StepType 枚举, step.step 是 dict
                    step_type = str(getattr(step, "type", "")) if not isinstance(step, dict) else step.get("type", "")
                    if step_type == "ANSWER_RESPONSE":
                        step_data = getattr(step, "step", {}) if not isinstance(step, dict) else step.get("step", {})
                        answer_content = step_data.get("CONTENT", "") if isinstance(step_data, dict) else ""
                        break
            
            if query and answer_content:
                formatted.append(f"User: {query}")
                formatted.append(f"Assistant: {answer_content[:200]}")  # 截断过长内容
        
        return "\n".join(formatted) if formatted else "No previous conversation"

    def _build_full_tools_description(self) -> str:
        """
        构建全量工具描述（fallback，当没有 catalog 时使用）
        
        兼容原有逻辑，从 _tools_info.tools_name_map 构建完整描述。
        """
        from agent.catalog import INJECTED_PARAMS
        
        available_tools_list = []
        if self._tools_info and hasattr(self._tools_info, "tools_name_map"):
            tools_name_map = self._tools_info.tools_name_map
            for tool_name, tool_obj in tools_name_map.items():
                if isinstance(tool_obj, dict):
                    tool_desc = tool_obj.get("description") or "No description"
                    input_schema = tool_obj.get("inputSchema") or {}
                else:
                    tool_desc = tool_obj.description or "No description"
                    input_schema = tool_obj.inputSchema or {}
                
                properties = input_schema.get("properties", {})
                required_params = input_schema.get("required", [])
                
                params_info = []
                for param_name, param_details in properties.items():
                    if param_name in INJECTED_PARAMS:
                        continue
                    param_type = param_details.get("type", "any")
                    param_desc = param_details.get("description", "")
                    is_required = " (required)" if param_name in required_params else ""
                    params_info.append(f"    - {param_name} ({param_type}){is_required}: {param_desc}")
                
                tool_info = f"- {tool_name}: {tool_desc}"
                if params_info:
                    tool_info += "\n  Parameters:\n" + "\n".join(params_info)
                
                available_tools_list.append(tool_info)
        
        return "\n\n".join(available_tools_list) if available_tools_list else "No external tools available"


__all__ = ["DAGExecutionMixin"]
