"""
Session Lineage — parent/child 追踪 (§5.4)

Tracks session fork/compact relationships for audit and replay.
A lineage record is lightweight and stored in-memory; the authoritative
parent_session_id field lives in the MongoDB sessions collection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class LineageReason(str, Enum):
    """Why a new session was derived from its parent."""

    COMPACTION = "compaction"  # context window overflow → compact + new session
    FORK = "fork"  # explicit fork for sub-task isolation
    RESUME = "resume"  # manual resume of a previous session


@dataclass
class LineageRecord:
    """
    Immutable snapshot of a parent → child relationship.

    Attributes
    ----------
    child_session_id:
        The newly created session.
    parent_session_id:
        The session from which this one was derived.
    reason:
        What triggered the derivation.
    created_at:
        Wall-clock timestamp of when the relationship was established.
    metadata:
        Optional bag for extra context (e.g., compaction summary length,
        fork task description).
    """

    child_session_id: str
    parent_session_id: str
    reason: LineageReason
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "child_session_id": self.child_session_id,
            "parent_session_id": self.parent_session_id,
            "reason": self.reason.value,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }


class SessionLineage:
    """
    Manages the lineage chain for the current process lifetime.

    In production, the *authoritative* store is the ``parent_session_id``
    field on the MongoDB ``sessions`` document.  This in-memory index is a
    fast lookup cache built from that persistent source on startup or
    on-demand.

    Usage::

        lineage = SessionLineage()
        lineage.record(child_id="sess-new", parent_id="sess-old",
                       reason=LineageReason.COMPACTION)
        chain = lineage.get_chain("sess-new")  # ["sess-old"]
    """

    def __init__(self) -> None:
        # child_id → LineageRecord
        self._records: dict[str, LineageRecord] = {}

    # ── Write ──────────────────────────────────────────────────────────────────

    def record(
        self,
        child_session_id: str,
        parent_session_id: str,
        reason: LineageReason,
        metadata: Optional[dict] = None,
    ) -> LineageRecord:
        """
        Record a parent → child relationship.

        A child may only have *one* parent — if a record for *child_session_id*
        already exists it is overwritten (last write wins; callers must ensure
        correctness).
        """
        rec = LineageRecord(
            child_session_id=child_session_id,
            parent_session_id=parent_session_id,
            reason=reason,
            metadata=metadata or {},
        )
        self._records[child_session_id] = rec
        return rec

    # ── Read ───────────────────────────────────────────────────────────────────

    def get_parent(self, session_id: str) -> Optional[str]:
        """Return the direct parent session ID, or None if root."""
        rec = self._records.get(session_id)
        return rec.parent_session_id if rec else None

    def get_record(self, session_id: str) -> Optional[LineageRecord]:
        """Return the LineageRecord for *session_id*, or None."""
        return self._records.get(session_id)

    def get_chain(self, session_id: str, max_depth: int = 50) -> list[str]:
        """
        Walk up the parent chain and return all ancestor session IDs,
        oldest-first.

        The *session_id* itself is **not** included in the result.

        Parameters
        ----------
        session_id:
            Starting point (the leaf / youngest session).
        max_depth:
            Safety cap to prevent infinite loops if the data is cyclic.
        """
        chain: list[str] = []
        current = session_id
        seen: set[str] = {current}

        for _ in range(max_depth):
            parent = self.get_parent(current)
            if parent is None:
                break
            if parent in seen:
                # Cycle guard — should never happen with valid data
                break
            chain.append(parent)
            seen.add(parent)
            current = parent

        chain.reverse()  # oldest first
        return chain

    def get_children(self, parent_session_id: str) -> list[LineageRecord]:
        """Return all direct children of *parent_session_id*."""
        return [rec for rec in self._records.values() if rec.parent_session_id == parent_session_id]

    def is_root(self, session_id: str) -> bool:
        """Return True if *session_id* has no recorded parent."""
        return session_id not in self._records

    def depth(self, session_id: str) -> int:
        """Return how many ancestors *session_id* has (0 = root)."""
        return len(self.get_chain(session_id))

    # ── Housekeeping ───────────────────────────────────────────────────────────

    def remove(self, session_id: str) -> None:
        """Evict *session_id* from the in-memory index."""
        self._records.pop(session_id, None)

    def __len__(self) -> int:
        return len(self._records)

    def __repr__(self) -> str:
        return f"SessionLineage(records={len(self._records)})"
