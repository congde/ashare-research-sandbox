# -*- coding: utf-8 -*-
"""
Compactor — pre-compaction memory flush + summarization + marker.

The key insight: before allowing compression to discard old events,
force-persist what matters. The agent does not rely on "the model
remembering" — the system explicitly saves it.

Sequence:
1. memory_flush: Extract critical state from context via LLM
2. compaction_summary: Summarize old events via LLM
3. compaction_marker: Write boundary marker, update session
"""

import logging
import time
from typing import List, Optional

from agent.context.models import TranscriptEvent, TranscriptEventType
from agent.context.writer import TranscriptWriter
from agent.context.reader import TranscriptReader
from agent.context.token_budget import TokenBudget, estimate_tokens
from agent.utils import jinja_render

logger = logging.getLogger(__name__)


class Compactor:
    """
    Manages context compaction for a session.

    Triggered when context_tokens_estimate exceeds the compaction threshold.
    """

    def __init__(
        self,
        session_id: str,
        writer: TranscriptWriter,
        reader: TranscriptReader,
        token_budget: TokenBudget,
        llm=None,
        model_name: str = "",
        compaction_threshold: float = 0.7,
        recent_window: int = 6,
        flush_before_compact: bool = True,
    ):
        self._session_id = session_id
        self._writer = writer
        self._reader = reader
        self._budget = token_budget
        self._llm = llm
        self._model_name = model_name
        self._threshold = compaction_threshold
        self._recent_window = recent_window
        self._flush_before_compact = flush_before_compact

    def should_compact(self, current_tokens: int) -> bool:
        """Check if compaction should be triggered."""
        threshold_tokens = int(self._budget.total_available * self._threshold)
        return current_tokens > threshold_tokens

    async def compact(self, events: List[TranscriptEvent]) -> Optional[str]:
        """
        Run the full compaction pipeline.

        Args:
            events: All main-line events since last compaction.

        Returns:
            The compaction summary text, or None if compaction failed/skipped.
        """
        if len(events) <= self._recent_window:
            logger.info("Not enough events to compact, skipping")
            return None

        old_events = events[:-self._recent_window]
        if not old_events:
            return None

        start = time.time()
        logger.info(
            f"Compaction starting: {len(old_events)} old events, "
            f"{len(events) - len(old_events)} recent events kept"
        )

        try:
            # Step 1: Memory flush — persist critical state before compression
            flush_content = None
            if self._flush_before_compact:
                flush_content = await self._memory_flush(events)
                if flush_content:
                    await self._writer.append_memory_flush(flush_content)
                    logger.info(f"Memory flush written: {len(flush_content)} chars")

            # Step 2: Compaction summary — summarize old events
            summary = await self._summarize(old_events)
            if not summary:
                logger.warning("Compaction summary generation failed")
                return None

            summary_event = await self._writer.append_compaction_summary(summary)

            # Step 3: Compaction marker — mark the boundary
            await self._writer.append_compaction_marker(summary_event.id)
            await self._writer.flush()

            elapsed = int((time.time() - start) * 1000)
            logger.info(
                f"Compaction complete: summary={len(summary)} chars, "
                f"flush={'yes' if flush_content else 'no'}, elapsed={elapsed}ms"
            )

            return summary

        except Exception as e:
            logger.exception(f"Compaction failed: {e}")
            return None

    async def _memory_flush(self, events: List[TranscriptEvent]) -> Optional[str]:
        """
        Step 1: Extract and persist critical state from the conversation.

        Uses LLM to identify key facts, pending items, tool state,
        and user context that must survive compression.
        """
        if not self._llm:
            return None

        conversation = self._events_to_conversation(events[-20:])

        try:
            prompt = jinja_render("memory_flush_prompt", {"conversation": conversation})
            response = await self._llm.ainvoke(
                messages=[
                    {"role": "system", "content": prompt},
                ],
                model=self._model_name or None,
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                max_tokens=800,
                temperature=0.3,
            )
            return response.content if hasattr(response, "content") else str(response)
        except Exception as e:
            logger.warning(f"Memory flush LLM call failed: {e}")
            return None

    async def _summarize(self, old_events: List[TranscriptEvent]) -> Optional[str]:
        """
        Step 2: Summarize old events into a concise paragraph.
        """
        if not self._llm:
            return self._fallback_summarize(old_events)

        events_text = self._events_to_conversation(old_events)

        try:
            prompt = jinja_render("compaction_summary_prompt", {"events": events_text})
            response = await self._llm.ainvoke(
                messages=[
                    {"role": "system", "content": prompt},
                ],
                model=self._model_name or None,
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                max_tokens=500,
                temperature=0.3,
            )
            return response.content if hasattr(response, "content") else str(response)
        except Exception as e:
            logger.warning(f"Compaction summary LLM call failed: {e}")
            return self._fallback_summarize(old_events)

    @staticmethod
    def _fallback_summarize(events: List[TranscriptEvent]) -> str:
        """Simple truncation fallback when LLM is unavailable."""
        parts = []
        for e in events:
            if e.event_type == TranscriptEventType.USER_MESSAGE:
                parts.append(f"User: {e.content[:100]}")
            elif e.event_type == TranscriptEventType.ASSISTANT_MESSAGE:
                parts.append(f"Assistant: {e.content[:100]}")
            elif e.event_type == TranscriptEventType.TOOL_RESULT:
                tool = e.metadata.get("tool_name", "tool")
                parts.append(f"[{tool} result: {e.content[:50]}]")
        return " | ".join(parts)[:2000]

    @staticmethod
    def _events_to_conversation(events: List[TranscriptEvent]) -> str:
        """Format events into a readable conversation string for LLM consumption."""
        lines = []
        for e in events:
            if e.event_type == TranscriptEventType.USER_MESSAGE:
                lines.append(f"User: {e.content}")
            elif e.event_type == TranscriptEventType.ASSISTANT_MESSAGE:
                lines.append(f"Assistant: {e.content[:500]}")
            elif e.event_type == TranscriptEventType.TOOL_CALL:
                tool = e.metadata.get("tool_name", "tool")
                lines.append(f"[Tool call: {tool}]")
            elif e.event_type == TranscriptEventType.TOOL_RESULT:
                tool = e.metadata.get("tool_name", "tool")
                success = e.metadata.get("success", True)
                status = "OK" if success else "FAILED"
                lines.append(f"[Tool result: {tool} ({status}): {e.content[:200]}]")
            elif e.event_type == TranscriptEventType.MEMORY_FLUSH:
                lines.append(f"[Critical context preserved: {e.content[:200]}]")
            elif e.event_type == TranscriptEventType.COMPACTION_SUMMARY:
                lines.append(f"[Previous summary: {e.content[:200]}]")
            elif e.event_type == TranscriptEventType.BRANCH_SUMMARY:
                lines.append(f"[Sub-task result: {e.content[:200]}]")
        return "\n".join(lines)
