# -*- coding: utf-8 -*-
"""
TranscriptReader — read and walk the transcript event tree.

Provides methods to:
- Load events for a session (optionally from a compaction cursor)
- Walk the main line (skip branch events)
- Collect branch summaries
- Find the latest compaction marker
"""

import logging
from typing import Any, List, Optional, Tuple

from agent.context.models import TranscriptEvent, TranscriptEventType

logger = logging.getLogger(__name__)


class TranscriptReader:
    """Reads transcript events from the configured ContextStore."""

    COLLECTION = "kia_transcript"

    def __init__(self, session_id: str):
        self._session_id = session_id

    def _coll(self):
        from vendor_runtime_sdk.runtime.protocols.context_store import get_context_store
        return get_context_store().get_collection(self.COLLECTION)

    async def _query_transcript(
        self,
        *,
        sort: List[Tuple[str, int]],
        page_size: int,
        after_seq: Optional[int] = None,
        branch_id: Any = ...,
        event_type: Optional[str] = None,
    ) -> List[dict]:
        docs = await self._coll().query(
            matcher={"session_id": self._session_id},
            sort=sort,
            page=1,
            page_size=max(page_size, 200),
            hidden_names=["_id"],
        ) or []

        if after_seq is not None:
            docs = [d for d in docs if (d.get("seq") or 0) > after_seq]
        if branch_id is not ...:
            docs = [d for d in docs if d.get("branch_id") == branch_id]
        if event_type is not None:
            docs = [d for d in docs if d.get("event_type") == event_type]

        reverse = sort and sort[0][1] == -1
        key = sort[0][0] if sort else "seq"
        docs.sort(key=lambda d: d.get(key) or 0, reverse=reverse)
        return docs[:page_size]

    async def load_events(
        self,
        after_seq: int = 0,
        limit: int = 200,
        branch_id: Optional[str] = None,
    ) -> List[TranscriptEvent]:
        """
        Load transcript events for this session.

        Args:
            after_seq: Only load events with seq > after_seq (for incremental reads).
            limit: Max events to load.
            branch_id: If set, only load events from this branch. None = all events.
        """
        try:
            docs = await self._query_transcript(
                after_seq=after_seq,
                branch_id=branch_id,
                sort=[("seq", 1)],
                page_size=limit,
            )
            return [TranscriptEvent(**doc) for doc in docs]
        except Exception as e:
            logger.warning(f"Failed to load transcript events: {e}")
            return []

    async def load_main_line(
        self, after_seq: int = 0, limit: int = 200
    ) -> List[TranscriptEvent]:
        """Load only main-line events (branch_id is null)."""
        try:
            docs = await self._query_transcript(
                after_seq=after_seq,
                branch_id=None,
                sort=[("seq", 1)],
                page_size=limit,
            )
            return [TranscriptEvent(**doc) for doc in docs]
        except Exception as e:
            logger.warning(f"Failed to load main-line events: {e}")
            return []

    async def find_latest_compaction_marker(self) -> Optional[TranscriptEvent]:
        """Find the most recent compaction marker for this session."""
        try:
            docs = await self._query_transcript(
                branch_id=None,
                event_type=TranscriptEventType.COMPACTION_MARKER.value,
                sort=[("seq", -1)],
                page_size=1,
            )
            if docs:
                return TranscriptEvent(**docs[0])
            return None
        except Exception as e:
            logger.warning(f"Failed to find compaction marker: {e}")
            return None

    async def load_since_compaction(
        self, limit: int = 100
    ) -> Tuple[Optional[TranscriptEvent], List[TranscriptEvent]]:
        """
        Load events since the last compaction.

        Returns:
            (compaction_summary_event_or_none, events_after_compaction)
        """
        marker = await self.find_latest_compaction_marker()
        after_seq = marker.seq if marker else 0

        events = await self.load_main_line(after_seq=after_seq, limit=limit)

        summary_event = None
        if marker:
            summary_id = marker.metadata.get("summary_event_id")
            if summary_id:
                for e in events:
                    if e.id == summary_id:
                        summary_event = e
                        break
                if not summary_event:
                    try:
                        doc = await self._coll().get(
                            matcher={"id": summary_id, "session_id": self._session_id},
                            hidden_names=["_id"],
                        )
                        if doc:
                            summary_event = TranscriptEvent(**doc)
                    except Exception:
                        pass

        return summary_event, events

    async def load_branch_events(
        self, branch_id: str, limit: int = 50
    ) -> List[TranscriptEvent]:
        """Load all events for a specific branch."""
        return await self.load_events(branch_id=branch_id, limit=limit)

    async def collect_branch_summaries(
        self, after_seq: int = 0
    ) -> List[TranscriptEvent]:
        """Collect all branch_summary events on the main line after a given seq."""
        try:
            docs = await self._query_transcript(
                after_seq=after_seq,
                branch_id=None,
                event_type=TranscriptEventType.BRANCH_SUMMARY.value,
                sort=[("seq", 1)],
                page_size=50,
            )
            return [TranscriptEvent(**doc) for doc in docs]
        except Exception as e:
            logger.warning(f"Failed to collect branch summaries: {e}")
            return []

    async def get_total_token_estimate(self, after_seq: int = 0) -> int:
        """Sum token_estimate for all main-line events after a given seq."""
        events = await self.load_main_line(after_seq=after_seq)
        return sum(e.token_estimate for e in events)
