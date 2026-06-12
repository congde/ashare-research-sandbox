# -*- coding: utf-8 -*-
"""
SqliteStorageBackend — local-first backend implementation.

Sprint 0 PR-C delivery (docs/TUI-Web-Runtime同构化技术方案.md §A2 + §E).

Targets TUI / CLI / daemon contexts. Reuses the existing
``cli/adapters/storage_sqlite.py:SqliteStorage`` which already
implements 5/5 production DAO protocols (SessionRepository,
QARepository, MemoryRepository, CostRepository,
CoordinatorThreadRepository — verified in docs/Sprint0-Pre-work-报告.md
§1). PR-C adds 3 new adapters that didn't exist:

* ``_InMemoryStreamSink`` — asyncio.Queue per (session, qa) for SSE
  events; dict for session_meta. Replaces Redis hard-dependency.
* ``_SqliteHitlGateRepo`` — new ``hitl_pending`` + ``hitl_decisions``
  tables on the SQLite db; mirrors the Mongo backend's HITL shape.
* ``_SqliteArtifactStore`` — local FS via CheckpointManager +
  TrajectoryRecorder (same as Mongo backend; both default to FS).

Lazy-init contract
------------------
``__init__`` performs NO I/O. The underlying ``SqliteStorage``
connection + table creation happen on first method call via
``_ensure_initialized``. The in-memory StreamSink starts with empty
dicts; the HITL gate repo runs its DDL on first save/get.

This keeps construction cheap and import-safe across CLI/TUI/test
contexts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import defaultdict
from typing import Any, Dict, List, Literal, Optional, Tuple

logger = logging.getLogger(__name__)


_DEFAULT_DB_PATH = "~/.aibuddy/runtime.db"


# ──────────────────────────────────────────────────────────────────────────
# StreamSink — in-memory implementation (no Redis required)
# ──────────────────────────────────────────────────────────────────────────


class _InMemoryStreamSink:
    """SSE stream sink backed by ``asyncio.Queue`` + dict (no Redis).

    Wire shape matches ``web.api.chat.cache.RedisCache`` so the consumer
    (currently chat.py's polling loop; Sprint 1+ ConversationRuntime
    mixins) sees identical semantics:

    * One asyncio.Queue per (session_id, qa_id) holds token bytes
      pending consumer drain.
    * One dict per (session_id, qa_id) holds ``status`` / ``log`` /
      ``createdAt`` — exactly the fields ``SessionMeta.get_session_meta``
      returns to its caller.
    * One asyncio.Event per (session_id, qa_id) signals "publish_complete"
      so consumers waiting on the channel can wake up.

    Tokens are stored as bytes (matches RedisCache's
    ``cache.session_queue.get_tokens`` return type) so the SSE consumer
    code doesn't need a per-backend branch.

    Memory growth
    -------------
    The dicts grow until ``clear((session_id, qa_id))`` is called or the
    process restarts. TUI / CLI processes are short-lived enough that
    this is fine; if leaks become real, add LRU eviction. Not Sprint 0's
    problem.
    """

    def __init__(self) -> None:
        self._queues: Dict[Tuple[str, str], "asyncio.Queue[bytes]"] = {}
        self._meta: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._complete_events: Dict[Tuple[str, str], asyncio.Event] = {}
        self._lock = asyncio.Lock()

    async def _queue_for(self, session_id: str, qa_id: str) -> "asyncio.Queue[bytes]":
        key = (session_id, qa_id)
        async with self._lock:
            q = self._queues.get(key)
            if q is None:
                q = asyncio.Queue()
                self._queues[key] = q
            return q

    async def _meta_for(self, session_id: str, qa_id: str) -> Dict[str, Any]:
        key = (session_id, qa_id)
        async with self._lock:
            m = self._meta.get(key)
            if m is None:
                m = {"createdAt": int(time.time() * 1000)}
                self._meta[key] = m
            return m

    async def append_token(
        self,
        *,
        session_id: str,
        qa_id: str,
        token: str,
        ttl: int = 600,
    ) -> int:
        # ttl ignored — in-memory queue lives for process lifetime.
        q = await self._queue_for(session_id, qa_id)
        await q.put(token.encode("utf-8"))
        return q.qsize()

    async def update_session_status(
        self,
        *,
        session_id: str,
        qa_id: str,
        status: str,
        log: str = "",
        ttl: int = 600,
    ) -> None:
        m = await self._meta_for(session_id, qa_id)
        m["status"] = status
        m["log"] = log

    async def publish_complete(
        self, *, session_id: str, qa_id: str
    ) -> None:
        key = (session_id, qa_id)
        async with self._lock:
            ev = self._complete_events.get(key)
            if ev is None:
                ev = asyncio.Event()
                self._complete_events[key] = ev
        ev.set()

    async def get_session_meta(
        self, *, session_id: str, qa_id: str
    ) -> Optional[dict]:
        key = (session_id, qa_id)
        async with self._lock:
            m = self._meta.get(key)
        if m is None:
            return None
        # Re-encode strings → bytes to match Redis hash format the
        # consumer ``chat.py`` polling loop expects (``meta.get(b"status",
        # b"")``).
        encoded: Dict[bytes, bytes] = {}
        for k, v in m.items():
            try:
                encoded[k.encode("utf-8")] = (
                    str(v).encode("utf-8") if not isinstance(v, bytes) else v
                )
            except Exception:  # noqa: BLE001
                continue
        return encoded

    async def get_token_count(
        self, *, session_id: str, qa_id: str
    ) -> int:
        q = await self._queue_for(session_id, qa_id)
        return q.qsize()

    async def get_tokens(
        self,
        *,
        session_id: str,
        qa_id: str,
        start: int = 0,
        end: int = -1,
    ) -> List[bytes]:
        # asyncio.Queue doesn't support indexed access; snapshot the
        # internal deque (private but stable across asyncio versions).
        q = await self._queue_for(session_id, qa_id)
        snapshot = list(q._queue)  # type: ignore[attr-defined]
        if end < 0 or end >= len(snapshot):
            return snapshot[start:]
        return snapshot[start : end + 1]


# ──────────────────────────────────────────────────────────────────────────
# HitlGateRepo — new SQLite tables for HITL pending + session decisions
# ──────────────────────────────────────────────────────────────────────────


_HITL_PENDING_DDL = """
CREATE TABLE IF NOT EXISTS hitl_pending (
    session_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL,
    updated_at INTEGER NOT NULL
)
"""

_HITL_DECISIONS_DDL = """
CREATE TABLE IF NOT EXISTS hitl_decisions (
    session_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL DEFAULT '',
    tool_name TEXT NOT NULL,
    action TEXT NOT NULL,
    args_pattern TEXT NOT NULL DEFAULT '*',
    decided_by TEXT NOT NULL DEFAULT '',
    decided_at INTEGER NOT NULL,
    PRIMARY KEY (session_id, tool_name, args_pattern)
)
"""


class _SqliteHitlGateRepo:
    """HitlGateRepository — SQLite implementation.

    Owns its own table schema (idempotent CREATE IF NOT EXISTS on first
    call). Designed to coexist with ``cli/adapters/storage_sqlite.py``'s
    other tables in the same DB file.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def _ensure(self) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            # Reuse the existing connection pool the SqliteStorage uses.
            from cli.adapters.storage_sqlite import _get_conn
            conn = await _get_conn(self._db_path)
            await conn.execute(_HITL_PENDING_DDL)
            await conn.execute(_HITL_DECISIONS_DDL)
            await conn.commit()
            self._initialized = True

    async def save_pending(
        self,
        *,
        session_id: str,
        workspace_id: str,
        qa_id: str,
        envelope: Dict[str, Any],
    ) -> None:
        await self._ensure()
        from cli.adapters.storage_sqlite import _get_conn
        conn = await _get_conn(self._db_path)
        # Mirror the Mongo payload shape: store everything as one JSON
        # blob keyed by session_id so /hitl/decide can recreate the
        # gate envelope faithfully (matches the Mongo ``hitl_pending``
        # sub-document field-for-field).
        _arguments = envelope.get("arguments") or envelope.get("tool_args") or {}
        payload = {
            "approval_id": envelope.get("approval_id") or "",
            "tool_name": envelope.get("tool_name", ""),
            "tool_call_id": envelope.get("tool_call_id"),
            "arguments": _arguments,
            "tool_args": _arguments,
            "rule_id": envelope.get("rule_id"),
            "policy_message": envelope.get("policy_message", ""),
            "risk_level": envelope.get("risk_level", "low"),
            "editable_args": list(envelope.get("editable_args") or []),
            "scope_options": list(
                envelope.get("scope_options") or ["once", "session", "forever"]
            ),
            "qa_id": qa_id,
            "saved_at": int(time.time() * 1000),
        }
        await conn.execute(
            "INSERT INTO hitl_pending (session_id, workspace_id, payload, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET "
            "  workspace_id=excluded.workspace_id, "
            "  payload=excluded.payload, "
            "  updated_at=excluded.updated_at",
            (session_id, workspace_id, json.dumps(payload, ensure_ascii=False), payload["saved_at"]),
        )
        await conn.commit()

    async def get_pending(
        self, *, session_id: str, workspace_id: str
    ) -> Optional[Dict[str, Any]]:
        await self._ensure()
        from cli.adapters.storage_sqlite import _get_conn
        conn = await _get_conn(self._db_path)
        cursor = await conn.execute(
            "SELECT payload FROM hitl_pending WHERE session_id = ? AND workspace_id = ?",
            (session_id, workspace_id),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except Exception:  # noqa: BLE001
            return None

    async def clear_pending(
        self,
        *,
        session_id: str,
        workspace_id: str,
        decision: str,
        decided_by: str = "",
        reason: str = "",
        approval_id: str = "",
        succeeded: Optional[bool] = None,
    ) -> None:
        await self._ensure()
        from cli.adapters.storage_sqlite import _get_conn
        conn = await _get_conn(self._db_path)
        await conn.execute(
            "DELETE FROM hitl_pending WHERE session_id = ? AND workspace_id = ?",
            (session_id, workspace_id),
        )
        await conn.commit()
        # decision/decided_by/reason/approval_id/succeeded are not
        # persisted in the SQLite backend (CLI doesn't replay audit
        # trails the same way Web does — Mongo path uses
        # ``hitl_decision_v2`` sub-doc + ``hitl_approved_by`` etc.).
        # Sprint 1 PR-E can add a parallel ``hitl_audit`` table if a
        # CLI consumer surfaces a need.

    async def record_session_decision(
        self,
        *,
        session_id: str,
        workspace_id: str,
        tool_name: str,
        action: str,
        args_pattern: str = "*",
        decided_by: str = "",
    ) -> None:
        await self._ensure()
        from cli.adapters.storage_sqlite import _get_conn
        conn = await _get_conn(self._db_path)
        await conn.execute(
            "INSERT INTO hitl_decisions "
            "(session_id, workspace_id, tool_name, action, args_pattern, decided_by, decided_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(session_id, tool_name, args_pattern) DO UPDATE SET "
            "  action=excluded.action, "
            "  decided_by=excluded.decided_by, "
            "  decided_at=excluded.decided_at",
            (
                session_id,
                workspace_id,
                tool_name,
                action,
                args_pattern,
                decided_by,
                int(time.time() * 1000),
            ),
        )
        await conn.commit()

    async def lookup_session_decision(
        self,
        *,
        session_id: str,
        workspace_id: str,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Sprint 2 PR-O0 — query the ``hitl_decisions`` table for a
        matching session-scope allow.

        Strict workspace isolation:``workspace_id`` is part of the
        ``WHERE`` clause, never the primary key, so two workspaces
        can hold independent decisions for the same ``(session_id,
        tool_name)`` pair without collision. PR-C's primary-key
        choice doesn't include ``workspace_id`` (session_id is
        already globally unique in the CLI), but defense-in-depth:
        filter on workspace anyway.

        ``args_pattern="*"`` (the standard session-scope record
        written by ``record_session_decision``) matches any
        ``arguments``. Future enhancement: support exact-signature
        match by hashing ``arguments`` and comparing to a stored
        ``args_signature`` column.

        Fail-soft per Protocol contract: any exception → return
        ``None`` rather than raise, so the agent loop continues to
        the normal prompter path. Never crashes the gate.
        """
        if not session_id or not tool_name:
            return None
        try:
            await self._ensure()
            from cli.adapters.storage_sqlite import _get_conn
            conn = await _get_conn(self._db_path)
            cursor = await conn.execute(
                "SELECT action FROM hitl_decisions "
                "WHERE session_id = ? "
                "  AND workspace_id = ? "
                "  AND tool_name = ? "
                "  AND args_pattern = '*' "
                "  AND action = 'allow' "
                "LIMIT 1",
                (session_id, workspace_id, tool_name),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return str(row[0]) or None
        except Exception as exc:  # noqa: BLE001 — fail-soft per Protocol
            logger.debug(
                "SqliteHitlGateRepo.lookup_session_decision raised "
                "(%s) — returning None so agent loop continues",
                exc,
            )
            return None


# ──────────────────────────────────────────────────────────────────────────
# ArtifactStore — local FS implementation (same shape as Mongo backend)
# ──────────────────────────────────────────────────────────────────────────


class _SqliteArtifactStore:
    """ArtifactStore — local FS via CheckpointManager + TrajectoryRecorder.

    Shape-identical to ``_MongoArtifactStore``. The Mongo / SQLite
    distinction at the StorageBackend layer is about identity tagging,
    not behaviour — CheckpointManager and TrajectoryRecorder already
    default to local FS when their respective Mongo toggles (off in
    CLI context) are off.
    """

    def __init__(self) -> None:
        self._checkpoint = None
        self._trajectory = None

    def _get_checkpoint(self) -> Any:
        if self._checkpoint is None:
            from vendor_runtime_sdk.runtime.checkpoint.manager import CheckpointManager
            self._checkpoint = CheckpointManager()
        return self._checkpoint

    def _get_trajectory(self) -> Any:
        if self._trajectory is None:
            from vendor_runtime_sdk.runtime.checkpoint.trajectory import TrajectoryRecorder
            self._trajectory = TrajectoryRecorder()
        return self._trajectory

    def save_checkpoint(
        self,
        *,
        session_id: str,
        workspace_id: str,
        state: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        meta = dict(metadata or {})
        if workspace_id and "workspace_id" not in meta:
            meta["workspace_id"] = workspace_id
        return self._get_checkpoint().save(session_id, state, meta)

    def record_turn(
        self,
        *,
        session_id: str,
        workspace_id: str,
        turn_id: str,
        messages: List[Dict[str, Any]],
        outcome: str = "success",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        meta = dict(metadata or {})
        if workspace_id and "workspace_id" not in meta:
            meta["workspace_id"] = workspace_id
        self._get_trajectory().record_turn(
            session_id, turn_id, messages, outcome, meta,
        )

    def record_failure(
        self,
        *,
        session_id: str,
        workspace_id: str,
        turn_id: str,
        messages: List[Dict[str, Any]],
        error: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        meta = dict(metadata or {})
        if workspace_id and "workspace_id" not in meta:
            meta["workspace_id"] = workspace_id
        self._get_trajectory().record_failure(
            session_id, turn_id, messages, error, meta,
        )


# ──────────────────────────────────────────────────────────────────────────
# Composition root
# ──────────────────────────────────────────────────────────────────────────


class SqliteStorageBackend:
    """Local-first StorageBackend (SQLite + in-memory + local FS).

    The 5 long-existing DAO methods (sessions / qa / memory / cost /
    coordinator_threads) are served by the flat ``SqliteStorage`` class
    in ``cli/adapters/storage_sqlite.py`` — its method set already
    matches the Protocol signatures. We expose ONE shared instance via
    sub-attribute wrappers so consumers can call e.g.
    ``self._storage.sessions.get_session(...)`` even though the
    underlying methods all live on the flat ``SqliteStorage``.

    Satisfies ``runtime.storage.backend.StorageBackend`` Protocol.
    """

    name: Literal["sqlite"] = "sqlite"

    def __init__(self, db_path: Optional[str] = None) -> None:
        # Resolve db path: explicit arg → env override → default.
        resolved = db_path or os.environ.get("AIBUDDY_RUNTIME_DB") or _DEFAULT_DB_PATH
        if resolved.startswith("~"):
            resolved = os.path.expanduser(resolved)
        self._db_path = resolved

        from cli.adapters.storage_sqlite import SqliteStorage
        self._storage = SqliteStorage(self._db_path)

        # The flat ``SqliteStorage`` class implements 5/5 DAO Protocols
        # in one object. Wrap it in 5 lightweight per-protocol facades
        # so callers can write ``self.sessions.get_session(...)`` even
        # though all five method sets live on the same instance. The
        # facades hold no state — they delegate every call.
        self.sessions = _SqliteFacade(self._storage)
        self.qa = _SqliteFacade(self._storage)
        self.memory = _SqliteFacade(self._storage)
        self.cost = _SqliteFacade(self._storage)
        self.coordinator_threads = _SqliteFacade(self._storage)

        # New adapters added by PR-C.
        self.hitl_gates = _SqliteHitlGateRepo(self._db_path)
        self.artifacts = _SqliteArtifactStore()

        # Stream sink: in-memory (no Redis dependency in CLI).
        self.stream_sink = _InMemoryStreamSink()

        # Registry store: in-process for CLI; honours the same factory
        # so a configured Redis client (rare in CLI) still wins.
        from vendor_runtime_sdk.runtime.cache.registry_store import get_registry_store
        self.registry_store = get_registry_store()

    async def initialize(self) -> None:
        """Eagerly initialize the SQLite schema. Optional — every method
        also self-initializes on first call. Useful for tests that want
        to fail fast on a bad ``db_path``.
        """
        await self._storage.initialize()


class _SqliteFacade:
    """One-attribute delegate to a shared ``SqliteStorage`` instance.

    ``SqliteStorage`` is a flat 5-protocol implementation (sessions +
    qa + memory + cost + coordinator_threads methods on the same
    class). The ``StorageBackend`` Protocol expects 5 named sub-objects
    each carrying ONE protocol's methods, so we wrap with this facade
    — ``getattr(facade, "get_session")`` returns the bound method on
    the underlying storage.

    Pure delegation: no per-facade state, no method filtering.
    Python's duck-typing accepts the facade as any of the 5 protocols
    because the method names are unique across protocols.
    """

    def __init__(self, storage: Any) -> None:
        self._s = storage

    def __getattr__(self, name: str) -> Any:
        return getattr(self._s, name)


__all__ = ["SqliteStorageBackend"]
