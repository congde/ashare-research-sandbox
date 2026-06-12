# -*- coding: utf-8 -*-
"""
TranscriptWriter — append-only event writer for the transcript log.

Every significant event (user message, assistant message, tool call/result,
summaries, flushes) gets appended to the kia_transcript MongoDB collection.
Writes are async and non-blocking to avoid impacting the main flow.
"""

import asyncio
import logging
import time
from typing import Optional, Dict, Any

from agent.context.models import TranscriptEvent, TranscriptEventType
from agent.context.token_budget import estimate_tokens

logger = logging.getLogger(__name__)


class TranscriptWriter:
    """Append-only writer for transcript events."""

    COLLECTION = "kia_transcript"

    def __init__(self, session_id: str):
        self._session_id = session_id
        self._seq = 0
        self._last_main_event_id: Optional[str] = None
        self._current_branch_id: Optional[str] = None
        self._buffer = []
        self._flush_lock = asyncio.Lock()

    @property
    def session_id(self) -> str:
        return self._session_id

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    async def initialize(self, resume_seq: int = 0):
        """Resume sequence counter from last known value (e.g. on reconnect)."""
        self._seq = resume_seq

    async def append(
        self,
        event_type: TranscriptEventType,
        content: str,
        role: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        parent_id: Optional[str] = None,
        branch_id: Optional[str] = None,
    ) -> TranscriptEvent:
        """
        Append a single event to the transcript.

        Returns the created TranscriptEvent (with generated id).
        """
        event = TranscriptEvent(
            session_id=self._session_id,
            parent_id=parent_id or self._last_main_event_id,
            branch_id=branch_id or self._current_branch_id,
            seq=self._next_seq(),
            event_type=event_type,
            role=role,
            content=content,
            metadata=metadata or {},
            token_estimate=estimate_tokens(content),
        )

        if event.is_main_line():
            self._last_main_event_id = event.id

        self._buffer.append(event)

        if len(self._buffer) >= 5:
            await self.flush()

        return event

    async def append_user_message(self, query: str) -> TranscriptEvent:
        return await self.append(
            event_type=TranscriptEventType.USER_MESSAGE,
            content=query,
            role="user",
        )

    async def append_assistant_message(self, content: str) -> TranscriptEvent:
        return await self.append(
            event_type=TranscriptEventType.ASSISTANT_MESSAGE,
            content=content,
            role="assistant",
        )

    async def append_tool_call(
        self, tool_name: str, arguments: Any, tool_call_id: str = ""
    ) -> TranscriptEvent:
        return await self.append(
            event_type=TranscriptEventType.TOOL_CALL,
            content=f"Call {tool_name}",
            role="tool",
            metadata={
                "tool_name": tool_name,
                "arguments": arguments,
                "tool_call_id": tool_call_id,
            },
        )

    async def append_tool_result(
        self, tool_name: str, success: bool, data: str, tool_call_id: str = ""
    ) -> TranscriptEvent:
        return await self.append(
            event_type=TranscriptEventType.TOOL_RESULT,
            content=data[:3000],
            role="tool",
            metadata={
                "tool_name": tool_name,
                "success": success,
                "tool_call_id": tool_call_id,
            },
        )

    async def append_compaction_summary(self, summary: str) -> TranscriptEvent:
        return await self.append(
            event_type=TranscriptEventType.COMPACTION_SUMMARY,
            content=summary,
            role="system",
        )

    async def append_memory_flush(self, flush_content: str) -> TranscriptEvent:
        return await self.append(
            event_type=TranscriptEventType.MEMORY_FLUSH,
            content=flush_content,
            role="system",
        )

    async def append_compaction_marker(self, summary_event_id: str) -> TranscriptEvent:
        return await self.append(
            event_type=TranscriptEventType.COMPACTION_MARKER,
            content="",
            role="system",
            metadata={"summary_event_id": summary_event_id},
        )

    async def append_branch_summary(
        self, branch_id: str, summary: str
    ) -> TranscriptEvent:
        """Append a branch summary event to the main line."""
        return await self.append(
            event_type=TranscriptEventType.BRANCH_SUMMARY,
            content=summary,
            role="system",
            metadata={"source_branch_id": branch_id},
            branch_id=None,
        )

    def set_branch(self, branch_id: Optional[str]):
        """Switch to a branch (or back to main line if None)."""
        self._current_branch_id = branch_id

    async def flush(self):
        """Write buffered events to MongoDB."""
        if not self._buffer:
            return

        async with self._flush_lock:
            events_to_write = self._buffer[:]
            self._buffer.clear()

        try:
            from vendor_runtime_sdk.runtime.protocols.context_store import get_context_store
            docs = [e.model_dump(mode="json") for e in events_to_write]
            await get_context_store().get_collection("kia_transcript").insert_many(docs)
            logger.debug(
                f"Flushed {len(docs)} transcript events for session {self._session_id}"
            )
        except Exception as e:
            logger.warning(f"Failed to flush transcript events: {e}")
            self._buffer.extend(events_to_write)

    async def close(self):
        """Flush remaining events on teardown."""
        await self.flush()
