# -*- coding: utf-8 -*-
"""
Tool & Skill Catalog - 两阶段按需加载

Phase 1 (选择阶段): 只给 LLM 看每个 tool/skill 的名称 + 简短摘要 (~3句话)
Phase 2 (规划阶段): 只加载被选中的 tool/skill 的完整描述 + 参数 schema

用法:
    catalog = ToolSkillCatalog()
    await catalog.load(tools_info)            # 从 MCP 加载工具元数据
    catalog.load_skills()                     # 从 YAML 加载技能配置

    # Phase 1: 选择
    brief = catalog.get_brief_list()          # 简短列表

    # Phase 2: 按需加载
    detail = catalog.get_detail(["search_crypto_news", "crypto_insight_skill"])
"""

import os
import re
import logging
from typing import Dict, List, Optional, Any, Set

import yaml

logger = logging.getLogger(__name__)

# 注入参数 —— to_openai_tools() 给所有工具注入的参数，DAG 模式不需要
INJECTED_PARAMS = {"detect_language"}

# Skills 配置目录
SKILLS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "conf", "skills")

# 工具摘要硬编码 —— 比自动提取更稳定、更简洁
TOOL_SUMMARIES: dict[str, str] = {
    "web_search": "Real-time web search. Retrieves up-to-date information, news, and factual data from the internet.",
    "recommend_financial_product": "Recommends suitable financial products by analyzing user risk profile, preferences, and market conditions.",
    "KB_search": "Searches KuCoin knowledge base for platform features, policies, tutorials, and factual non-real-time questions.",
    "customer_service_kb_search": "Specialized customer service knowledge base search with language mapping and customer-friendly formatting.",
    "get_crypto_investment_outlook": "Assesses investment potential of a cryptocurrency with outlook analysis across short/mid/long-term timeframes.",
    "recharge_and_withdraw": "Detects user intent to deposit or withdraw crypto and provides guided instructions with network/fee details.",
    "get_crypto_market_data": "KuCoin MCP technical indicators (RSI, MACD, etc.). For spot price and token fundamentals, prefer valueScan_api (token_detail / price_indicators) first.",
    "coin_screener": "Screens and recommends cryptocurrencies based on market conditions, categories, and user-specified filters.",
    "direct_response": "Directly respond without any external tool. ONLY for trivial chitchat (greetings, identity questions). Do NOT use for any query involving assets, markets, prices, analysis, weather, or factual data.",
    "kucoin_openapi_public": "Calls KuCoin public OpenAPI endpoints directly (GET only) for spot/futures market data.",
    "valueScan_api": "PRIMARY source for crypto spot price & on-chain/exchange data: use operation token_detail (symbol e.g. BTC) for price/mcap; price_indicators, realtime_fund, kline, support_resistance as needed. Prefer over get_crypto_market_data for price truthfulness.",
    "trading_decision": "End-to-end crypto trading decision tool. Use for buy/sell/hold, dry-run, execute=false, risk-controlled trading decisions, or scheduled trading analysis. It gathers KuCoin market/K-lines, optional RAG events/account data, calls the trading LLM prompt, applies RiskManager, and never trades live unless explicitly confirmed and live trading is enabled.",
    "dexScan_api": "DEX on-chain data: token price, K-line, stats, liquidity, market cap, risk labels, coin rankings, top holders, pools, trade records, social heat. For Solana meme coins and DEX-only tokens (BONK, WIF, JUP etc.), prefer this over valueScan_api.",
}

# 工具级别的回复模板映射 —— 当某工具作为 primary_intent 时使用对应的 prompt 模板
# skill 的 response_prompt_name 在 YAML 中定义，这里只配置 tool 级别的
TOOL_RESPONSE_PROMPTS: dict[str, str] = {
    "coin_screener": "coin_screener",
    "recharge_and_withdraw": "recharge_and_withdraw",
    "recommend_financial_product": "recommend_financial_product",
}


class CatalogItem:
    """统一的目录条目（tool 或 skill）"""

    __slots__ = ("name", "kind", "summary", "description", "parameters", "sub_tools", "response_prompt_name")

    def __init__(
        self,
        name: str,
        kind: str,            # "tool" 或 "skill"
        summary: str,         # Phase 1 用: 2-3 句话摘要
        description: str = "",     # Phase 2 用: 完整描述
        parameters: Optional[List[Dict[str, Any]]] = None,  # Phase 2 用: 参数列表
        sub_tools: Optional[List[str]] = None,               # skill 专用: 需要调用的工具列表
        response_prompt_name: str = "",                       # 回复使用的 MCP prompt 名称
    ):
        self.name = name
        self.kind = kind
        self.summary = summary
        self.description = description
        self.parameters = parameters or []
        self.sub_tools = sub_tools or []
        self.response_prompt_name = response_prompt_name


class ToolSkillCatalog:
    """
    工具与技能的统一目录

    职责:
    1. 维护所有 tool/skill 的元数据
    2. 提供 Phase 1 简短列表（用于 LLM 选择）
    3. 提供 Phase 2 按需详情（只加载需要的）
    """

    def __init__(self):
        self._items: Dict[str, CatalogItem] = {}

    # ================================================================
    # 加载
    # ================================================================

    def load_tools(self, tools_info) -> int:
        """
        从 MCP ToolsInfo 加载工具元数据

        Args:
            tools_info: mcp.types.ToolsInfo 对象

        Returns:
            加载的工具数量
        """
        if not tools_info or not hasattr(tools_info, "tools_name_map"):
            return 0

        count = 0
        tools_name_map = tools_info.tools_name_map
        for tool_name, tool_obj in tools_name_map.items():
            # 兼容 dict 和 Tool 对象
            if isinstance(tool_obj, dict):
                full_desc = tool_obj.get("description") or ""
                input_schema = tool_obj.get("inputSchema") or {}
            else:
                full_desc = tool_obj.description or ""
                input_schema = tool_obj.inputSchema or {}

            # 优先使用硬编码摘要，未知工具 fallback 到自动提取
            summary = TOOL_SUMMARIES.get(tool_name) or self._make_summary(full_desc)

            # 解析参数（过滤注入参数）
            params = self._parse_parameters(input_schema)

            self._items[tool_name] = CatalogItem(
                name=tool_name,
                kind="tool",
                summary=summary,
                description=full_desc,
                parameters=params,
                response_prompt_name=TOOL_RESPONSE_PROMPTS.get(tool_name, ""),
            )
            count += 1

        logger.info(f"[Catalog] Loaded {count} tools from MCP")
        return count

    def apply_tool_allowlist(self, allowed: Set[str]) -> None:
        """Remove catalog tools not in allowed (skills unchanged)."""
        if not allowed:
            return
        for name in list(self._items.keys()):
            item = self._items[name]
            if item.kind == "tool" and name not in allowed:
                del self._items[name]
                logger.info(f"[Catalog] Filtered tool (not in agent_allowed_tools): {name}")

    def load_skills(self) -> int:
        """
        从 conf/skills/ 目录加载 YAML 技能配置

        每个 YAML 文件定义一个 skill，格式:
            name: crypto_insight
            summary: "币种洞察分析..."
            description: "完整描述..."
            sub_tools:
              - get_crypto_investment_outlook
              - get_crypto_market_data
            response_prompt_name: currency_insight_synthesis_prompt

        Returns:
            加载的 skill 数量
        """
        if not os.path.isdir(SKILLS_DIR):
            logger.info(f"[Catalog] Skills dir not found: {SKILLS_DIR}, skipping")
            return 0

        from web.config import config as _cfg

        _allowed_skills = getattr(_cfg, "agent_allowed_skills", None) if _cfg else None
        if _allowed_skills:
            _allowed_skills = set(_allowed_skills)
        else:
            _allowed_skills = None

        count = 0
        for filename in sorted(os.listdir(SKILLS_DIR)):
            if not filename.endswith((".yaml", ".yml")):
                continue
            filepath = os.path.join(SKILLS_DIR, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    cfg = {}
                    for doc in yaml.safe_load_all(f):
                        if isinstance(doc, dict):
                            cfg.update(doc)
                if not cfg or not isinstance(cfg, dict):
                    continue

                name = cfg.get("name", "")
                if not name:
                    logger.warning(f"[Catalog] Skill file {filename} missing 'name', skipped")
                    continue

                if _allowed_skills is not None and name not in _allowed_skills:
                    logger.info(f"[Catalog] Skipped skill (not in agent_allowed_skills): {name}")
                    continue

                # 仅加载 dag_eligible != False 的 skill（crypto_insight 专属 currency_insight 工作流，不参与 DAG）
                if cfg.get("dag_eligible", True) is False:
                    logger.info(f"[Catalog] Skipped skill (dag_eligible=false): {name}")
                    continue

                self._items[name] = CatalogItem(
                    name=name,
                    kind="skill",
                    summary=cfg.get("summary", ""),
                    description=cfg.get("description", ""),
                    parameters=cfg.get("parameters", []),
                    sub_tools=cfg.get("sub_tools", []),
                    response_prompt_name=cfg.get("response_prompt_name", ""),
                )
                count += 1
                logger.info(f"[Catalog] Loaded skill: {name} (sub_tools={cfg.get('sub_tools', [])})")
            except Exception as e:
                logger.warning(f"[Catalog] Failed to load skill {filename}: {e}")

        logger.info(f"[Catalog] Loaded {count} skills from {SKILLS_DIR}")
        return count

    # ================================================================
    # Phase 1: 简短列表
    # ================================================================

    def get_brief_list(self) -> str:
        """
        生成 Phase 1 简短目录（用于 LLM 选择阶段）

        返回格式:
            ## Tools
            1. search_crypto_news [tool] — Search for cryptocurrency news from multiple sources.
            2. get_crypto_market_data [tool] — Get real-time market data for a cryptocurrency.

            ## Skills
            1. crypto_insight [skill] — Comprehensive cryptocurrency insight analysis.

        Returns:
            格式化的简短目录字符串
        """
        tools = []
        skills = []

        for item in self._items.values():
            line = f"{item.name} [{item.kind}] — {item.summary}"
            if item.kind == "tool":
                tools.append(line)
            else:
                skills.append(line)

        sections = []
        if tools:
            numbered = [f"{i}. {line}" for i, line in enumerate(tools, 1)]
            sections.append("## Tools\n" + "\n".join(numbered))
        if skills:
            numbered = [f"{i}. {line}" for i, line in enumerate(skills, 1)]
            sections.append("## Skills\n" + "\n".join(numbered))

        return "\n\n".join(sections) if sections else "No tools or skills available"

    # ================================================================
    # Phase 2: 按需详情
    # ================================================================

    def get_detail(self, names: List[str]) -> str:
        """
        获取指定 tool/skill 的完整描述（用于 LLM 规划阶段）

        对于 skill: 展示 skill 描述 + 自动展开子工具的完整详情（描述+参数）
        对于 tool: 展示工具的完整详情

        Args:
            names: 需要详情的 tool/skill 名称列表

        Returns:
            格式化的完整描述字符串
        """
        details = []
        included_tools = set()  # 避免重复展示子工具

        for name in names:
            item = self._items.get(name)
            if not item:
                logger.warning(f"[Catalog] Unknown item requested: {name}")
                continue

            if item.kind == "tool":
                if name not in included_tools:
                    details.append(self._format_tool_detail(item))
                    included_tools.add(name)
            else:
                # Skill: 先展示 skill 概述
                details.append(self._format_skill_detail(item))
                # 记录子工具名，避免后续重复展示
                for sub_name in (item.sub_tools or []):
                    included_tools.add(sub_name)
                # 再自动展开子工具的完整详情（描述+参数，来自 MCP）
                for sub_detail in self._get_skill_sub_tool_details(item):
                    details.append(sub_detail)

        return "\n\n".join(details) if details else "No details available"

    def get_item(self, name: str) -> Optional[CatalogItem]:
        """获取单个条目"""
        return self._items.get(name)

    def get_skill_sub_tools(self, skill_name: str) -> List[str]:
        """获取 skill 需要的子工具列表"""
        item = self._items.get(skill_name)
        if item and item.kind == "skill":
            return item.sub_tools
        return []

    def get_all_required_tools(self, selected_names: List[str]) -> List[str]:
        """
        从选中的 names 中提取所有需要的实际工具名

        - 如果选中的是 tool → 直接加入
        - 如果选中的是 skill → 展开其 sub_tools

        Args:
            selected_names: LLM Phase 1 选中的名称列表

        Returns:
            需要注册到 ToolRegistry 的工具名列表（去重）
        """
        tools = set()
        for name in selected_names:
            item = self._items.get(name)
            if not item:
                continue
            if item.kind == "tool":
                tools.add(name)
            elif item.kind == "skill":
                for sub in item.sub_tools:
                    tools.add(sub)
        return list(tools)

    @property
    def all_names(self) -> List[str]:
        return list(self._items.keys())

    @property
    def tool_names(self) -> List[str]:
        return [n for n, i in self._items.items() if i.kind == "tool"]

    @property
    def skill_names(self) -> List[str]:
        return [n for n, i in self._items.items() if i.kind == "skill"]

    # ================================================================
    # 内部方法
    # ================================================================

    @staticmethod
    def _make_summary(description: str, max_sentences: int = 2, max_chars: int = 120) -> str:
        """
        从完整描述中提取简洁摘要

        处理流程:
        1. 去除 markdown 格式标记（标题、分隔线、粗体、列表、代码块等）
        2. 合并为纯文本段落
        3. 提取前 N 句话，限制总长度
        """
        import re
        if not description:
            return "No description available."

        text = description.strip()

        # ---- Step 1: 移除 markdown 格式 ----
        # 移除代码块（```...```）
        text = re.sub(r'```[\s\S]*?```', ' ', text)
        # 移除行内代码
        text = re.sub(r'`[^`]+`', '', text)
        # 移除水平分隔线（--- 或 *** 或 ___ 独占一行）
        text = re.sub(r'^\s*[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
        # 移除 markdown 标题标记 (## -> 保留文字)
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
        # 移除粗体/斜体标记
        text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)
        text = re.sub(r'_{1,3}(.*?)_{1,3}', r'\1', text)
        # 移除列表标记 (- item, * item, 1. item)
        text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
        # 移除链接 [text](url) -> text
        text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)
        # 移除图片 ![alt](url)
        text = re.sub(r'!\[([^\]]*)\]\([^)]*\)', r'\1', text)

        # ---- Step 2: 合并空白，得到纯文本 ----
        # 多个换行/空白合并为单个空格
        text = re.sub(r'\s+', ' ', text).strip()

        if not text:
            return "No description available."

        # ---- Step 3: 按句子切分并提取 ----
        # 按 . ! ? 及中文句号分割
        parts = re.split(r'(?<=[.!?。！？])\s*', text)

        clean = []
        total_len = 0
        for s in parts:
            s = s.strip()
            if not s:
                continue
            # 跳过过短的碎片（可能是参数名等）
            if len(s) < 8:
                continue
            clean.append(s)
            total_len += len(s)
            if len(clean) >= max_sentences or total_len >= max_chars:
                break

        result = " ".join(clean) if clean else text[:max_chars]

        # 硬截断保底
        if len(result) > max_chars + 30:
            # 在 max_chars 附近找最近的句子边界
            cut = result[:max_chars + 30]
            last_period = max(cut.rfind('.'), cut.rfind('。'), cut.rfind('!'), cut.rfind('?'))
            if last_period > max_chars // 2:
                result = cut[:last_period + 1]
            else:
                result = cut[:max_chars] + "..."

        return result

    @staticmethod
    def _parse_parameters(input_schema: dict) -> List[Dict[str, Any]]:
        """解析 inputSchema 为参数列表（过滤注入参数）"""
        properties = input_schema.get("properties", {})
        required_params = input_schema.get("required", [])

        params = []
        for param_name, param_details in properties.items():
            if param_name in INJECTED_PARAMS:
                continue
            params.append({
                "name": param_name,
                "type": param_details.get("type", "any"),
                "required": param_name in required_params,
                "description": param_details.get("description", ""),
            })
        return params

    def _format_tool_detail(self, item: CatalogItem) -> str:
        """格式化工具的完整详情"""
        # 剥离 description 尾部的内联 "Parameters: ..." 段（参数由下方结构化段展示，避免重复）
        desc = re.sub(r'\s*Parameters?\s*:.*', '', item.description, flags=re.IGNORECASE).strip()
        lines = [f"### {item.name} [tool]", desc]

        if item.parameters:
            lines.append("**Parameters:**")
            for p in item.parameters:
                req = " (required)" if p.get("required") else ""
                lines.append(f"  - {p['name']} ({p.get('type', 'any')}){req}: {p.get('description', '')}")

        return "\n".join(lines)

    def _format_skill_detail(self, item: CatalogItem) -> str:
        """格式化技能的完整详情（包含子工具的完整描述，自动从 MCP 获取）"""
        lines = [f"### {item.name} [skill]", f"{item.description}"]

        if item.sub_tools:
            lines.append(f"**Required tools:** {', '.join(item.sub_tools)}")

        return "\n".join(lines)

    def _get_skill_sub_tool_details(self, item: CatalogItem) -> List[str]:
        """获取 skill 子工具的完整详情（自动从 catalog 中获取，无需手动维护）"""
        details = []
        if not item.sub_tools:
            return details
        for sub_name in item.sub_tools:
            sub_item = self._items.get(sub_name)
            if sub_item:
                details.append(self._format_tool_detail(sub_item))
        return details
