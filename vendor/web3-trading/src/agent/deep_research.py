# -*- coding: utf-8 -*-
'''
@Time    :   2025/09/03 16:52:39
'''

import json
import os
import logging
import time
import asyncio
import aiohttp

from datetime import datetime

from agent.schema import StreamResponse, StepType, StepModel, StreamStatusType, StepStatusType, HistoryStepType
from agent.utils import jinja_render
from agent.base import BaseAgent, AgentType, StopError, save_step
from agent.context.token_budget import estimate_tokens
from web.config import config
from libs.typing_effect import TypingEffect
from web.context import context
from libs.eureka import eureka
from web.authenticator import get_headers
from libs.language import get_localized_message, detect_chinese_variant, ENGLISH_NAME_TO_CODE_MAP, LANGUAGE_CODE_TO_NAME_MAP
from llm.shield.translate import translate
from llm.llm import final_response, llm
from mcp.mcp_http_client import mcp_client

logger = logging.getLogger(__name__)


def clean_tool_call_tags(arguments: str) -> str:
    """
    清理 tool_call.function.arguments 中可能存在的 <tool_call> 标签
    
    Args:
        arguments: 原始的 arguments 字符串
        
    Returns:
        清理后的 JSON 字符串
    """
    if not arguments:
        return arguments
    
    arguments = arguments.strip()
    
    # 检查是否包含 <tool_call> 标签
    if arguments.startswith('<tool_call>') and arguments.endswith('</tool_call>'):
        # 提取标签内的内容
        arguments = arguments[len('<tool_call>'):-len('</tool_call>')].strip()
    
    return arguments


class DeepResearchAgent(BaseAgent):
    NAME = AgentType.DEEP_RESEARCH

    async def on_init(self, *args, **kwargs):
        await super().on_init(*args, **kwargs)
        self._typing_effect = TypingEffect(context.get("request"))
        self._deep_research_service = config.deep_research_url

    async def _run(self):
        breadth = self.kwargs.get("breadth", 2)
        if not (1 <= breadth <= 8):
            raise StopError(f"Invalid breadth parameter: {breadth}. Must be between 1 and 8.")
        depth = self.kwargs.get("depth", 2)
        if not (1 <= depth <= 4):
            raise StopError(f"Invalid depth parameter: {depth}. Must be between 1 and 4.")

        user_query = self.query
        self.history = await self._get_history(self.session_id, self.user_id)

        # 1、澄清问题
        disable_query_clarify = str(os.environ.get("DISABLE_QUERY_CLARIFY", "False")).lower() == 'true'
        if disable_query_clarify:
            self.cache['clarification_result'] = {'is_ready_for_research': True}

        elif self._has_query_clarify_in_latest_history(self.history):
            # 最近一条消息包含澄清问题，跳过澄清步骤，但需要从历史中生成research_query
            logger.info("Latest history contains query clarification, skipping clarification step")
            query_result = await self._generate_research_query_from_history(user_query, self.history)
            self.cache['clarification_result'] = {
                'is_ready_for_research': True,
                'research_query': query_result.get('research_query', user_query),
                'model_detected_language': query_result.get('model_detected_language', '')
            }
        
        else:
            async for event in self._clarify_question(user_query, self.history):
                yield event

        # 2、生成研究报告
        if self.cache.get("clarification_result", {}).get("is_ready_for_research", False):
            # 输出分析问句标题流
            async for event in self._analyz_query():
                yield event
            
            model_detected_language = self.cache.get("clarification_result", {}).get("model_detected_language", "")
            logger.info(f"model_detected_language: {model_detected_language}")
            # 大模型对中文简繁判断不准，额外进行判断
            if model_detected_language:
                if 'chinese' in model_detected_language.lower():
                    reply_language = detect_chinese_variant(user_query)
                else:
                    reply_language = model_detected_language
            else:
                reply_language = LANGUAGE_CODE_TO_NAME_MAP[self.system_lang_code][0]
            logger.info(f"reply_language: {reply_language}")
            async for event in self._generate_report(user_query, reply_language, breadth, depth):
                yield event
    
    # @save_step(stream_type=StepType.REPORT_GENERATION)
    async def _generate_report(self, user_query, reply_language, breadth, depth, timeout=900):
        research_query = self.cache.get("clarification_result", {}).get('research_query', user_query)
        logger.info(f"clarified deep research query: {research_query}")
        if not research_query or research_query.strip() == "":
            research_query = user_query
            logger.info(f"Proceeding with research query: {research_query}")
        payload = {
            "query": research_query,
            "system_language_code": self.system_lang_code,
            "reply_language_name": reply_language,
            "breadth": breadth,
            "depth": depth
        }
        logger.info(f"Deep research payload: query='{research_query}', breadth={breadth}, depth={depth}")

        self.in_query_analysis = None
        self.in_research_decomposition = None
        self.in_progress = None
        self.in_report = None
        self.step = StepModel(type=StepType.PROGRESS)
        
        # 初始化报告内容缓存
        self.cache['report_content'] = ""

        try:
            logger.info(f"app_name={config.deep_research_server}, json={payload}, api=/api/generate_report_stream")
            if os.environ.get('serverEnv', '') == 'local':
                self._deep_research_service = config.deep_research_url.strip('/')
            else:
                self._deep_research_service = eureka.get_service_url(app_name=config.deep_research_server).strip('/')

            url = f"{self._deep_research_service}/api/generate_report_stream"
            headers = get_headers(
                app_name=os.environ.get("DEEP_RESEARCH_SERVER", "ai-deep-research"),
                method="POST",
                url=url,
                headers=context.get('headers', {}),
                sk=config.deep_research_securekey,
                name=os.getenv("SERVER_NAME").upper()
            )
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self._deep_research_service}/api/generate_report_stream",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                    headers=headers
                ) as response:
                    logger.info(f"Deep research service response status: {response.status}")
                    response.raise_for_status()
                    async for line in response.content:
                        async for event in self._report_stream(line):
                            if not event:
                                continue
                            yield event
                    
                    # 流式处理完成后，提取币种信息
                    logger.info("Deep research report completed, extracting currency suggestions")
                    async for event in self._extract_currency_suggestions(self.cache.get("report_content", "")):
                        yield event
                    
        except asyncio.CancelledError:
            raise
        except (aiohttp.ClientConnectorError, aiohttp.ClientResponseError) as e:
            # 连接失败或HTTP错误状态码，使用 ReAct 多轮工具循环 + 研报生成降级方案
            logger.warning(f"Deep research service unavailable: {e}, falling back to local ReAct report generation")
            async for event in self._fallback_generate_report(user_query, reply_language):
                yield event
        except Exception as e:
            # 其他异常（如超时等），仍然抛出异常
            logger.exception('Generate report error')
            if self.qa.answer:
                latest_step = self.qa.answer[-1]
                latest_step.status = StepStatusType.FAILED
                latest_step.log = str(e)
            else:
                self.qa.answer.append(StepModel(type=StepType.PROGRESS, status=StepStatusType.FAILED, log=f"{str(e)}"))
            await self.qa.save()
            raise
        finally:
            await self.qa.save()

    async def _report_stream(self, line):
        start_time = time.time()
        line_str = line.decode('utf-8').strip()
        if not line_str.startswith('data: '):
            return

        def concat_content(step_type, content=""):
            tmp = self.step.step.get(step_type) 
            if tmp is None:
                self.step.step[step_type] = ""
            self.step.step[step_type] += content

        def stream_content(step_type, content, status=StreamStatusType.PENDING, chunk_size=1):
            """
            按chunk_size个char拼接为chunk进行流式输出content
            """
            if not content:
                return
            chunk = ""
            for char in content:
                chunk += char
                if len(chunk) >= chunk_size:
                    yield StreamResponse(type=step_type, content=chunk, status=status, qaId=self.qa.id, sessionId=self.session.id).model_dump_json(exclude={'deliver', 'save'})
                    chunk = ""
            if chunk:
                yield StreamResponse(type=step_type, content=chunk, status=status, qaId=self.qa.id, sessionId=self.session.id).model_dump_json(exclude={'deliver', 'save'})

        data_json = json.loads(line_str[6:])  # Remove 'data: ' prefix
        raw_step = data_json.get('step', 'CONTENT').upper()
        raw_status = data_json.get('status', '').upper()
        msg_type = data_json.get('type', '')
        step_type = StepType.from_value(raw_step)
        data = data_json.get('data', {})
        content = str(data.get('message', ''))

        if msg_type == 'query_analysis':
            if self.in_query_analysis is None:
                yield StreamResponse(type=StepType.QUERY_ANALYSIS, status=StreamStatusType.START, qaId=self.qa.id, sessionId=self.session.id).model_dump_json(exclude={'deliver', 'save'})
                self.step = StepModel(type=StepType.QUERY_ANALYSIS)
                for chunk in stream_content(StepType.TITLE, content=content):
                    yield chunk
                concat_content(StepType.TITLE, content=content)
                self.in_query_analysis = True
            else:
                if step_type == StepType.TITLE_CORRECTION:
                    yield StreamResponse(type=StepType.TITLE_CORRECTION, status=StreamStatusType.PENDING, content=content, qaId=self.qa.id, sessionId=self.session.id).model_dump_json(exclude={'deliver', 'save'})
                    yield StreamResponse(type=StepType.QUERY_ANALYSIS, status=StreamStatusType.END, qaId=self.qa.id, sessionId=self.session.id).model_dump_json(exclude={'deliver', 'save'})
                    self.step.step[StepType.TITLE_CORRECTION] = get_localized_message("analyzing_query_end", self.system_lang_code)
                    self.step.elapsedMs = int((time.time() - start_time) * 1000)
                    self.step.status = StepStatusType.SUCCEEDED
                    self.qa.answer.append(self.step)
                    await self.qa.save()

        elif msg_type == 'research_decomposition':
            if self.in_research_decomposition is None:
                yield StreamResponse(type=StepType.RESEARCH_DECOMPOSITION, status=StreamStatusType.START, qaId=self.qa.id, sessionId=self.session.id).model_dump_json(exclude={'deliver', 'save'})
                self.step = StepModel(type=StepType.RESEARCH_DECOMPOSITION)
                for chunk in stream_content(StepType.TITLE, content=content):
                    yield chunk
                concat_content(StepType.TITLE, content=content)
                self.in_research_decomposition = True
            else:
                if step_type == StepType.TITLE_CORRECTION:
                    yield StreamResponse(type=StepType.TITLE_CORRECTION, status=StreamStatusType.PENDING, content=content, qaId=self.qa.id, sessionId=self.session.id).model_dump_json(exclude={'deliver', 'save'})
                    yield StreamResponse(type=StepType.RESEARCH_DECOMPOSITION, status=StreamStatusType.END, qaId=self.qa.id, sessionId=self.session.id).model_dump_json(exclude={'deliver', 'save'})
                    self.step.step[StepType.TITLE_CORRECTION] = content
                    self.step.elapsedMs = int((time.time() - start_time) * 1000)
                    self.step.status = StepStatusType.SUCCEEDED
                    self.qa.answer.append(self.step)
                    await self.qa.save()
                else:
                    for chunk in stream_content(StepType.CONTENT, content=content, chunk_size=10):
                        yield chunk
                    concat_content(StepType.CONTENT, content=content)

        elif msg_type == 'progress':
            # 首个开始
            if self.in_progress is None:
                self.step = StepModel(type=StepType.PROGRESS)
                yield StreamResponse(type=StepType.PROGRESS, status=StreamStatusType.START, qaId=self.qa.id, sessionId=self.session.id).model_dump_json(exclude={'deliver', 'save'})
                for chunk in stream_content(StepType.TITLE, content=content):
                    yield chunk
                concat_content(StepType.TITLE, content=content)
                self.in_progress = True
            else:
                if step_type == StepType.TITLE_CORRECTION:
                    yield StreamResponse(type=StepType.TITLE_CORRECTION, status=StreamStatusType.PENDING, content=content, qaId=self.qa.id, sessionId=self.session.id).model_dump_json(exclude={'deliver', 'save'})
                else:
                    # 结束上一个progress步骤
                    yield StreamResponse(type=StepType.PROGRESS, status=StreamStatusType.END, qaId=self.qa.id, sessionId=self.session.id).model_dump_json(exclude={'deliver', 'save'})
                    self.step.elapsedMs = int((time.time() - start_time) * 1000)
                    self.step.status = StepStatusType.SUCCEEDED
                    self.qa.answer.append(self.step)
                    await self.qa.save()

                    # 开始进入新的progress步骤
                    self.step = StepModel(type=StepType.PROGRESS)
                    yield StreamResponse(type=StepType.PROGRESS, status=StreamStatusType.START, qaId=self.qa.id, sessionId=self.session.id).model_dump_json(exclude={'deliver', 'save'})
                    for chunk in stream_content(StepType.TITLE, content=content):
                        yield chunk
                    concat_content(StepType.TITLE, content=content)

        elif msg_type == 'report':
            # 检测内容风控拦截 - 复用 ai-web3-tradding-agent 的翻译和 block answer 机制
            if raw_status == 'BLOCKED_ANSWER':
                logger.warning(f"[Deep Research] 检测到内容风控拦截 (status=BLOCKED_ANSWER)")
                
                # ai-deep-research 只返回 blocked 标记，不返回翻译好的消息
                msg_template = translate(self.system_lang_code, "21109315dbba4000a894", "conf/i18n/llm_shield")
                category = translate(self.system_lang_code, "a89e495ae4f84000a024", "conf/i18n/llm_shield")
                msg =  msg_template.format(category=category)
                # logger.info(f"[Deep Research] 生成拦截消息 (language={language_code}): {msg}")

                from web.exceptions import RiskException
                raise RiskException(
                    code=200001,
                    msg=msg,
                    raise_user=False
                )            
            if self.in_report is None:
                # 结束上一个progress步骤
                yield StreamResponse(type=StepType.PROGRESS, status=StreamStatusType.END, qaId=self.qa.id, sessionId=self.session.id).model_dump_json(exclude={'deliver', 'save'})
                self.step.elapsedMs = int((time.time() - start_time) * 1000)
                self.step.status = StepStatusType.SUCCEEDED
                self.qa.answer.append(self.step)
                await self.qa.save()

                # 开始进入report步骤
                self.step = StepModel(type=StepType.REPORT)
                yield StreamResponse(type=StepType.REPORT, status=StreamStatusType.START, qaId=self.qa.id, sessionId=self.session.id).model_dump_json(exclude={'deliver', 'save'})
                for chunk in stream_content(StepType.TITLE, content=content):
                    yield chunk
                concat_content(StepType.TITLE, content=content)
                self.in_report = True
                
            else:
                if step_type == StepType.TITLE_CORRECTION:
                    yield StreamResponse(type=StepType.TITLE_CORRECTION, status=StreamStatusType.PENDING, content=content, qaId=self.qa.id, sessionId=self.session.id).model_dump_json(exclude={'deliver', 'save'})
                    # 结束report步骤
                    yield StreamResponse(type=StepType.REPORT, status=StreamStatusType.END, qaId=self.qa.id, sessionId=self.session.id).model_dump_json(exclude={'deliver', 'save'})
                    self.step.step[StepType.TITLE_CORRECTION] = content
                    self.step.elapsedMs = int((time.time() - start_time) * 1000)
                    self.step.status = StepStatusType.SUCCEEDED
                    self.qa.answer.append(self.step)
                    await self.qa.save()
                elif step_type == StepType.CONTENT_CORRECTION:
                    yield StreamResponse(type=StepType.CONTENT_CORRECTION, status=StreamStatusType.PENDING, content=content, qaId=self.qa.id, sessionId=self.session.id).model_dump_json(exclude={'deliver', 'save'})
                    self.step.step[StepType.CONTENT_CORRECTION] = content
                else:
                    # 流式输出报告的速度由deep research服务控制，这里只负责转发流式输出
                    yield StreamResponse(type=StepType.CONTENT, content=content, qaId=self.qa.id, sessionId=self.session.id).model_dump_json(exclude={'deliver', 'save'})
                    concat_content(StepType.CONTENT, content=content)
                    # 累积报告内容用于币种提取
                    self.cache['report_content'] += content
        
        elif msg_type == 'citations':
            # 开始进入citations步骤
            content = data.get('citations', [])
            if content:
                self.step = StepModel(type=StepType.CITATIONS)
                yield StreamResponse(type=StepType.CITATIONS, status=StreamStatusType.START, qaId=self.qa.id, sessionId=self.session.id).model_dump_json(exclude={'deliver', 'save'})
                yield StreamResponse(type=StepType.CONTENT, content=content, qaId=self.qa.id, sessionId=self.session.id).model_dump_json(exclude={'deliver', 'save'})
                tmp = self.step.step.get(StepType.CONTENT)
                if tmp is None:
                    self.step.step[StepType.CONTENT] = []
                self.step.step[StepType.CONTENT].extend(content)

                # 结束citations步骤
                yield StreamResponse(type=StepType.CITATIONS, status=StreamStatusType.END, qaId=self.qa.id, sessionId=self.session.id).model_dump_json(exclude={'deliver', 'save'})
                self.step.elapsedMs = int((time.time() - start_time) * 1000)
                self.step.status = StepStatusType.SUCCEEDED
                self.qa.answer.append(self.step)
                logger.info(f"Save citations, step={self.step.model_dump()}")
                await self.qa.save()
                logger.info(f"Saving qa: {self.qa.model_dump()}")

        else:
            # URL、LEARNING等中间过程速度较慢，按10个char拼接为chunk进行流式输出
            for chunk in stream_content(StepType.CONTENT, content=content, chunk_size=10):
                yield chunk
            concat_content(StepType.CONTENT, content=content)

    async def _fallback_generate_report(self, user_query, reply_language):
        """Deep research service unavailable -- run ReAct loop + generate report locally.

        Phase 1: Multi-dimensional data gathering via the ReAct loop.
                 The LLM autonomously decides which tools to call (coin_screener,
                 web_search with different angles, get_crypto_market_data, etc.)
                 and iterates until it has enough information.
        Phase 2: Generate a structured research report from all collected data.
        Phase 3: Post-processing (citations, currency suggestions).
        """
        # Phase 1 — ReAct multi-tool research
        async for event in self._react_run(
            query=user_query,
            history=self.history,
            max_iterations=5,
        ):
            yield event

        # Phase 2 — Generate structured report using REPORT step type
        async for event in self._stream_report_response(user_query, reply_language):
            yield event

        # Phase 3 — Citations + currency suggestions
        report_content = self.cache.get("report_content", "")
        async for event in self._generate_final_citations(report_content):
            yield event
        async for event in self._extract_currency_suggestions(report_content):
            yield event

    async def _stream_report_response(self, user_query, reply_language):
        """Stream a structured research report through the REPORT step type.

        Reads all accumulated tool results from the ReAct loop and feeds them
        to the LLM with *deep_research_report_prompt* to produce a professional
        research report.
        """
        start_time = time.time()
        step = StepModel(type=StepType.REPORT)
        self.cache["report_content"] = ""

        # REPORT START
        yield StreamResponse(
            type=StepType.REPORT, status=StreamStatusType.START,
            qaId=self.qa.id, sessionId=self.session.id,
        ).model_dump_json(exclude={"deliver", "save"})

        # Report title
        title = get_localized_message("generating_answer_start", self.system_lang_code)
        yield StreamResponse(
            type=StepType.TITLE, status=StreamStatusType.PENDING,
            content=title, qaId=self.qa.id, sessionId=self.session.id,
        ).model_dump_json(exclude={"deliver", "save"})
        step.step[StepType.TITLE] = title

        # Build messages with ALL accumulated tool results
        messages = await self._build_report_messages(user_query)

        # Prepare system prompt variables
        now = datetime.now()
        memory = await self._get_memory(user_query)
        system_prompt_vars = {
            "reply_language": reply_language,
            "current_date": now.strftime("%Y-%m-%d"),
            "current_year": now.year,
            "current_month": now.strftime("%B"),
            "memory": memory,
            "max_response_tokens": 6000,
        }

        # Stream LLM report generation
        async for content in final_response(
            client=self.llm,
            messages=messages,
            model=self.model_name,
            system_prompt_name="deep_research_report_prompt",
            system_prompt_vars=system_prompt_vars,
            max_tokens=8000,
            temperature=0.7,
            timeout=config.llm_stream_timeout or 120.0,
            extra_body=None if config.use_azure_openai else {
                "chat_template_kwargs": {"enable_thinking": False},
            },
        ):
            yield StreamResponse(
                type=StepType.CONTENT, status=StreamStatusType.PENDING,
                content=content, qaId=self.qa.id, sessionId=self.session.id,
            ).model_dump_json(exclude={"deliver", "save"})
            self.cache["report_content"] += content

        # TITLE_CORRECTION + REPORT END
        title_correction = get_localized_message("generating_answer_end", self.system_lang_code)
        yield StreamResponse(
            type=StepType.TITLE_CORRECTION, status=StreamStatusType.PENDING,
            content=title_correction, qaId=self.qa.id, sessionId=self.session.id,
        ).model_dump_json(exclude={"deliver", "save"})

        yield StreamResponse(
            type=StepType.REPORT, status=StreamStatusType.END,
            qaId=self.qa.id, sessionId=self.session.id,
        ).model_dump_json(exclude={"deliver", "save"})

        # Save step
        step.step[StepType.TITLE_CORRECTION] = title_correction
        step.step[StepType.CONTENT] = self.cache["report_content"]
        step.elapsedMs = int((time.time() - start_time) * 1000)
        step.status = StepStatusType.SUCCEEDED
        self.qa.answer.append(step)
        await self.qa.save()

    async def _build_report_messages(self, user_query):
        """Combine conversation history and ALL ReAct tool results into messages
        for the report-generation LLM call."""
        messages = []
        if self.history:
            context_payload = await self._prepare_context(
                history=self.history,
                history_turns=4,
                current_query_tokens=estimate_tokens(user_query or ""),
            )
            messages.extend(context_payload.get("messages", []))
        messages.append({"role": "user", "content": user_query})

        # Combine all ReAct tool results into research context
        react_results = self.cache.get("react_tool_results", [])
        if react_results:
            sections = []
            for r in react_results:
                content = r.get("content", "")
                if content:
                    sections.append(f"[{r.get('name', 'unknown')}]\n{content}")
            combined = "\n\n---\n\n".join(sections)
            messages.append({
                "role": "assistant",
                "content": "I conducted multi-dimensional research and gathered the following data:",
            })
            messages.append({
                "role": "user",
                "content": (
                    f"Research data:\n\n{combined}\n\n"
                    "Based on all the data above, generate a comprehensive research report."
                ),
            })
        elif self.cache.get("tools_result"):
            # Fallback: use last tool result if react_tool_results is empty
            tools_text = "\n".join(
                r.get("text", "") for r in self.cache["tools_result"] if r.get("text")
            )
            if tools_text:
                messages.append({
                    "role": "assistant",
                    "content": "I conducted research and gathered the following data:",
                })
                messages.append({
                    "role": "user",
                    "content": (
                        f"Research data:\n\n{tools_text}\n\n"
                        "Based on the data above, generate a comprehensive research report."
                    ),
                })
        return messages

    async def _generate_research_query_from_history(self, user_query: str, history) -> dict:
        """
        根据历史对话上下文生成用于深度研究的查询
        
        当历史中已经包含澄清问题时，调用此函数从历史上下文中梳理并生成一个清晰的研究查询。
        
        Args:
            user_query: 当前用户查询
            history: 对话历史
            
        Returns:
            dict: 包含 research_query 和 model_detected_language 的字典
        """
        try:
            system_prompt = await mcp_client.get_prompt(
                name='clarify_research_confirm_again_prompt'
            )

            # 构建对话
            messages = [{"role": "system", "content": system_prompt}]
            if history:
                context_payload = await self._prepare_context(
                    history=history,
                    history_turns=6,
                    current_query_tokens=estimate_tokens(user_query or ""),
                )
                messages.extend(context_payload.get("messages", []))
            messages.append({"role": "user", "content": user_query})

            # 定义工具
            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "generate_research_query",
                        "description": "Generate a clear, comprehensive research query based on conversation history and detect the language of the user's query.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "research_query": {
                                    "type": "string",
                                    "description": "The final, clarified research query ready for deep analysis. Combine the original question with any clarifications from conversation history into a single, clear research query. IMPORTANT: The research_query MUST be in the same language as the user's current query. This field must not be empty."
                                },
                                "model_detected_language": {
                                    "type": "string",
                                    "description": "The language detected from the user's query or the language the user wants to reply in. If the user's input language or the language the user wants to reply in is listed in the supported languages, the value should exactly match the language name from this list. Supported languages: " + ", ".join([name for name in ENGLISH_NAME_TO_CODE_MAP.keys()])
                                }
                            },
                            "required": ["research_query", "model_detected_language"]
                        }
                    }
                }
            ]

            extra_body = None if config.use_azure_openai else {
                "chat_template_kwargs": {"enable_thinking": False},
            }

            response = await self.llm.chat.completions.create(
                model=self.model_name,
                messages=messages,
                tools=tools,
                tool_choice={
                    "type": "function",
                    "function": {"name": "generate_research_query"}
                },
                max_tokens=500,
                temperature=0.3,
                timeout=config.llm_api_timeout or 30.0,
                extra_body=extra_body
            )

            choice = response.choices[0]
            
            if choice.message.tool_calls:
                tool_call = choice.message.tool_calls[0]
                if tool_call.function.name == "generate_research_query":
                    try:
                        # 清理可能存在的 <tool_call> 标签
                        cleaned_arguments = clean_tool_call_tags(tool_call.function.arguments)
                        if 'arguments' in cleaned_arguments:
                            result = json.loads(cleaned_arguments).get("arguments", {})
                        else:
                            result = json.loads(cleaned_arguments)
                        
                        research_query = result.get("research_query", "")
                        model_detected_language = result.get("model_detected_language", "")
                        
                        if research_query:
                            logger.info(f"Generated research query from history: {research_query}, language: {model_detected_language}")
                            return {
                                "research_query": research_query,
                                "model_detected_language": model_detected_language
                            }
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse research query result JSON: {e}")
            
            # 回退到默认值
            logger.warning("Failed to generate research query from history, using original user_query")
            return {
                "research_query": user_query,
                "model_detected_language": ""
            }
                
        except Exception as e:
            logger.exception(f"Failed to generate research query from history: {e}")
            return {
                "research_query": user_query,
                "model_detected_language": ""
            }

    @save_step(stream_type=StepType.QUERY_CLARIFY)
    async def _clarify_question(
        self,
        user_query: str,
        history=None,
    ):
        """
        澄清深度研究问题
        
        分析用户查询是否足够具体和清晰以进行深度研究，如果不够清晰则生成澄清问题。
        
        Args:
            user_query: 用户查询
            history: 对话历史
            
        Returns:
            Dict: 包含澄清结果的结构化数据
        """
        async def clarify_question():
            system_prompt = await mcp_client.get_prompt(
                name='clarify_research_prompt'
            )

            # 构建对话
            messages = [{"role": "system", "content": system_prompt}]
            if history:
                context_payload = await self._prepare_context(
                    history=history,
                    history_turns=6,
                    current_query_tokens=estimate_tokens(user_query or ""),
                )
                history_messages = context_payload.get("messages", [])
                if history_messages:
                    context.get("kia_memory").history[HistoryStepType.QUERY_CLARIFY] = history_messages
                messages.extend(history_messages)
            messages.extend([{"role": "user", "content": user_query}])

            # 定义工具
            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "evaluate_research_readiness",
                        "description": "Evaluate whether the user's query is ready for deep cryptocurrency research. Determine if the question is clear and specific enough, or if it needs clarification. For non-crypto topics, you MUST provide appropriate responses and guide users toward relevant research topics.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "is_ready_for_research": {
                                    "type": "boolean",
                                    "description": "Whether the user's query is ready for deep research. Set to True if the question is cryptocurrency-related, clear, and specific enough for research. Set to False if clarification is needed, the topic is not crypto-related, or it's casual conversation."
                                },
                                "response_to_user": {
                                    "type": "string",
                                    "description": "Response to send to the user. If is_ready_for_research is False and clarification is needed, ask 1-3 focused questions to narrow down the research scope. Use line breaks (\\n) to separate each question. If the topic is not crypto-related, respond naturally and guide toward crypto topics. If is_ready_for_research is False, this field can not be empty, you MUST provide appropriate responses and guide users toward relevant research topics. If is_ready_for_research is True, this field can be empty."
                                },
                                "research_query": {
                                    "type": "string",
                                    "description": "The final, clarified research query ready for deep analysis. Only populate this field when is_ready_for_research is True. If is_ready_for_research is True, this field must not be empty. Combine original question with any clarifications from conversation history into a single, clear research query. "
                                },
                                "evaluation_reasoning": {
                                    "type": "string",
                                    "description": "Brief explanation of why the query is considered ready for research or needs clarification. Reference the user's query and conversation context."
                                },
                                "model_detected_language": {
                                    "type": "string",
                                    "description": "The language detected from the user's query or the language the user want to reply in. If the user's input language or the language the user want to reply in is listed in the supported languages, the value should exactly match the language name from this list. Supported languages: " + ", ".join([name for name in ENGLISH_NAME_TO_CODE_MAP.keys()])
                                }
                            },
                            "required": ["is_ready_for_research", "evaluation_reasoning", "model_detected_language"]
                        }
                    }
                }
            ]

            try:
                extra_body = None if config.use_azure_openai else {
                    "chat_template_kwargs": {"enable_thinking": False},
                }
                
                response = await self.llm.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    tools=tools,
                    tool_choice={
                        "type": "function",
                        "function": {"name": "evaluate_research_readiness"}
                    },
                    max_tokens=800,
                    temperature=0.3,
                    timeout=config.llm_api_timeout or 30.0,
                    extra_body=extra_body
                )

                choice = response.choices[0]
                
                if choice.message.tool_calls:
                    tool_call = choice.message.tool_calls[0]
                    if tool_call.function.name == "evaluate_research_readiness":
                        try:
                            # 清理可能存在的 <tool_call> 标签
                            cleaned_arguments = clean_tool_call_tags(tool_call.function.arguments)
                            if 'arguments' in cleaned_arguments:
                                result = json.loads(cleaned_arguments).get("arguments", {})
                            else:
                                result = json.loads(cleaned_arguments)
                            
                            # 根据工具定义的参数名解析结果
                            clarification_result = {
                                "is_ready_for_research": result.get("is_ready_for_research", False),
                                "response_to_user": result.get("response_to_user", ""),
                                "research_query": result.get("research_query", ""),
                                "evaluation_reasoning": result.get("evaluation_reasoning", ""),
                                "model_detected_language": result.get("model_detected_language", "")
                            }
                            
                            logger.info(f"Question clarification analysis: is_ready_for_research={clarification_result['is_ready_for_research']}")
                            return clarification_result
                            
                        except json.JSONDecodeError as e:
                            logger.error(f"Failed to parse clarification result JSON: {e}")
                
                # 回退到默认策略
                logger.warning("Failed to get structured clarification result, using fallback")
                return {
                    "is_ready_for_research": False,
                    "response_to_user": '\n'.join([
                        "1. What timeframe are you interested in? (short-term, medium-term, or long-term)",
                        "2. Which aspect interests you most? (price analysis, technical development, market sentiment, etc.)",
                        "3. What's your research purpose? (investment decision, academic research, risk assessment, etc.)",
                    ]),
                    "research_query": "",
                    "evaluation_reasoning": "Using default clarification strategy",
                    "model_detected_language": "",
                }
                
            except Exception as e:
                logger.exception(f"Question clarification failed")
                return {
                    "is_ready_for_research": False,
                    "response_to_user": "",
                    "research_query": "",
                    "evaluation_reasoning": "",
                    "model_detected_language": "",
                }

        clarification_result = await clarify_question()
        logger.info(f"clarification_result: {clarification_result}")
        self.cache["clarification_result"] = clarification_result
        response_to_user = clarification_result.get('response_to_user') if clarification_result.get('response_to_user') else 'Your question does not seem to be related to cryptocurrency or investment research. If you have any questions about digital assets, market trends, or investment strategies, I’d be happy to assist you.'
        if not clarification_result.get('is_ready_for_research', False):
            async for event in self._typing_effect.stream_text(response_to_user, "text", 0.001):
                yield StreamResponse(
                    type=StepType.CONTENT,
                    content=json.loads(event).get("data", "")
                )
        