# -*- coding: utf-8 -*-
"""
BranchManager — fork/merge for sub-task isolation.

Prevents "tool retry noise" from polluting the main conversation context.
Dirty work (tool retries, plan exploration, alternative approaches) happens
in a branch. When done, the branch is summarized and merged back.
"""

import uuid
import logging
from typing import List, Optional

from agent.context.models import TranscriptEvent, TranscriptEventType
from agent.context.writer import TranscriptWriter
from agent.context.reader import TranscriptReader

logger = logging.getLogger(__name__)


class BranchManager:
    """
    Manages conversation branches for sub-task isolation.

    Usage:
        branch_id = await manager.fork("retrying failed tool call")
        # ... do work, events auto-tagged with branch_id via writer ...
        await manager.merge(branch_id)
    """

    def __init__(
        self,
        session_id: str,
        writer: TranscriptWriter,
        reader: TranscriptReader,
        llm=None,
        model_name: str = "",
    ):
        self._session_id = session_id
        self._writer = writer
        self._reader = reader
        self._llm = llm
        self._model_name = model_name
        self._active_branches: dict = {}

    async def fork(self, reason: str = "") -> str:
        """
        Create a new branch.

        Sets the writer to tag subsequent events with this branch_id.
        Returns the branch_id.
        """
        branch_id = uuid.uuid4().hex[:12]
        self._active_branches[branch_id] = {
            "reason": reason,
            "fork_event_id": self._writer._last_main_event_id,
        }
        self._writer.set_branch(branch_id)
        logger.info(f"Forked branch {branch_id}: {reason}")
        return branch_id

    async def merge(self, branch_id: str) -> Optional[str]:
        """
        Merge a branch back to the main line.

        Summarizes branch events and appends a branch_summary event
        to the main line. Switches writer back to main line.

        Returns the summary text, or None if merge failed.
        """
        if branch_id not in self._active_branches:
            logger.warning(f"Branch {branch_id} not found in active branches")
            return None

        self._writer.set_branch(None)

        branch_events = await self._reader.load_branch_events(branch_id)
        if not branch_events:
            logger.info(f"Branch {branch_id} has no events, nothing to merge")
            del self._active_branches[branch_id]
            return None

        summary = await self._summarize_branch(branch_id, branch_events)
        await self._writer.append_branch_summary(branch_id, summary)

        del self._active_branches[branch_id]
        logger.info(
            f"Merged branch {branch_id}: {len(branch_events)} events -> "
            f"{len(summary)} chars summary"
        )
        return summary

    async def _summarize_branch(
        self, branch_id: str, events: List[TranscriptEvent]
    ) -> str:
        """Summarize branch events into a concise result description."""
        reason = self._active_branches.get(branch_id, {}).get("reason", "")

        if self._llm:
            try:
                events_text = self._format_branch_events(events)
                prompt = (
                    f"A sub-task was executed: {reason}\n\n"
                    f"Events:\n{events_text}\n\n"
                    f"Summarize what was attempted and what the outcome was "
                    f"in 1-3 sentences. Focus on results, not process."
                )
                response = await self._llm.ainvoke(
                    messages=[{"role": "user", "content": prompt}],
                    model=self._model_name or None,
                    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                    max_tokens=300,
                    temperature=0.3,
                )
                return response.content if hasattr(response, "content") else str(response)
            except Exception as e:
                logger.warning(f"Branch summary LLM call failed: {e}")

        return self._fallback_summarize(branch_id, events, reason)

    @staticmethod
    def _format_branch_events(events: List[TranscriptEvent]) -> str:
        lines = []
        for e in events:
            if e.event_type == TranscriptEventType.TOOL_CALL:
                tool = e.metadata.get("tool_name", "tool")
                lines.append(f"Called {tool}")
            elif e.event_type == TranscriptEventType.TOOL_RESULT:
                tool = e.metadata.get("tool_name", "tool")
                success = e.metadata.get("success", True)
                lines.append(f"{tool} {'succeeded' if success else 'failed'}: {e.content[:200]}")
            elif e.event_type == TranscriptEventType.ASSISTANT_MESSAGE:
                lines.append(f"Assistant: {e.content[:200]}")
        return "\n".join(lines)

    @staticmethod
    def _fallback_summarize(
        branch_id: str, events: List[TranscriptEvent], reason: str
    ) -> str:
        """Simple fallback when LLM is unavailable."""
        tool_names = set()
        success_count = 0
        fail_count = 0
        for e in events:
            if e.event_type == TranscriptEventType.TOOL_CALL:
                tool_names.add(e.metadata.get("tool_name", "unknown"))
            elif e.event_type == TranscriptEventType.TOOL_RESULT:
                if e.metadata.get("success", True):
                    success_count += 1
                else:
                    fail_count += 1

        tools_str = ", ".join(tool_names) if tool_names else "no tools"
        return (
            f"Sub-task ({reason}): used {tools_str}, "
            f"{success_count} succeeded, {fail_count} failed."
        )

    @property
    def has_active_branches(self) -> bool:
        return bool(self._active_branches)
