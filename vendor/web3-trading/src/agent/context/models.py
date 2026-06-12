# -*- coding: utf-8 -*-
"""
Transcript event models and context window data structures.

TranscriptEvent is the fundamental unit of the transcript log.
Each event has an id/parentId forming a tree (for branch support).
"""

import uuid
import time
from enum import StrEnum
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field


class TranscriptEventType(StrEnum):
    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    COMPACTION_SUMMARY = "compaction_summary"
    BRANCH_SUMMARY = "branch_summary"
    MEMORY_FLUSH = "memory_flush"
    COMPACTION_MARKER = "compaction_marker"


class TranscriptEvent(BaseModel):
    """A single event in the transcript log (append-only)."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    session_id: str = Field(..., description="Which session this event belongs to")
    parent_id: Optional[str] = Field(None, description="Parent event ID (tree structure for branches)")
    branch_id: Optional[str] = Field(None, description="None = main line, non-null = branch ID")
    seq: int = Field(0, description="Monotonic sequence number within session")
    event_type: TranscriptEventType = Field(...)
    role: Optional[str] = Field(None, description="user / assistant / tool / system")
    content: str = Field("", description="The actual content")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Extra: tool_name, args, token_count, etc.")
    token_estimate: int = Field(0, description="Estimated token count for this event")
    created_at: int = Field(default_factory=lambda: int(time.time()))

    def is_main_line(self) -> bool:
        return self.branch_id is None

    def is_summary(self) -> bool:
        return self.event_type in (
            TranscriptEventType.COMPACTION_SUMMARY,
            TranscriptEventType.BRANCH_SUMMARY,
            TranscriptEventType.MEMORY_FLUSH,
        )


@dataclass
class ContextWindow:
    """
    Assembled context window ready for LLM injection.

    Built by ContextAssembler from the transcript tree.
    """
    summary: str = ""
    memory_flush: str = ""
    recent_messages: List[Dict[str, str]] = field(default_factory=list)
    branch_summaries: List[str] = field(default_factory=list)
    token_estimate: int = 0

    def to_messages(self) -> List[Dict[str, str]]:
        """Convert to OpenAI-style message list for LLM injection."""
        messages = []

        preamble_parts = []
        if self.summary:
            preamble_parts.append(f"[Conversation Summary]\n{self.summary}")
        if self.memory_flush:
            preamble_parts.append(f"[Critical Context]\n{self.memory_flush}")
        for bs in self.branch_summaries:
            preamble_parts.append(f"[Sub-task Result]\n{bs}")

        if preamble_parts:
            messages.append({
                "role": "system",
                "content": "\n\n".join(preamble_parts),
            })

        messages.extend(self.recent_messages)
        return messages

    def to_prompt_string(self) -> str:
        """Convert to a single string for Jinja template injection."""
        parts = []
        if self.summary:
            parts.append(f"[Summary] {self.summary}")
        if self.memory_flush:
            parts.append(f"[Critical Context] {self.memory_flush}")
        for bs in self.branch_summaries:
            parts.append(f"[Sub-task] {bs}")
        for msg in self.recent_messages:
            parts.append(f"{msg['role'].capitalize()}: {msg['content']}")
        return "\n".join(parts) if parts else "No previous conversation"
