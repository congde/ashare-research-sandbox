# -*- coding: utf-8 -*-
"""
ContextAssembler — builds the context window from the transcript tree.

Replaces _history_to_messages with a structured approach:
1. Start from latest compaction_summary (if any)
2. Add memory_flush events
3. Add branch_summary events
4. Add recent events in full
5. Check token budget; trigger compaction if needed
"""

import logging
from typing import List, Optional, Tuple

from agent.context.models import (
    TranscriptEvent,
    TranscriptEventType,
    ContextWindow,
)
from agent.context.reader import TranscriptReader
from agent.context.compactor import Compactor
from agent.context.token_budget import TokenBudget, estimate_tokens

logger = logging.getLogger(__name__)


class ContextAssembler:
    """
    Assembles a ContextWindow from the transcript tree.

    Supports graceful degradation:
    - If transcript is available, builds from transcript
    - Falls back to legacy _history_to_messages if transcript is empty
    """

    def __init__(
        self,
        session_id: str,
        reader: TranscriptReader,
        token_budget: TokenBudget,
        compactor: Optional[Compactor] = None,
        recent_window: int = 6,
    ):
        self._session_id = session_id
        self._reader = reader
        self._budget = token_budget
        self._compactor = compactor
        self._recent_window = recent_window

    async def assemble(
        self,
        system_prompt_tokens: int = 0,
        tools_result_tokens: int = 0,
        current_query_tokens: int = 0,
    ) -> ContextWindow:
        """
        Build the context window from the transcript.

        Steps:
        1. Load events since last compaction
        2. If over budget, trigger compaction, then reload
        3. Build ContextWindow from summary + recent events
        """
        try:
            summary_event, events = await self._reader.load_since_compaction()

            if not events and not summary_event:
                return ContextWindow()

            history_budget = self._budget.history_budget(
                system_prompt_tokens, tools_result_tokens, current_query_tokens
            )

            total_tokens = sum(e.token_estimate for e in events)
            if summary_event:
                total_tokens += summary_event.token_estimate

            # Trigger compaction if over budget
            if total_tokens > history_budget and self._compactor and len(events) > self._recent_window:
                logger.info(
                    f"Context over budget ({total_tokens}/{history_budget}), "
                    f"triggering compaction"
                )
                await self._compactor.compact(events)
                summary_event, events = await self._reader.load_since_compaction()
                total_tokens = sum(e.token_estimate for e in events)
                if summary_event:
                    total_tokens += summary_event.token_estimate

            return self._build_window(summary_event, events, history_budget)

        except Exception as e:
            logger.warning(f"ContextAssembler.assemble failed: {e}")
            return ContextWindow()

    def _build_window(
        self,
        summary_event: Optional[TranscriptEvent],
        events: List[TranscriptEvent],
        history_budget: int,
    ) -> ContextWindow:
        """
        Build ContextWindow from loaded events, respecting token budget.

        Recovery strategy: if still over budget after compaction,
        progressively reduce recent_window (6 -> 4 -> 2 -> 1).
        """
        window = ContextWindow()

        # 1. Compaction summary
        if summary_event:
            window.summary = summary_event.content

        # 2. Collect memory_flush and branch_summary from events
        flush_parts = []
        branch_parts = []
        conversation_events = []

        for e in events:
            if e.event_type == TranscriptEventType.MEMORY_FLUSH:
                flush_parts.append(e.content)
            elif e.event_type == TranscriptEventType.BRANCH_SUMMARY:
                branch_parts.append(e.content)
            elif e.event_type == TranscriptEventType.COMPACTION_MARKER:
                continue
            elif e.event_type == TranscriptEventType.COMPACTION_SUMMARY:
                continue
            else:
                conversation_events.append(e)

        window.memory_flush = "\n".join(flush_parts) if flush_parts else ""
        window.branch_summaries = branch_parts

        # 3. Convert recent events to messages, with progressive reduction
        recent_window = self._recent_window
        while recent_window >= 1:
            messages = self._events_to_messages(conversation_events[-recent_window * 3:])
            token_est = self._estimate_window_tokens(window, messages)
            if token_est <= history_budget or recent_window <= 1:
                break
            recent_window = max(recent_window - 2, 1)

        window.recent_messages = messages
        window.token_estimate = self._estimate_window_tokens(window, messages)

        logger.info(
            f"Context assembled: summary={'yes' if window.summary else 'no'}, "
            f"flush={'yes' if window.memory_flush else 'no'}, "
            f"branches={len(window.branch_summaries)}, "
            f"recent_msgs={len(window.recent_messages)}, "
            f"tokens~{window.token_estimate}"
        )

        return window

    @staticmethod
    def _events_to_messages(events: List[TranscriptEvent]) -> List[dict]:
        """Convert transcript events to OpenAI-style messages."""
        messages = []
        for e in events:
            if e.event_type == TranscriptEventType.USER_MESSAGE:
                messages.append({"role": "user", "content": e.content})
            elif e.event_type == TranscriptEventType.ASSISTANT_MESSAGE:
                messages.append({"role": "assistant", "content": e.content})
            elif e.event_type == TranscriptEventType.TOOL_CALL:
                tool = e.metadata.get("tool_name", "tool")
                messages.append({
                    "role": "assistant",
                    "content": f"[Called tool: {tool}]",
                })
            elif e.event_type == TranscriptEventType.TOOL_RESULT:
                tool = e.metadata.get("tool_name", "tool")
                messages.append({
                    "role": "user",
                    "content": f"[Tool `{tool}` output]\n{e.content[:500]}",
                })
        return messages

    @staticmethod
    def _estimate_window_tokens(window: ContextWindow, messages: List[dict]) -> int:
        total = 0
        if window.summary:
            total += estimate_tokens(window.summary)
        if window.memory_flush:
            total += estimate_tokens(window.memory_flush)
        for bs in window.branch_summaries:
            total += estimate_tokens(bs)
        for msg in messages:
            total += estimate_tokens(msg.get("content", "")) + 4
        return total
