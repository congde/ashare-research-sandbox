# -*- coding: utf-8 -*-
"""
ResponseMixin — final response generation, citations, currency extraction, follow-up questions.

Methods extracted from BaseAgent for readability.
"""

import asyncio
import json
import logging
import random
import re
import time
import traceback
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from pathlib import Path

from pydantic import BaseModel

from agent.schema import (
    StepType,
    StepModel,
    StepStatusType,
    StreamResponse,
    StreamStatusType,
    HistoryStepType,
    MemoryModel,
    ReferenceType,
    ResourceReference,
    response_event
)
from agent.plan.decorators import save_step, StopError
from agent.utils import jinja_render, truncate_message, truncate_web_search_query, CustomTableStreamProcessor
from libs.language import (
    get_localized_message,
    detect_chinese_variant,
    LANGUAGE_CODE_TO_NAME_MAP,
    ENGLISH_NAME_TO_CODE_MAP,
    ENGLISH_NAME_TO_CODE_LOCAL_MAP,
    KB_SEARCH_ENGLISH_NAME_TO_CODE_MAP,
)
from libs.citation_processor import CitationProcessor
from libs.crypto_extractor import crypto_extractor
from llm.llm import final_response
from mcp.mcp_http_client import mcp_client
from agent.context.token_budget import estimate_tokens
from web.config import config
from web.context import context
from web.exceptions import RiskException
from web import code_msg
from agent.plan.task_graph import TaskStatus
from agent.dag_execution import DAGPlan, DAGTask
from llm.llm import llm

logger = logging.getLogger(__name__)


class FollowUpQuestionsIndex(BaseModel):
    indices: List[int] = []


class ResponseMixin:
    """Provides final response generation, post-processing (citations, currency, follow-up), and fallback."""

    _REFERENCE_SOURCE_NAME = ('coin_screener', 'recharge_and_withdraw')

    # ------------------------------------------------------------------
    # A: StreamResponse boilerplate helper
    # ------------------------------------------------------------------

    def _stream_json(self, *, status, type, content=None, log=None, **kw) -> str:
        """Build a StreamResponse, serialize to JSON, and return the string."""
        kwargs = dict(sessionId=self.session.id, qaId=self.qa.id, status=status, type=type)
        if content is not None:
            kwargs["content"] = content
        if log is not None:
            kwargs["log"] = log
        kwargs.update(kw)
        return StreamResponse(**kwargs).model_dump_json(exclude={"save", "deliver"})

    # ------------------------------------------------------------------
    # Properties / small helpers
    # ------------------------------------------------------------------

    @property
    def plan(self):
        return self.cache.get("plan", DAGPlan(tasks=[DAGTask(id="default", name="direct response", tool="direct_response", output_key="")]))

    def _get_prompt_tools_info(self):
        tools_dir = Path(__file__).parent.parent / "prompt"
        filtered_tools_info = {}
        for task in self.plan.tasks:
            tool_name = task.tool_name
            if (tools_dir / tool_name).exists() or (tools_dir / f"{tool_name}.md").exists():
                filtered_tools_info[tool_name] = task.result
        return filtered_tools_info

    def _concat_content(self, step_model, step_type, content=""):
        tmp = step_model.step.get(step_type)
        if tmp is None:
            step_model.step[step_type] = ""
        step_model.step[step_type] += content

    def _has_tool_names(self, tools_name: List[str]) -> bool:
        for task in self.plan.tasks:
            if task.tool_name in tools_name:
                return True
        return False

    def _get_reply_tools(self):
        """Partition plan tasks into KB-reply tools and other tools."""
        reply_tools, other_tools = [], []
        for task in self.plan.tasks:
            if task.enable_reply and task.status == TaskStatus.COMPLETED:
                reply_tools.append(task)
            else:
                other_tools.append(task)
        if other_tools:
            self.plan.tasks = other_tools
        return reply_tools, other_tools

    # ------------------------------------------------------------------
    # Decorated post-processing generators
    # ------------------------------------------------------------------

    @save_step(stream_type=StepType.QUERY_FOLLOWUP_SUGGESTIONS)
    async def _generate_follow_up_questions(self, user_query, history, language):
        response = self.cache.get("corrected_response", "")
        if not response:
            response = self.cache.get("full_response", "")

        if response and response.strip() and len(response.strip()) > 20 or self.cache.get("follow_up_questions"):
            logger.info("Generating follow-up questions...")

            follow_up_questions = await self.generate_follow_up_questions(
                user_query=user_query,
                history=history,
                assistant_response=response,
                language=language,
            )
            if follow_up_questions:
                logger.info(
                    f"Generated {len(follow_up_questions)} follow-up questions, "
                    f"assistant_response: {response}"
                     f"\nfollow_up_questions: {follow_up_questions}"
                )
                follow_up_questions = await self.check_follow_up_questions(follow_up_questions)
                yield StreamResponse(
                    type=StepType.CONTENT,
                    content=follow_up_questions
                )

    @save_step(stream_type=StepType.CITATIONS)
    async def _generate_final_citations(self, full_response):
        final_citations = self.cache.get("final_citations")
        if final_citations:
            logger.info(f"final_citations={final_citations}")
            yield StreamResponse(
                type=StepType.CONTENT,
                content=final_citations
            )

    @save_step(stream_type=StepType.CURRENCY_FOLLOWUP_SUGGESTIONS)
    async def _extract_currency_suggestions(self, full_response):
        """从用户查询和Agent回复中提取币种信息。优先使用 plan 实际执行的 symbol（cache 注入）。"""
        if not full_response:
            return

        extracted_symbols = self.cache.get("currency_suggestions_symbols")
        if not extracted_symbols:
            extracted_symbols = await crypto_extractor.extract_with_llm(
                self.llm, self.model_name, self.query, full_response
            )
        logger.info(f"Extracted symbols: {extracted_symbols}")
    
        if extracted_symbols:
            reply_language = self.cache.get("reply_language", "English")
            lang_code = ENGLISH_NAME_TO_CODE_MAP.get(reply_language, self.system_lang_code or "en")
        
            yield StreamResponse(
                type=StepType.TITLE,
                content=get_localized_message("currency_suggestions_title", lang_code)
            )
            yield StreamResponse(
                type=StepType.CONTENT,
                content=extracted_symbols
            )

    # ------------------------------------------------------------------
    # Fallback pipeline
    # ------------------------------------------------------------------

    async def _fallback_via_web_search(
        self,
        user_query: str,
        reply_language: str,
        *,
        enable_think: bool = False,
        include_follow_up: bool = True,
    ):
        """统一降级路径: web_search → LLM → 后处理。"""
        tool_decision = {
            "tool_call": {
                "name": "web_search",
                "arguments": json.dumps({"query": truncate_web_search_query(user_query)}),
            }
        }

        async for event in self._call_tools(
            tool_decision, user_query, reply_language,
            step=StepModel(type=StepType.TOOL_EXECUTION),
        ):
            yield event

        async for event in self._generate_final_response(
            user_query, self.cache.get("tools_result"), self.history,
            reply_language, enable_think=enable_think,
        ):
            yield event

        async for event in self._generate_final_citations(
            self.cache.get("full_response", ""),
        ):
            yield event

        async for event in self._extract_currency_suggestions(
            self.cache.get("full_response", ""),
        ):
            yield event

        if include_follow_up:
            async for event in self._generate_follow_up_questions(
                user_query, self.history, reply_language,
            ):
                yield event

    # ==================================================================
    # _generate_final_response — orchestrator
    # ==================================================================

    async def _generate_final_response(self, query, tools_result, history, reply_language,
                                       enable_think=False, enable_research=False):
        start_time = time.time()
        tools_name = [task.tool_name for task in self.plan.tasks]
        resource_references = self.plan.resource_references

        # 1) Resource reference cards → custom_table_processor
        custom_table_processor = None
        if resource_references:
            yield self._stream_json(
                status=StreamStatusType.END, type=StepType.RESOURCE_REFERENCE,
                content=resource_references, checkSensitive=False,
            )
            custom_table_processor = await self._save_resource_step_and_build_processor(
                resource_references, start_time,
            )

        # 2) KB direct-reply (short-circuits if handled)
        has_kb, kb_events = await self._try_kb_direct_reply()
        for event in kb_events:
            yield event
        if has_kb:
            return

        # 3) Guard: nothing to generate
        has_web_search_fallback = self.cache.get("tool_name", "") == "web_search"
        if not self._get_other_tools_exist() and not has_web_search_fallback:
            return
        if has_web_search_fallback:
            logger.info("[_generate_final_response] KB returned empty, using web_search fallback for LLM response")

        # direct_response processor fallback
        if len(tools_name) == 1 and 'direct_response' in tools_name and self.plan.tasks:
            custom_table_processor = CustomTableStreamProcessor(
                tag_names=["custom_table", "custom_card"],
                event_id=self.plan.tasks[0].tool_call_id,
            )

        # 4) Stream LLM response (thinking + answering)
        is_answering = not enable_think
        step_deep_think = StepModel(type=StepType.DEEP_THINK)
        step_answer_response = StepModel(type=StepType.ANSWER_RESPONSE)

        try:
            # 4a) Emit deep-think start header
            if enable_think:
                yield self._stream_json(status=StreamStatusType.START, type=StepType.DEEP_THINK)
                async for event in self._yield_thinking_title(step="deep_think_start"):
                    yield self._stream_json(
                        status=StreamStatusType.PENDING, type=StepType.TITLE, content=event,
                    )
                    self._concat_content(step_deep_think, StepType.TITLE, content=event)

            # 4b) Build LLM messages + system prompt vars
            messages, system_prompt_vars = await self._build_llm_context(
                query, tools_result, history, reply_language,
                enable_think, has_web_search_fallback,
            )

            # 4c) Stream LLM chunks — thinking / answering separation
            ready_to_send_answer = not enable_think
            from llm.llm import qwen_extra_body
            async for content in final_response(
                client=self.llm,
                messages=messages,
                model=self.model_name,
                extra_body=qwen_extra_body(
                    self.model_name or "",
                    enable_thinking=enable_think,
                    enable_research=enable_research,
                ),
                timeout=config.llm_stream_timeout or 60.0,
                max_tokens=12000 if enable_think else 6000,
                temperature=0 if self._has_tool_names(self._REFERENCE_SOURCE_NAME) else 0.7,
                system_prompt_name=self.cache.get("dag_response_prompt_name") or "final_response_prompt",
                system_prompt_vars=system_prompt_vars
            ):
                # -- <think> opening tag --
                if enable_think and not is_answering and "<think>" in content:
                    content = content.replace("<think>", "", 1)
                    if not content:
                        continue

                # -- </think> closing tag → finalize thinking, transition to answering --
                if enable_think and not is_answering and "</think>" in content:
                    before_tag, _, after_tag = content.partition("</think>")
                    async for ev in self._finalize_thinking_step(
                        step_deep_think, before_tag, start_time,
                    ):
                        yield ev
                    ready_to_send_answer = True
                    is_answering = True
                    content = after_tag
                    if not content:
                        continue

                # -- First answer chunk: emit ANSWER_RESPONSE start --
                if ready_to_send_answer:
                    ready_to_send_answer = False
                    yield self._stream_json(status=StreamStatusType.START, type=StepType.ANSWER_RESPONSE)
                    async for event in self._yield_thinking_title(step="generating_answer_start"):
                        yield self._stream_json(
                            status=StreamStatusType.PENDING, type=StepType.TITLE, content=event,
                        )
                        self._concat_content(step_answer_response, StepType.TITLE, content=event)

                # -- Route chunk to answer (with card processing) or thinking --
                if is_answering and custom_table_processor:
                    for pc in custom_table_processor.process(content):
                        if pc:
                            yield self._stream_json(
                                status=StreamStatusType.PENDING, type=StepType.CONTENT, content=pc,
                            )
                            self._concat_content(step_answer_response, StepType.CONTENT, content=pc)
                else:
                    if content or is_answering:
                        yield self._stream_json(
                            status=StreamStatusType.PENDING, type=StepType.CONTENT, content=content,
                        )
                    if is_answering:
                        self._concat_content(step_answer_response, StepType.CONTENT, content=content)
                    else:
                        self._concat_content(step_deep_think, StepType.CONTENT, content=content)

            # 4d) Flush remaining custom-table buffer
            if custom_table_processor:
                remaining = custom_table_processor.flush()
                if remaining:
                    yield self._stream_json(
                        status=StreamStatusType.PENDING, type=StepType.CONTENT, content=remaining,
                    )
                    self._concat_content(step_answer_response, StepType.CONTENT, content=remaining)

            # 4e) Append missing card placeholders (multi-card scenario)
            if len(resource_references) > 1:
                async for ev in self._append_missing_card_placeholders(
                    resource_references, step_answer_response,
                ):
                    yield ev

            logger.info("Streaming response completed")

            # 5) Fallbacks for edge cases
            self._apply_answer_fallbacks(step_deep_think, step_answer_response, enable_think)

            # 6) Transcript shadow-write
            await self._write_transcript(step_answer_response)

            # 7) Citation processing + CONTENT_CORRECTION
            for ev in await self._process_citations(step_answer_response):
                yield ev

            # 8) Finalize answer step
            yield self._stream_json(
                status=StreamStatusType.PENDING, type=StepType.TITLE_CORRECTION,
                content=get_localized_message("generating_answer_end", self.system_lang_code),
            )
            yield self._stream_json(status=StreamStatusType.END, type=StepType.ANSWER_RESPONSE)
            step_answer_response.step[StepType.TITLE_CORRECTION] = get_localized_message(
                "generating_answer_end", self.system_lang_code,
            )
            step_answer_response.elapsedMs = int((time.time() - start_time) * 1000)
            step_answer_response.status = StepStatusType.SUCCEEDED
            self.qa.answer.append(step_answer_response)
            await self.qa.save()

        except asyncio.CancelledError:
            raise
        except RiskException:
            raise
        except Exception as e:
            logger.exception('_generate_final_response error')
            msg = self._format_stream_error(e, reply_language)
            if is_answering:
                yield self._stream_json(
                    status=StreamStatusType.FAILED, type=StepType.ANSWER_RESPONSE, log=msg,
                )
                step_answer_response.status = StepStatusType.FAILED
                step_answer_response.log = msg
                self.qa.answer.append(step_answer_response)
            else:
                yield self._stream_json(
                    status=StreamStatusType.FAILED, type=StepType.DEEP_THINK, log=msg,
                )
                step_deep_think.status = StepStatusType.FAILED
                step_deep_think.log = msg
                self.qa.answer.append(step_deep_think)
            await self.qa.save()
            raise StopError from e
        finally:
            self._step_log(int((time.time() - start_time) * 1000), "_generate_final_response")

    # ==================================================================
    # B: Extracted sub-methods of _generate_final_response
    # ==================================================================

    async def _save_resource_step_and_build_processor(
        self, resource_references, start_time,
    ) -> CustomTableStreamProcessor:
        """Save RESOURCE_REFERENCE step to QA and build the custom-table stream processor."""
        step = StepModel(type=StepType.RESOURCE_REFERENCE)
        step.step[StepType.CONTENT] = resource_references
        step.elapsedMs = int((time.time() - start_time) * 1000)
        step.status = StepStatusType.SUCCEEDED
        self.qa.answer.append(step)
        self.qa.resourceReference = resource_references
        await self.qa.save()

        _REF_TYPE_TO_TAG = {"CUSTOM_TABLE": "custom_table", "CUSTOM_CARD": "custom_card"}
        tag_names_ordered: list[str] = []
        tag_event_ids_raw: dict[str, list[str]] = {}
        for ref in resource_references:
            ref_type = ref.get("type") or ""
            ref_type_str = ref_type.value if hasattr(ref_type, "value") else str(ref_type)
            tag_name = _REF_TYPE_TO_TAG.get(ref_type_str, ref_type_str.lower())
            if tag_name not in tag_event_ids_raw:
                tag_names_ordered.append(tag_name)
                tag_event_ids_raw[tag_name] = []
            tag_event_ids_raw[tag_name].append(ref["eventId"])

        tag_event_ids: dict[str, str | list[str]] = {
            k: (v[0] if len(v) == 1 else v) for k, v in tag_event_ids_raw.items()
        }
        tag_event_ids_for_processor = {
            k: (list(v) if isinstance(v, list) else v) for k, v in tag_event_ids.items()
        }
        if len(tag_names_ordered) == 1 and not isinstance(tag_event_ids.get(tag_names_ordered[0]), list):
            processor = CustomTableStreamProcessor(
                tag_name=tag_names_ordered[0],
                event_id=tag_event_ids_for_processor[tag_names_ordered[0]],
            )
        else:
            processor = CustomTableStreamProcessor(
                tag_names=tag_names_ordered,
                tag_event_ids=tag_event_ids_for_processor,
            )
        logger.info(f"[RESOURCE_REFERENCE] {len(resource_references)} card(s) generated")
        return processor

    async def _try_kb_direct_reply(self) -> tuple[bool, list]:
        """Check if KB tools can handle the reply directly.

        Returns:
            (handled, stream_events) — if handled is True, caller should short-circuit.
        """
        events: list = []
        reply_tools, _other_tools = self._get_reply_tools()
        for task in reply_tools:
            if task.tool_name.lower() == 'customer_service_kb_search':
                content = task.raw_result.get("answer_response", "")
                if content:
                    self.cache["follow_up_questions"] = task.raw_result.get("query_followup_suggestions")
                    async for event in response_event(
                        type=StepType.CUSTOMER_SERVICE_RESPONSE,
                        content=content,
                        session_id=self.session.id,
                        qa_id=self.qa.id,
                        system_lang_code=self.system_lang_code,
                        qa=self.qa,
                    ):
                        events.append(event)
                    return True, events
            elif task.tool_name.lower() == 'kb_search':
                kb_results = task.raw_result.get("results") or [""]
                content = kb_results[0] if kb_results else ""
                if content:
                    async for event in response_event(
                        type=StepType.ANSWER_RESPONSE,
                        content=content,
                        session_id=self.session.id,
                        qa_id=self.qa.id,
                        system_lang_code=self.system_lang_code,
                        qa=self.qa,
                    ):
                        events.append(event)
                    return True, events
        return False, events

    def _get_other_tools_exist(self) -> bool:
        """Check whether there are non-KB tasks remaining in the plan."""
        return any(
            not (task.enable_reply and task.status == TaskStatus.COMPLETED)
            for task in self.plan.tasks
        )

    async def _build_llm_context(
        self, query, tools_result, history, reply_language,
        enable_think, has_web_search_fallback,
    ) -> tuple[list, dict]:
        """Build LLM messages list and system prompt variables.

        Returns:
            (messages, system_prompt_vars)
        """
        messages = []

        memory = await self._get_memory(query)

        if history and self._has_tool_names(self._REFERENCE_SOURCE_NAME):
            context_payload = await self._prepare_context(
                history=history,
                history_turns=6,
                current_query_tokens=estimate_tokens(query or ""),
            )
            history_messages = context_payload.get("messages", [])
            if history_messages:
                context.get("kia_memory").history[HistoryStepType.ANSWER_RESPONSE] = history_messages
                messages.extend(history_messages)

        messages.append({"role": "user", "content": query})

        for task in self.plan.tasks:
            if task.tool_name in ['direct_response', *self._REFERENCE_SOURCE_NAME]:
                continue
            tool_content = task.result if task.status == TaskStatus.COMPLETED else task.error
            messages.append({
                "role": "user",
                "content": f"[Tool `{task.tool_name}` output]\n{tool_content}",
            })

        if has_web_search_fallback:
            ws_result = self.cache.get("tools_result", [])
            if ws_result:
                ws_content = (
                    "\n".join(tr.get("text", "") for tr in ws_result if isinstance(tr, dict))
                    if isinstance(ws_result, list)
                    else str(ws_result)
                )
                messages.append({
                    "role": "user",
                    "content": f"[Tool `web_search` output]\n{ws_content}",
                })
                logger.info(f"[_build_llm_context] Added web_search fallback tool message, content_len={len(ws_content)}")

        prompt_tools_info = self._get_prompt_tools_info()
        if self._has_tool_names(['coin_screener']) and tools_result:
            crypto_names = self._extract_crypto_names(tools_result)
            if not crypto_names:
                table_data = self.cache.get("recommend_crypto_table_data", {})
                if isinstance(table_data, dict):
                    crypto_names = ",".join(
                        item["currency"]
                        for item in table_data.get("data", [])
                        if isinstance(item, dict) and item.get("currency")
                    )
            if crypto_names:
                prompt_tools_info["coin_screener"] = crypto_names
            logger.info(f"从工具返回值中提取的加密货币名称: {crypto_names}")

        system_prompt_vars = {
            "query": query,
            "reply_language": reply_language,
            "current_time": datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S (%A)") + " (UTC+8)",
            "memory": memory,
            "max_response_tokens": 8000 if enable_think else 4000,
            "tools_info": prompt_tools_info,
            "enable_think": enable_think,
        }

        dag_prompt = self.cache.get("dag_response_prompt_name") or ""
        if dag_prompt and dag_prompt != "final_response_prompt":
            tool_result_text = prompt_tools_info.get(dag_prompt, "")
            if not tool_result_text:
                tool_result_text = self.cache.get("tools_info", {}).get(dag_prompt, "")
            system_prompt_vars["tool_name"] = dag_prompt
            system_prompt_vars["tool_result"] = tool_result_text

        return messages, system_prompt_vars

    async def _finalize_thinking_step(
        self, step_deep_think, trailing_text, start_time,
    ):
        """Finalize the DEEP_THINK step when </think> is encountered.

        Yields stream events for: trailing content, content correction,
        title correction, and DEEP_THINK end.
        """
        if trailing_text:
            yield self._stream_json(
                status=StreamStatusType.PENDING, type=StepType.CONTENT, content=trailing_text,
            )
            self._concat_content(step_deep_think, StepType.CONTENT, content=trailing_text)

        thinking_content = step_deep_think.step.get(StepType.CONTENT, "")
        await self._check_url_risk(thinking_content, "Thinking")

        thinking_cleaned = re.sub(r'\[\s*\d+\s*\]', '', thinking_content)
        if thinking_cleaned != thinking_content:
            yield self._stream_json(
                status=StreamStatusType.PENDING, type=StepType.CONTENT_CORRECTION,
                content=thinking_cleaned,
            )
            step_deep_think.step[StepType.CONTENT_CORRECTION] = thinking_cleaned

        deep_think_end_msg = get_localized_message("deep_think_end", self.system_lang_code)
        yield self._stream_json(
            status=StreamStatusType.PENDING, type=StepType.TITLE_CORRECTION, content=deep_think_end_msg,
        )
        yield self._stream_json(status=StreamStatusType.END, type=StepType.DEEP_THINK)

        step_deep_think.step[StepType.TITLE_CORRECTION] = deep_think_end_msg
        step_deep_think.elapsedMs = int((time.time() - start_time) * 1000)
        step_deep_think.status = StepStatusType.SUCCEEDED
        self.qa.answer.append(step_deep_think)
        await self.qa.save()

    async def _append_missing_card_placeholders(self, resource_references, step_answer_response):
        """Append card placeholders that the LLM failed to emit (multi-card scenario)."""
        accumulated = step_answer_response.step.get(StepType.CONTENT, "")
        for ref in resource_references:
            expected = f"{{{{kia-chat-card eventId='{ref['eventId']}'}}}}"
            if expected not in accumulated:
                chunk = f"\n{expected}"
                yield self._stream_json(
                    status=StreamStatusType.PENDING, type=StepType.CONTENT, content=chunk,
                )
                self._concat_content(step_answer_response, StepType.CONTENT, content=chunk)
                logger.info(f"[RESOURCE_REFERENCE] appended missing placeholder for {ref['name']} ({ref['eventId']})")

    def _apply_answer_fallbacks(self, step_deep_think, step_answer_response, enable_think):
        """Handle edge cases where the LLM output is malformed or missing."""
        # Fallback: enable_think=True but no </think> tag — content stuck in think step
        if enable_think and not step_answer_response.step.get(StepType.CONTENT):
            think_content = step_deep_think.step.get(StepType.CONTENT, "")
            if think_content:
                logger.warning(
                    "[DEEP_THINK] No </think> tag found in LLM response; "
                    "falling back to using thinking content as answer"
                )
                step_answer_response.step[StepType.CONTENT] = think_content

        # Fallback: LLM echoed "[Tool: xxx]" instead of real content
        raw = step_answer_response.step.get(StepType.CONTENT, "")
        if raw and re.match(r"^\[\s*Tool\s*:\s*\w+\s*\]\s*$", raw.strip()):
            logger.warning(f"[RESPONSE] LLM echoed tool reference '{raw.strip()}', treating as empty")
            step_answer_response.step[StepType.CONTENT] = ""
            if enable_think:
                think_content = step_deep_think.step.get(StepType.CONTENT, "")
                if think_content:
                    step_answer_response.step[StepType.CONTENT] = think_content

    async def _write_transcript(self, step_answer_response):
        """Shadow-write the assistant response to the conversation transcript."""
        full_response = step_answer_response.step.get(StepType.CONTENT, "")
        if full_response and hasattr(self, '_is_context_enabled') and self._is_context_enabled():
            try:
                writer = self._get_transcript_writer()
                if writer:
                    await writer.append_assistant_message(full_response)
                    await writer.flush()
            except Exception as e:
                logger.debug(f"Transcript append assistant msg failed (non-critical): {e}")

    async def _process_citations(self, step_answer_response) -> list[str]:
        """Process citations in the answer, update cache. Returns stream events to yield."""
        events: list[str] = []
        full_response = step_answer_response.step.get(StepType.CONTENT, "")
        self.cache["full_response"] = full_response
        corrected_response = full_response

        await self._check_url_risk(full_response, "Answer")
        search_id_to_url_map = self.cache.get("search_id_to_url_map", {})

        if not full_response.strip():
            return events

        if search_id_to_url_map:
            corrected_response, events = self._process_citations_with_sources(
                step_answer_response, full_response, search_id_to_url_map,
            )
        else:
            corrected_response, events = self._strip_orphan_citation_markers(
                step_answer_response, full_response,
            )

        self.cache.update({
            "corrected_response": corrected_response,
        })
        return events

    def _process_citations_with_sources(
        self, step_answer_response, full_response, search_id_to_url_map,
    ) -> tuple[str, list[str]]:
        """Convert numeric citations to Markdown links using search results."""
        events: list[str] = []
        corrected_response = full_response
        logger.info(f"Processing citations - original search results: {len(search_id_to_url_map)}")

        try:
            converted_response, final_citations = CitationProcessor.convert_to_markdown_citations(
                text=full_response, citation_map=search_id_to_url_map,
            )

            if final_citations:
                logger.info(f"Citations converted: {len(final_citations)} citations found")
                logger.debug(f"Citation summary:\n{CitationProcessor.get_citation_summary(search_id_to_url_map)}")

                is_valid, errors = CitationProcessor.validate_citations(converted_response)
                if not is_valid:
                    logger.warning(f"Citation validation warnings: {errors}")

                if converted_response != full_response:
                    logger.info("Sending corrected response with Markdown-formatted citations")
                    corrected_response = converted_response
                    events.append(self._stream_json(
                        status=StreamStatusType.PENDING, type=StepType.CONTENT_CORRECTION,
                        content=corrected_response,
                    ))
                    step_answer_response.step[StepType.CONTENT_CORRECTION] = corrected_response

                self.cache["final_citations"] = final_citations

        except Exception as e:
            logger.error(f"Citation processing failed: {e}, using original response")
            corrected_response = full_response
            self.cache["final_citations"] = []

        return corrected_response, events

    def _strip_orphan_citation_markers(
        self, step_answer_response, full_response,
    ) -> tuple[str, list[str]]:
        """Remove [1], [2,3] etc. when no search results are available."""
        events: list[str] = []
        logger.info("No search results available, removing citation markers from response")

        citation_pattern = r'\[\d+(?:[,\-]\d+)*\]'
        corrected_response = re.sub(citation_pattern, '', full_response)

        if corrected_response != full_response:
            logger.info("Removed citation markers from response (no search results)")
            events.append(self._stream_json(
                status=StreamStatusType.PENDING, type=StepType.CONTENT_CORRECTION,
                content=corrected_response,
            ))
            step_answer_response.step[StepType.CONTENT_CORRECTION] = corrected_response
        else:
            corrected_response = full_response

        self.cache["final_citations"] = []
        return corrected_response, events

    def _format_stream_error(self, error: Exception, reply_language: str) -> str:
        """Build a user-facing error message for LLM streaming failures."""
        msg = str(error).strip() or getattr(error, "message", "") or type(error).__name__
        if not msg or "ReadError" in type(error).__name__ or "ReadError" in msg:
            lang_code = ENGLISH_NAME_TO_CODE_MAP.get(reply_language, self.system_lang_code or "en")
            msg = get_localized_message("llm_stream_error", lang_code) or "LLM stream connection interrupted, please retry."
        return msg

    # ==================================================================
    # Follow-up question generation
    # ==================================================================

    async def check_follow_up_questions(self, questions):
        """Sanity check the generated follow-up questions."""
        try:
            response = await llm.ainvoke(
                messages=[
                    {
                        "role": "system",
                        "content": await mcp_client.get_prompt("check_follow_up_questions_prompt")
                    },
                    {
                        "role": "user",
                        "content": str(questions)
                    }
                ],
                response_format=FollowUpQuestionsIndex
            )
            if response.indices:
                logger.info(f"Filtered out follow-up questions at indices: {response.indices}")
                return [q for i, q in enumerate(questions) if i not in response.indices]
        except Exception as e:
            logger.exception(f"Failed to generate follow-up questions, error={e}")
        return questions

    async def generate_follow_up_questions(
            self,
            user_query: str,
            history,
            assistant_response: str,
            language: str = "en",
    ) -> List[str]:
        """Generate follow-up questions based on conversation context."""
        follow_up_questions = self.cache.get("follow_up_questions")
        if follow_up_questions:
            return follow_up_questions[:3]
        
        messages = []
        if history:
            context_payload = await self._prepare_context(
                history=history,
                history_turns=6,
                current_query_tokens=estimate_tokens(user_query or ""),
            )
            history_messages = context_payload.get("messages", [])
            if history_messages:
                context.get("kia_memory").history[HistoryStepType.QUERY_FOLLOWUP_SUGGESTIONS] = history_messages
            messages.extend(history_messages)

        user_query = truncate_message(user_query, 1000)
        assistant_response = truncate_message(assistant_response)
        logger.info(f"Follow-up input: query={user_query!r}, language={language}, assistant_response={assistant_response[:500]!r}")
        messages.append({"role": "user", "content": user_query})
        messages.append({"role": "assistant", "content": assistant_response})

        memory = await self._get_memory(user_query)

        system_prompt = await mcp_client.get_prompt(
            name='follow_up_questions_prompt',
            data={
                'language_name': language,
                'memory': memory
            }
        )

        messages.insert(0, {"role": "system", "content": system_prompt})

        try:
            extra_body = None if config.use_azure_openai else {
                "chat_template_kwargs": {"enable_thinking": False},
            }
            response = await self.llm.chat.completions.create(
                model=self.model_name,
                messages=messages,
                max_tokens=200,
                temperature=0.6,
                top_p=0.9,
                timeout=config.llm_followup_timeout or 30.0,
                extra_body=extra_body
            )

            questions_text = response.choices[0].message.content.strip()

            questions = []
            for line in questions_text.split("\n"):
                line = line.strip()
                if (
                        line
                        and not line.startswith("#")
                        and not line.startswith("-")
                        and not line.startswith("*")
                ):
                    line = re.sub(r"^\d+[.、]\s*", "", line)
                    line = re.sub(r"^[•·]\s*", "", line)
                    if line and len(line) > 10 and (line.endswith("?") or line.endswith("？")):
                        questions.append(line)

            if questions:
                final_questions = questions[:3]
                if len(final_questions) >= 1:
                    logger.info(
                        f"Generated {len(final_questions)} follow-up questions for query: {user_query[:50]}")
                    return final_questions

            logger.warning(f"Follow-up LLM output not parseable as questions, using fallback. raw={questions_text!r}")
            return self._default_follow_up_questions(language)

        except Exception as e:
            logger.error(f"Failed to generate follow-up questions: {e}, {traceback.format_exc()}")
            logger.warning("Using fast fallback questions")
            return self._default_follow_up_questions(language)

    @staticmethod
    def _default_follow_up_questions(language: str) -> List[str]:
        """默认追问列表，当 LLM 无法生成有效追问时兜底。从池中随机选 3 个。"""
        _MAX_FOLLOWUP = 3
        if language == "Chinese (Simplified)":
            pool = [
                "比特币现在的价格走势如何？",
                "如何构建多元化的投资组合？",
                "什么是最有效的技术分析方法？",
                "加密货币投资有哪些风险？",
                "平台操作遇到问题怎么解决？",
            ]
        else:
            pool = [
                "What's Bitcoin's current price trend?",
                "How do I build a diversified crypto portfolio?",
                "What are the most effective trading strategies?",
                "Which risks should I be aware of?",
                "How do I resolve platform technical issues?",
            ]
        return random.sample(pool, min(_MAX_FOLLOWUP, len(pool)))
