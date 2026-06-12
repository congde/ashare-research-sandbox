# -*- coding: utf-8 -*-
"""
Customer Service Knowledge Base Tool
"""

import time
import os
import json
import logging
from typing import Any, Dict

from agent.tools.base import BaseTool, ToolResult
from mcp.mcp_http_client import mcp_client, CallToolRequestParams, CallToolError
from web import authenticator as auth
from libs import http
from web.config import config


logger = logging.getLogger(__name__)


class CustomerServiceKBTool(BaseTool):
    """
    Customer Service Knowledge Base Search Tool

    Specialized tool for customer service knowledge base queries in KuCoin platform.
    Provides simplified parameter interface, automatic language mapping, and
    customer-friendly result formatting.

    Parameters:
        query: User query content
        detect_language: Detected language of user query

    Implementation Note:
        This tool requires manual integration with actual customer service
        knowledge base API. The execute() method provides a template that
        needs to be implemented with actual API calls.
    """

    @property
    def name(self) -> str:
        return "customer_service_kb_search"

    @property
    def description(self) -> str:
        return (
            "Specialized tool for searching KuCoin customer service knowledge base. "
            "Retrieves platform features, policies, tutorials, and non-real-time FAQs. "
            "Only applicable to predefined customer service question categories. "
            "This customer service knowledge base covers routine support scenarios for KuCoin users, including account management and identity verification, fiat and cryptocurrency deposits/withdrawals, various trading products (spot, margin, futures/contracts, fast trade, P2P), wealth management/lending/earn products, card services, and platform activities. For each category, it provides typical question templates and troubleshooting key points, suitable for handling user inquiries and automating fault ticket resolution related to: account access and security, KYC and risk control, deposit/withdrawal status and exceptions, trading permissions and order placement/issues, lending/wealth management operations, card/payment services, and activity rewards/commissions."
        )

    async def mcp_description(self) -> str:
        """直接返回本地 description，跳过 MCP prompt 缓存（避免旧缓存含内联参数导致重复）"""
        return self.description

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "User query content to search in customer service knowledge base,no matter user's language,search query must be in English and concise, avoid complex sentences. no need to include greetings or polite words and such, just focus on the key question. For example, use 'How to reset my password?' instead of 'Hello, I would like to know how can I reset my password, thank you!'"
                },
                "detect_language": {
                    "type": "enum",
                    "enum": ["en_US", "zh_HK", "ru_RU", "ko_KR", "ja_JP", "pt_PT", "nl_NL", "de_DE", "fr_FR", "es_ES", "vi_VN", "tr_TR", "it_IT", "ms_MY", "id_ID", "hi_IN", "th_TH", "ar_AE", "bn_BD", "pl_PL", "fil_PH", "ur_PK", "uk_UA"],
                    "description": "Detected language of user query, must choose one from the list, e.g., 'zh_HK' for Traditional Chinese, 'en_US' for English."
                }
            },
            "required": ["query", "detect_language"]
        }

    async def execute(self, query: str, detect_language: str, **kwargs) -> ToolResult:
        """
        功能对接：https://bot.dev.kucoin.net/doc.html#/default-group/KIA%20support%20internal%20APIs/queryAdvancedAiUsingPOST
        示例：
            How to remove or unbind Google 2FA?
            Problems with registration
        """
        from web.context import context
        start_time = time.time()
        logger.info(f"tools/call, customer_service_kb_search, query: {query}, detect_language: {detect_language}")
        if os.getenv("serverEnv") in ("local", "offline"):
            resp = await http.post(
                url="https://inner.sit.kucoin.net/intelligent-bot-server/api/inner/kia/advanced-ai/query",
                json={
                    "contextParams": {},
                    "lang": detect_language,
                    "userId": kwargs.get("userId", context.get("user_id", "unknown")),
                    "userInput": query,
                },
                headers={"X-KC-CDN-SITE-TYPE": "global"},
                retries=3,
            )
        else:
            resp = await auth.post(
                app_name=config.kcbot_server.server_name,
                api="/api/inner/kia/advanced-ai/query",
                json={
                    "contextParams": {},
                    "lang": detect_language,
                    "userId": kwargs.get("userId", context.get("user_id", "unknown")),
                    "userInput": query,
                },
                retries=3,
                securekey=config.kcbot_server.securekey,
            )
        cost_time = int((time.time() - start_time) * 1000)
        data = resp.get("data") or {}
        answer = data.get("answer") or []
        suggestions = (data.get("relatedIssues") or [])[:3]
        logger.info(
            f"[{self.name}] cost_time={cost_time}ms, Callback response: answer_len={len(answer)}, "
            f"suggestions={len(suggestions)}, raw_keys={list(resp.keys())}, response={resp}"
        )
        raw_data = {
            "answer_response": answer,
            "query_followup_suggestions": suggestions,
            "disable_llm": True,
        }
        return ToolResult(
            success=True,
            content=json.dumps(raw_data, ensure_ascii=False),
            data=raw_data,
            metadata={"tool_name": self.name, "disable_llm": True},
        )

