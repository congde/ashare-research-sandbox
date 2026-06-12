# -*- coding: utf-8 -*-
"""
ToolMixin — tool decision, tool calling, MCP interaction, and risk checks.

Methods extracted from BaseAgent for readability.
"""

import json
import time
import logging
import traceback
from datetime import datetime
from typing import List, Dict, Optional

from pydantic import BaseModel

from agent.schema import (
    QAModel,
    StepType,
    StepModel,
    StreamResponse,
    StreamStatusType,
    HistoryStepType,
)
from agent.plan.decorators import save_step
from agent.utils import truncate_message, truncate_web_search_query
from agent.context.token_budget import estimate_tokens
from libs.language import (
    get_localized_message,
    detect_chinese_variant,
    LANGUAGE_CODE_TO_NAME_MAP,
    ENGLISH_NAME_TO_CODE_MAP,
    KB_SEARCH_ENGLISH_NAME_TO_CODE_MAP,
    ENGLISH_NAME_TO_CODE_LOCAL_MAP,
)
from libs.citation_processor import CitationProcessor
from mcp.mcp_http_client import mcp_client, CallToolRequestParams, CallToolResult, CallToolError
from web.config import config
from web.context import context
from web.exceptions import RiskException
from web import code_msg

logger = logging.getLogger(__name__)


class ToolMixin:
    """Provides tool decision-making, MCP tool calling, URL risk checking, and result filtering."""

    async def _check_url_risk(self, text, node_name: str):
        from web.config import is_risk_control_enabled

        if not is_risk_control_enabled():
            return
        if config.url_risk_enable and text.strip():
            extracted_urls = self._url_checker.extract_urls(text)
            if extracted_urls:
                logger.info(f"🔍 [{node_name}风控-URL] 检测到 {len(extracted_urls)} 个URL: {extracted_urls}")
                url_result = await self._url_checker.check_text(text)
            
                if url_result.has_risk:
                    fallback_msg = self._url_checker.get_fallback_message(self.system_lang_code)
                    logger.error(
                        f"❌ [{node_name}风控-URL] 检测到风险URL，阻止会话继续\n"
                        f"  风险URL数量: {len(url_result.risky_urls)}\n"
                        f"  风险URL列表: {url_result.risky_urls}\n"
                        f"  返回消息: {fallback_msg}"
                    )
                    raise RiskException(code=code_msg.CODE_RISK_ERROR, msg=fallback_msg)
                else:
                    logger.info(f"✅ [{node_name}风控-URL] {len(extracted_urls)} 个URL均安全")
            else:
                logger.info(f"[{node_name}风控-URL] 回复中未检测到URL，跳过风控检查")


    def _extract_crypto_names(self, tools_result):
        """从tools_result中提取所有加密货币名称（如 BTC、ETH 等），最多20个，返回逗号分隔字符串，不排序"""
        if not tools_result:
            return ''
        crypto_names = []
        seen = set()
        for item in tools_result:
            if not isinstance(item, dict):
                continue
            text = item.get('text')
            if not text:
                continue
            try:
                data = json.loads(text)
                if isinstance(data, dict):
                    data = [data]
                for entry in data:
                    if isinstance(entry, dict):
                        name = entry.get('currency')
                        if name and name not in seen:
                            crypto_names.append(name)
                            seen.add(name)
                            if len(crypto_names) >= 20:
                                break
                if len(crypto_names) >= 20:
                    break
            except Exception as e:
                logger.warning(f"Failed to parse crypto info from tools_result item: {e}; text={text}")
        return ','.join(crypto_names)
   

    async def _decide_tools(self, query, history):
        start_time = time.time()
        reply_language = None
        tool_decision = await self._decide_tools_and_actions(query, history)
        if tool_decision.get('tool_call') is not None:
            try:
                tool_call_arguments = json.loads(tool_decision['tool_call']['arguments'])
                model_detected_language = tool_call_arguments.get('detect_language')
            except Exception as e:
                model_detected_language = None
        else:
            model_detected_language = None
        cost_time = int((time.time() - start_time) * 1000)
        self._step_log(cost_time, "_decide_tools")
        logger.info(f"model_detected_language: {model_detected_language}")
        # 大模型对中文简繁判断不准，额外进行判断
        if model_detected_language:
            if 'chinese' in model_detected_language.lower():
                reply_language = detect_chinese_variant(query)
            else:
                reply_language = model_detected_language
        else:
            reply_language = LANGUAGE_CODE_TO_NAME_MAP[self.system_lang_code][0]
        logger.info(f"reply_language: {reply_language}")
        self.cache.update({"reply_language": reply_language})
        return tool_decision, reply_language


    @save_step(stream_type=StepType.TOOL_EXECUTION)
    async def _call_tools(self, tool_decision, user_query, reply_language, **kwargs):
        # 获取step对象，用于在兜底策略时清空之前的内容
        step = kwargs.get("step")

        title_stream = StreamResponse(
            type=StepType.TITLE,
            content=""
        )
        content_stream = StreamResponse(
            type=StepType.CONTENT,
            content=""
        )
        result_stream = StreamResponse(
            type=StepType.TOOL_RESULT,
            content=dict(),
            deliver=False
        )
        tool_name = ""
        tools_result = None
        if tool_decision and tool_decision.get('tool_call') and tool_decision.get('tool_call').get('name') != 'direct_response':
            try:
                rewritten_query = user_query
                tool_name = tool_decision['tool_call']['name']
                self.cache.update({
                    "tool_name": tool_name,
                })
                tool_call_arguments = json.loads(tool_decision['tool_call']['arguments'])
                rewritten_query = tool_call_arguments.get('query', rewritten_query)
                tool_name_display = get_localized_message(tool_name, self.system_lang_code)
                if not tool_name_display:
                    raise CallToolError(f"The current LLM returns a tool_name error, tool_name={tool_name}")

                # 发送工具调用标题
                async for event in self._yield_thinking_title("calling_tools_start"):
                    title_stream.content = event
                    yield title_stream

                # 发送工具调用内容
                for char in f"{tool_name_display}: {rewritten_query}":
                    content_stream.content = char
                    yield content_stream

                if tool_decision['tool_call']['name'].lower() == 'kb_search':
                    tool_call_arguments["target_language"] = KB_SEARCH_ENGLISH_NAME_TO_CODE_MAP.get(self.cache.get("reply_language", "en"), "en")
                    logger.info(f"kb_search tool_call_arguments: {tool_call_arguments}")

                elif tool_decision['tool_call']['name'].lower() == 'recharge_and_withdraw':
                    if "detect_language" in tool_call_arguments:
                        del tool_call_arguments["detect_language"]
                    tool_call_arguments["lang"] = ENGLISH_NAME_TO_CODE_LOCAL_MAP.get(self.cache.get("reply_language", "English"), "en_US")
                    logger.info(f"recharge_and_withdraw tool_call_arguments: {tool_call_arguments}")

                elif tool_decision['tool_call']['name'].lower() == 'web_search':
                    q = tool_call_arguments.get("query", "")
                    if q:
                        truncated = truncate_web_search_query(q)
                        if len(truncated) < len(q):
                            logger.info(f"[web_search] query truncated from {len(q)} to {len(truncated)} chars")
                        tool_call_arguments["query"] = truncated
                        rewritten_query = truncated

                # elif tool_decision['tool_call']['name'].lower() in ('recommend_financial_product', 'recommend_crypto'):
                #     tool_call_arguments['user_id'] = self.user_id if hasattr(self, "user_id") and self.user_id else "Unknown"
            
                user_id = self.user_id if hasattr(self, "user_id") and self.user_id else "Unknown"
                tool_call_arguments.update({
                    "user_id": user_id,
                    "userId": user_id
                })

                tool_decision['tool_call']['arguments'] = tool_call_arguments

                # Transcript: append tool_call event (shadow write)
                if hasattr(self, '_is_context_enabled') and self._is_context_enabled():
                    try:
                        writer = self._get_transcript_writer()
                        if writer:
                            await writer.append_tool_call(
                                tool_name=tool_name,
                                arguments=tool_call_arguments,
                                tool_call_id=tool_decision['tool_call'].get('tool_call_id', ''),
                            )
                    except Exception as _te:
                        logger.debug(f"Transcript tool_call append failed: {_te}")

                tools_result = await mcp_client.call_tool(CallToolRequestParams(
                    name=tool_decision['tool_call']['name'],
                    arguments=tool_call_arguments
                ))

                # Transcript: append tool_result event (shadow write)
                if hasattr(self, '_is_context_enabled') and self._is_context_enabled():
                    try:
                        writer = self._get_transcript_writer()
                        if writer:
                            result_text = str(tools_result.model_dump(mode="json").get("content", []))[:3000] if tools_result else ""
                            await writer.append_tool_result(
                                tool_name=tool_name,
                                success=True,
                                data=result_text,
                                tool_call_id=tool_decision['tool_call'].get('tool_call_id', ''),
                            )
                    except Exception as _te:
                        logger.debug(f"Transcript tool_result append failed: {_te}")

            except Exception as e:
                # 执行工具失败兜底策略
                # logger.warning(str(e))
                logger.exception('Call tool error')
                try:
                    _web_search_tool_name = "web_search"
                    if tool_name != _web_search_tool_name:
                        self.cache.update({
                            "tool_name": _web_search_tool_name,
                        })

                        # 修改工具调用标题
                        yield StreamResponse(
                            sessionId=self.session.id,
                            qaId=self.qa.id,
                            status=StreamStatusType.PENDING,
                            type=StepType.TITLE_CORRECTION,
                            content=get_localized_message("calling_tools_end", self.system_lang_code)
                        )

                        # 发送结束流，结束失败的工具执行
                        yield StreamResponse(
                            sessionId=self.session.id,
                            qaId=self.qa.id,
                            status=StreamStatusType.END,
                            type=StepType.TOOL_EXECUTION
                        )

                        # 清空之前失败工具积累的内容，避免内容重复
                        if step:
                            step.step[StepType.TITLE] = ""
                            step.step[StepType.CONTENT] = ""
                            step.step[StepType.TITLE_CORRECTION] = ""
                    
                        # 发送开始流，开始兜底工具执行
                        yield StreamResponse(
                            sessionId=self.session.id,
                            qaId=self.qa.id,
                            status=StreamStatusType.START,
                            type=StepType.TOOL_EXECUTION
                        )

                        # 发送工具调用标题
                        tool_name_display = get_localized_message(_web_search_tool_name, self.system_lang_code)
                        _fallback_query = truncate_web_search_query(rewritten_query)
                        async for event in self._yield_thinking_title(
                                step="calling_tools_start",
                                query=_fallback_query,
                                tool_name=tool_name_display
                        ):
                            title_stream.content = event
                            yield title_stream

                        # 发送工具调用内容
                        for char in f"{tool_name_display}: {_fallback_query}":
                            content_stream.content = char
                            yield content_stream

                        tool_name = _web_search_tool_name
                        self._tool_call = {
                            "tool_call": {
                                "tool_call_id": 'call_fallback', 
                                'name': tool_name, 
                                'arguments': json.dumps({"query": _fallback_query}, ensure_ascii=False)
                            },
                            "content": ""
                        }
                        tools_result = await mcp_client.call_tool(CallToolRequestParams(
                            name=tool_name,
                            arguments={"query": _fallback_query}
                        ))
                except Exception:
                    logger.exception("web_search tool callback execution failed")

        if tools_result is not None:
            # ============ URL风控: web_search结果前置过滤 ============
            if tool_name == "web_search":
                from web.config import is_risk_control_enabled

                url_risk_enable = is_risk_control_enabled() and getattr(config, 'url_risk_enable', True)

                if url_risk_enable:
                    logger.info(f"[web_search风控] 开始对搜索结果进行URL风险检测")
                    tools_result = await self._filter_risky_web_search_results(tools_result)
                    logger.info(f"[web_search风控] URL风险过滤完成")

            content = {
                "input": None,
                "output": tools_result.model_dump(mode="json").get("content", []) if tools_result is not None else []
            }
            if self._tool_call:
                if isinstance(self._tool_call, BaseModel):
                    content['input'] = self._tool_call.model_dump(mode="json")
                else:
                    content['input'] = self._tool_call
            if tool_name and self._tools_info and tool_name in self._tools_info.tools_name_map:
                content.update(self._tools_info.tools_name_map[tool_name].model_dump(mode="json"))
            result_stream.content = content
            yield result_stream

            # web_search的url引用处理
            search_id_to_url_map = await self._build_links_message(
                tool_name,
                tools_result
            )

            # kb_search一次性返回富文本模版到前端
            if tool_name.lower() == "kb_search":
                disable_llm = False
                results = []
                try:
                    tools_data_map = json.loads(tools_result.content[0].text)
                    disable_llm = tools_data_map.get("disable_llm", False)
                    results = tools_data_map.get("results", [])
                except Exception as e:
                    logger.error(f"Parse json error, error_msg={e}")
                self.cache.update({
                    "kb_search_info": {
                        "disable_llm": disable_llm,
                        "results": results
                    }
                })

            # 非行情事件查询工具的结果处理
            if tool_name.lower() == "retrieve_fundamental_events":
                try:
                    search_id_to_url_map = json.loads(tools_result.content[0].text)['results']
                    search_id_to_url_map = {(idx + 1): item for idx, item in enumerate(search_id_to_url_map)}
                except Exception as e:
                    logger.error(f"Parse json error, error_msg={e}")
                    search_id_to_url_map = {}

            # 币种筛选工具结果处理
            if self.cache.get("tool_name", "") == 'coin_screener':
                self._build_coin_screener_data(tools_result.content[0].text, reply_language)

            if self.cache.get("tool_name", "") == 'recharge_and_withdraw':
                self._build_recharge_withdraw_data(tools_result.content[0].text)

            self.cache.update({
                "tools_result": tools_result.model_dump(mode="json").get("content",[]) if tools_result is not None else None,
                "search_id_to_url_map": search_id_to_url_map,
            })

        if tool_decision and tool_decision.get('tool_call') and tool_decision.get('tool_call').get('name') != 'direct_response':
            # 修改工具调用标题
            yield StreamResponse(
                sessionId=self.session.id,
                qaId=self.qa.id,
                status=StreamStatusType.PENDING,
                type=StepType.TITLE_CORRECTION,
                content=get_localized_message("calling_tools_end", self.system_lang_code)
            )


    async def _decide_tools_and_actions(
            self,
            user_query: str,
            history: List[QAModel],
    ) -> Dict:
        """
        Comprehensive decision making for tool usage and operation strategies

        This is the core AI decision-making method that analyzes user queries and decides:
        - Whether to use RAG knowledge base search
        - Whether to use web search
        - Optimization strategies for various searches
        - Control of return result quantities

        Args:
            user_query: User's current query
            history: Conversation history
            history_turns: Number of turns in conversation history

        Returns:
            Dict: Complete configuration containing all tool decisions and search strategies
        """
        # Get current date for time-sensitive queries
        current_date = datetime.now().strftime("%Y-%m-%d")
        current_year = datetime.now().year

        tools_info = await mcp_client.get_tools_info()
        self._tools_info = tools_info
        tools = self._tools_info.openai_tools

        # 额外添加一个直接回复用户的工具
        tools.append({
            "type": "function",
            "function": {
                "name": "direct_response",
                "description": "This tool is used to directly respond to the user's query when no external tools are needed. You should provide your intended response content in the suggested_response parameter to help the system understand your response intent.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "suggested_response": { "type": "string", "description": "Your intended response content to the user's query. Keep it as brief as possible (preferably one sentence or a few key points) to express your response intent. The system will generate a refined final response based on this, so you only need to provide a concise summary of what you want to convey." },
                        "detect_language": { "type": "string", "description": "Detect the **writing language** (linguistic system) used in the user's query text. For example: 'What's the weather in Paris' is written in English, even though it mentions Paris. If the user explicitly requests a specific language for the response (e.g., 'please reply in XX language' or '請以 XX 語回覆我'), set this field to that requested language. Value constraints: (1) If the detected language or requested language is in the supported languages list, the value MUST exactly match one of the language names from the supported languages list. Supported languages: " + ", ".join([name for name in ENGLISH_NAME_TO_CODE_MAP.keys()]) + " (2) If the detected language or requested language is NOT in the supported languages list, you may use your understanding to output the language name in English. Note: You must carefully distinguish between Simplified Chinese and Traditional Chinese. If you are uncertain, prefer Traditional Chinese as much as possible. " }
                    },
                    "required": ["suggested_response", "detect_language"]
                }
            }
        })
        system_prompt = await mcp_client.get_prompt(
            name="tool_decision_prompt",
            data={
                "current_date": current_date,
                "current_year": current_year,
                'external_tools_list': tools_info.tools_name,
                'supported_languages_list': [name for name in ENGLISH_NAME_TO_CODE_MAP.keys()]
            }
        )
        messages = [{"role": "system", "content": system_prompt}]
        # Build conversation history messages
        if history:
            context_payload = await self._prepare_context(
                history=history,
                history_turns=6,
                current_query_tokens=estimate_tokens(user_query or ""),
            )
            history_messages = context_payload.get("messages", [])
            if history_messages:
                context.get("kia_memory").history[HistoryStepType.TOOL_DECIDE] = history_messages
            messages.extend(history_messages)
        messages.extend([{"role": "user", "content": truncate_message(user_query, 1000)}])

        # Define tools
        try:
            if not self.llm:
                await self._create_client()

            extra_body = None if config.use_azure_openai else {
                "chat_template_kwargs": {"enable_thinking": False},
            }
            response = await self.llm.chat.completions.create(
                model=self.model_name,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                max_tokens=800,
                temperature=0.2,  # Lower temperature for better consistency
                timeout=config.llm_api_timeout or 30.0,  # API 调用超时时间（秒）
                extra_body=extra_body
            )

            logger.info(f"Tool decision response: {response.choices[0].message.model_dump()}")

            tool_call = response.choices[0].message.tool_calls[0] if response.choices[0].message.tool_calls else None
            content = response.choices[0].message.content
            # 如果tool_call是None，则设置tool_call为direct_response
            if not tool_call:
                tool_call_fallback = {
                    "name": "direct_response",
                    "arguments": json.dumps({"suggested_response": content, "detect_language": LANGUAGE_CODE_TO_NAME_MAP[self.system_lang_code][0]}),
                    "tool_call_id": "call_fallback_direct_response"
                }
            self._tool_call = {
                "tool_call": tool_call.function.to_dict() | {'tool_call_id': tool_call.id} if tool_call else tool_call_fallback,
                "content": content if content else ""
            }
            self.cache.update({
                "tool_name": tool_call.function.name if tool_call else "direct_response",
            })
            return self._tool_call
        except Exception:
            logger.exception('LLM decide tools error')
            return {
                "tool_call": {},
                "content": ""
            }

    async def _build_links_message(self, tool_name: str, tools_result: Optional[CallToolResult] = None) -> dict:
        """联网搜索工具url处理"""
        if not tools_result or tool_name != "web_search":
            return {}

        try:
            tools_links, idx = {}, 1
            for row in tools_result.content:
                if not row.type in ("resource", "text"):
                    continue
                text = json.loads(row.text)
                for item in text.get("results", []):
                    url = item.get("url")
                    if not url:
                        continue
                    tools_links[idx] = {
                        "index": idx,
                        "url": url,
                        "title": item.get("title", "")
                    }
                    idx += 1

            return tools_links
        except Exception as e:
            logger.exception('LLM build links message error')
            return {}

    async def _filter_risky_web_search_results(self, tools_result: CallToolResult) -> CallToolResult:
        """
        过滤web_search结果中的风险URL

        新方案: 在工具决策前对web_search结果进行URL风控
        删除有风险的搜索结果项，防止风险内容进入后续LLM处理

        Args:
            tools_result: 原始web_search工具返回结果

        Returns:
            CallToolResult: 过滤后的工具结果（移除风险URL的搜索项）
        """
        try:
            # 提取所有URL和搜索结果
            all_urls = []
            all_results = []
            for row in tools_result.content:
                if row.type not in ("resource", "text"):
                    continue
                text_data = json.loads(row.text)
                for item in text_data.get("results", []):
                    url = item.get("url")
                    if url:
                        all_urls.append(url)
                        all_results.append(item)

            if not all_urls:
                logger.info(f"   未提取到URL，跳过风险检测")
                return tools_result

            logger.info(f"📋 [web_search风控] 原始结果: {len(all_results)} 个")
            # 打印原始搜索结果（简化版，只显示标题）
            for idx, item in enumerate(all_results, 1):
                logger.info(f"   [{idx}] {item.get('title', 'N/A')[:80]}")

            # 调用URL检测器
            url_result = await self._url_checker.check_urls(all_urls)

            if not url_result.has_risk:
                logger.info(f"✅ [web_search风控] 全部URL安全，无需过滤")
                return tools_result

            # 发现风险URL，需要过滤
            logger.warning(
                f"⚠️ [web_search风控] 检测到 {len(url_result.risky_urls)} 个风险URL: {url_result.risky_urls}"
            )

            # 提取风险域名集合（用于高效匹配）
            risky_domains = set()
            for url in url_result.risky_urls:
                domain = self._url_checker.extract_domain(url)
                if domain:
                    risky_domains.add(domain)

            # 过滤掉风险URL的搜索结果，并重新编排索引
            filtered_content = []
            removed_items = []
            safe_items = []

            for row in tools_result.content:
                if row.type not in ("resource", "text"):
                    filtered_content.append(row)
                    continue

                text_data = json.loads(row.text)
                original_results = text_data.get("results", [])
                safe_results = []

                for item in original_results:
                    url = item.get("url", "")
                    domain = self._url_checker.extract_domain(url)

                    if domain not in risky_domains:
                        safe_results.append(item)
                        safe_items.append(item)
                    else:
                        removed_items.append(item)

                # 更新results
                text_data["results"] = safe_results

                # 创建新的content项
                from mcp.types import TextContent
                new_row = TextContent(
                    type="text",
                    text=json.dumps(text_data, ensure_ascii=False)
                )
                filtered_content.append(new_row)

            # 创建新的CallToolResult
            tools_result.content = filtered_content

            # 打印过滤对比
            if removed_items:
                logger.warning(f"\n❌ [移除的搜索结果] 共 {len(removed_items)} 个:")
                for idx, item in enumerate(removed_items, 1):
                    logger.warning(
                        f"   [{idx}] {item.get('title', 'N/A')[:80]}\n"
                        f"       URL: {item.get('url', 'N/A')}"
                    )

            logger.info(f"\n✅ [保留的搜索结果] 共 {len(safe_items)} 个:")
            for idx, item in enumerate(safe_items, 1):
                logger.info(f"   [{idx}] {item.get('title', 'N/A')[:80]}")

            logger.info(
                f"\n✅ [web_search风控] 过滤完成: 原始{len(all_results)}个 -> 移除{len(removed_items)}个 -> 保留{len(safe_items)}个"
            )

            return tools_result

        except Exception as e:
            logger.exception(f"❌ [web_search风控] 过滤失败: {e}")
            return tools_result
