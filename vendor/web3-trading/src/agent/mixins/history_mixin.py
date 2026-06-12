# -*- coding: utf-8 -*-
"""
HistoryMixin — conversation history & memory helpers.

Methods extracted from BaseAgent for readability.

Supports two modes:
- Legacy: _history_to_messages (existing, character-based truncation)
- Transcript: _prepare_context (new, OpenClaw-inspired, token-budget-aware)

The mode is controlled by config.context.enable.
"""

import json
import re
import logging
from typing import List, Optional
from datetime import datetime

from agent.schema import (
    QAModel,
    StepType,
    StepStatusType,
    MemoryModel,
    ReferenceType,
)
from agent.utils import truncate_message
from web.context import context

logger = logging.getLogger(__name__)


class HistoryMixin:
    """Provides history retrieval, memory formatting, and message conversion."""

    def _get_latest_answer(self, lastest_qa: QAModel) -> str:
        for step in lastest_qa.answer:
            if step.type == StepType.ANSWER_RESPONSE:
                if step.status == StepStatusType.SUCCEEDED:
                    return step.step.get(StepType.CONTENT, "")
                return step.log
        return ""

    async def _get_latest_qa(self, id: str):
        return await QAModel.get_latest(id)

    async def _get_history(self, session_id: str, user_id: str, top_k=20) -> list:
        return await QAModel.get_history(session_id, user_id, top_k=top_k)


    def _has_query_clarify_in_latest_history(self, history: List[QAModel]) -> bool:
        """
        判断 history 中最近一条消息的 qa.answer 是否包含 StepType.QUERY_CLARIFY
    
        Args:
            history: 历史对话列表，按时间倒序排列（最近的在前）
        
        Returns:
            bool: 如果最近一条消息包含 QUERY_CLARIFY 则返回 True，否则返回 False
        """
        if not history or len(history) < 2:
            return False
    
        # 获取最近一条有assistant回复的历史记录
        latest_qa = history[1]
    
        # 检查 answer 中是否包含 QUERY_CLARIFY 类型的 step
        for step in latest_qa.answer:
            if step.type == StepType.QUERY_CLARIFY:
                return True
    
        return False

    def _history_to_messages(
            self,
            history: List[QAModel],
            history_turns: int = 6,
            max_answer_len: int = 500,
            max_total_length: int = 10000,
            types=(StepType.ANSWER_RESPONSE, StepType.CITATIONS, StepType.QUERY_CLARIFY, StepType.REPORT, StepType.TOOL_EXECUTION),
            join=False
    ):
        """短记忆"""
        result = []
        message_char_count = 0

        # 从最近的消息开始往前处理，确保最近的消息一定被包含
        for qa in history[:history_turns]:
            answer = ""
            for step in qa.answer:
                if not step.type in types:
                    continue
                if step.type in (StepType.ANSWER_RESPONSE, StepType.QUERY_CLARIFY):
                    answer += step.step.get(StepType.CONTENT, "") + "\n"
                elif step.type == StepType.REPORT:
                    answer += step.step.get(StepType.REPORT, "") + "\n"
                elif step.type == StepType.CITATIONS:
                    answer += "\n".join(
                        f"Reference[{item['index']}]: {item['url']}" for item in step.step.get(StepType.CONTENT, []))
                elif step.type == StepType.TOOL_EXECUTION:
                    answer += self._extract_tool_execution_summary(step)

            # 将 {{kia-chat-card eventId='...'}} 替换回 <custom_table> 或 <custom_card> 标记
            if answer.strip() and qa.resourceReference:
                # 构建 eventId -> tag_name 的映射
                event_id_to_tag = {}
                for ref in qa.resourceReference:
                    if isinstance(ref, dict):
                        ref_type = ref.get('type')
                        event_id = ref.get('eventId', '')
                    else:
                        ref_type = ref.type
                        event_id = ref.eventId
                
                    # 处理字符串或枚举值
                    ref_type_str = ref_type.value if hasattr(ref_type, 'value') else str(ref_type)
                    if ref_type_str == ReferenceType.CUSTOM_TABLE.value:
                        event_id_to_tag[event_id] = 'custom_table'
                    elif ref_type_str == ReferenceType.CUSTOM_CARD.value:
                        event_id_to_tag[event_id] = 'custom_card'
            
                # 替换 {{kia-chat-card eventId='xxx'}} 为对应的标记
                if event_id_to_tag:
                    def replace_card_tag(match):
                        event_id = match.group(1)
                        tag_name = event_id_to_tag.get(event_id, 'custom_table')  # 默认使用 custom_table
                        return f"<{tag_name}>{event_id}</{tag_name}>"
                
                    # 匹配 {{kia-chat-card eventId='xxx'}} 格式（允许 eventId 前后有空格）
                    answer = re.sub(
                        r'\{\{kia-chat-card\s+eventId\s*=\s*\'([^\']+)\'\}\}',
                        replace_card_tag,
                        answer
                    )

            if answer.strip():
                answer = truncate_message(answer, max_answer_len)
                current_message_length = len(qa.query + answer) + 25

                # 如果添加这条消息会超过总长度限制，且已经有其他消息，则停止添加
                if max_total_length is not None and message_char_count + current_message_length > max_total_length and result:
                    break

                # 将消息添加到结果的开头，保持时间顺序（旧消息在前，新消息在后）
                result.insert(0, {"role": "assistant", "content": answer})
                result.insert(0, {"role": "user", "content": qa.query})
                message_char_count += current_message_length

        if join:
            return "\n".join(f"{m['role']}: {m['content']}" for m in result)
        return result

    @staticmethod
    def _extract_tool_execution_summary(step) -> str:
        """
        Extract a concise summary from a TOOL_EXECUTION step.

        Reads from kia_qa.answer[].step.TOOL_RESULT, extracts:
        - tool name
        - key arguments (symbol, query)
        - result summary (overall_summary or first 300 chars of output)
        """
        tool_result = step.step.get(StepType.TOOL_RESULT) or step.step.get("TOOL_RESULT")
        if not tool_result or not isinstance(tool_result, dict):
            return ""

        # Extract tool name and key args from input
        tool_input = tool_result.get("input", {})
        tool_call = tool_input.get("tool_call", {}) if isinstance(tool_input, dict) else {}
        tool_name = tool_call.get("name", "") or tool_result.get("name", "")
        arguments = tool_call.get("arguments", {})

        parts = [f"[Tool: {tool_name}]"] if tool_name else []

        if isinstance(arguments, dict):
            symbol = arguments.get("symbol", "")
            query = arguments.get("query", "")
            if symbol:
                parts.append(f"symbol={symbol}")
            if query:
                parts.append(f"query={query[:80]}")

        # Extract key result from output
        output = tool_result.get("output", [])
        if isinstance(output, list) and output:
            first_item = output[0]
            if isinstance(first_item, dict):
                text = first_item.get("text", "")
                if text:
                    try:
                        data = json.loads(text)
                        inner = data.get("data", {}) if isinstance(data, dict) else {}
                        summary = inner.get("overall_summary", "")
                        if summary:
                            parts.append(f"Result: {summary[:300]}")
                        elif isinstance(inner, dict):
                            parts.append(f"Result: {str(inner)[:300]}")
                        else:
                            parts.append(f"Result: {text[:300]}")
                    except (json.JSONDecodeError, TypeError):
                        parts.append(f"Result: {text[:300]}")

        return " | ".join(parts) + "\n" if parts else ""

    async def _get_memory(self, query: str) -> str:
        """长记忆"""
        memory = await self.memory.recall(query)
        return self._format_user_memory(memory)

    def _format_user_memory(self, memory: List[dict]) -> str:
        if not memory or not isinstance(memory, list):
            return ""

        try:
            result = []
            for m in memory:
                # 提取关键信息
                memory_content = m.get('memory', '')
                score = m.get('score', 0)
                created_at = m.get('created_at', '')
                updated_at = m.get('updated_at', '')

                # 使用更新时间，如果没有则使用创建时间
                time_str = updated_at if updated_at else created_at

                # 格式化时间，保留到秒
                if time_str:
                    try:
                        dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                        formatted_time = dt.strftime('%Y-%m-%d %H:%M:%S')
                    except (ValueError, TypeError):
                        formatted_time = time_str[:19]
                else:
                    formatted_time = "Unknown"

                # 格式化相关性分数为百分比
                relevance = f"{score * 100:.1f}%" if score else "0%"

                # 拼接成一行：时间 | 相关性 | 记忆内容
                formatted_line = f"[{formatted_time}] | relevance: {relevance} | {memory_content}"
                result.append(formatted_line)

            memory = "\n".join(result)
            kia_memory : MemoryModel = context.get("kia_memory")
            if kia_memory:
                kia_memory.memory = memory
            return memory
        except Exception as e:
            logger.warning(f"Error in _get_memory: {e}")
            return ""

    # ================================================================
    # Transcript-based context management (OpenClaw-inspired)
    # ================================================================

    def _is_context_enabled(self) -> bool:
        """Check if transcript-based context management is enabled."""
        try:
            from web.config import config
            ctx = getattr(config, "context", None)
            return bool(getattr(ctx, "enable", False)) if ctx else False
        except Exception:
            return False

    def _get_transcript_writer(self):
        """Lazy-init transcript writer for the current session."""
        if not hasattr(self, "_transcript_writer") or self._transcript_writer is None:
            from agent.context.writer import TranscriptWriter
            session_id = getattr(self, "session_id", None)
            if session_id:
                self._transcript_writer = TranscriptWriter(session_id)
            else:
                return None
        return self._transcript_writer

    def _get_context_assembler(self):
        """Lazy-init context assembler for the current session."""
        if not hasattr(self, "_context_assembler") or self._context_assembler is None:
            from agent.context.assembler import ContextAssembler
            from agent.context.reader import TranscriptReader
            from agent.context.token_budget import TokenBudget
            from agent.context.compactor import Compactor
            from web.config import config

            session_id = getattr(self, "session_id", None)
            if not session_id:
                return None

            budget = TokenBudget.from_config(config)
            reader = TranscriptReader(session_id)

            ctx_cfg = getattr(config, "context", None)
            recent_window = int(getattr(ctx_cfg, "recent_window", 6)) if ctx_cfg else 6
            flush_before = bool(getattr(ctx_cfg, "flush_before_compact", True)) if ctx_cfg else True
            threshold = float(getattr(ctx_cfg, "compaction_threshold", 0.7)) if ctx_cfg else 0.7

            llm = getattr(self, "llm", None)
            model_name = getattr(self, "model_name", "") or ""

            compactor = Compactor(
                session_id=session_id,
                writer=self._get_transcript_writer(),
                reader=reader,
                token_budget=budget,
                llm=llm,
                model_name=model_name,
                compaction_threshold=threshold,
                recent_window=recent_window,
                flush_before_compact=flush_before,
            )

            self._context_assembler = ContextAssembler(
                session_id=session_id,
                reader=reader,
                token_budget=budget,
                compactor=compactor,
                recent_window=recent_window,
            )
        return self._context_assembler

    @staticmethod
    def _messages_to_prompt_string(messages: List[dict]) -> str:
        if not messages:
            return "No previous conversation"
        return "\n".join(
            f"{m.get('role', '').capitalize()}: {m.get('content', '')}" for m in messages
        )

    async def _prepare_context_transcript(
        self,
        system_prompt_tokens: int = 0,
        tools_result_tokens: int = 0,
        current_query_tokens: int = 0,
    ):
        """
        Transcript-only context builder.

        Returns transcript payload if successful; otherwise None.
        """
        if not self._is_context_enabled():
            return None

        try:
            assembler = self._get_context_assembler()
            if not assembler:
                return None
            window = await assembler.assemble(
                system_prompt_tokens=system_prompt_tokens,
                tools_result_tokens=tools_result_tokens,
                current_query_tokens=current_query_tokens,
            )
            if not (window.recent_messages or window.summary):
                return None
            return {
                "messages": window.to_messages(),
                "prompt_string": window.to_prompt_string(),
                "token_estimate": window.token_estimate,
                "source": "transcript",
            }
        except Exception as e:
            logger.warning(f"Transcript context assembly failed: {e}")
            return None

    async def _prepare_context(
        self,
        history: Optional[List[QAModel]] = None,
        history_turns: int = 6,
        system_prompt_tokens: int = 0,
        tools_result_tokens: int = 0,
        current_query_tokens: int = 0,
    ):
        """
        Unified context preparation entry point.

        If transcript-based context is enabled, uses ContextAssembler.
        Otherwise, falls back to legacy _history_to_messages.

        Returns:
            dict with keys:
                "messages": List[dict] — chat messages for LLM
                "prompt_string": str — for Jinja template {{ history }}
                "token_estimate": int — estimated tokens used
        """
        history = history or []
        messages = self._history_to_messages(
            history=history or [],
            history_turns=history_turns,
        ) if history else []
        prompt_string = self._messages_to_prompt_string(messages)

        # Default to legacy path first; switch to transcript only when over budget.
        token_estimate = 0
        history_budget = None
        try:
            from web.config import config
            from agent.context.token_budget import TokenBudget, estimate_messages_tokens

            token_estimate = estimate_messages_tokens(messages)
            history_budget = TokenBudget.from_config(config).history_budget(
                system_prompt_tokens=system_prompt_tokens,
                tools_result_tokens=tools_result_tokens,
                current_query_tokens=current_query_tokens,
            )
            if token_estimate <= history_budget:
                logger.info(
                    f"Context source=legacy (within budget): requested={token_estimate}, budget={history_budget}"
                )
                return {
                    "messages": messages,
                    "prompt_string": prompt_string,
                    "token_estimate": token_estimate,
                    "source": "legacy",
                }
        except Exception as e:
            logger.warning(f"Context budget estimation failed, using legacy: {e}")
            return {
                "messages": messages,
                "prompt_string": prompt_string,
                "token_estimate": token_estimate,
                "source": "legacy",
            }

        if not self._is_context_enabled():
            logger.info(
                f"Context source=legacy (overflow but transcript disabled): requested={token_estimate}, budget={history_budget}"
            )
            return {
                "messages": messages,
                "prompt_string": prompt_string,
                "token_estimate": token_estimate,
                "source": "legacy",
            }

        transcript_payload = await self._prepare_context_transcript(
            system_prompt_tokens=system_prompt_tokens,
            tools_result_tokens=tools_result_tokens,
            current_query_tokens=current_query_tokens,
        )
        if transcript_payload:
            logger.info(
                f"Context source=transcript (legacy overflow): requested={token_estimate}, budget={history_budget}, transcript_tokens={transcript_payload.get('token_estimate', 0)}"
            )
            return transcript_payload

        logger.warning(
            f"Context source=fallback_legacy (transcript unavailable): requested={token_estimate}, budget={history_budget}"
        )

        return {
            "messages": messages,
            "prompt_string": prompt_string,
            "token_estimate": token_estimate,
            "source": "fallback_legacy",
        }

