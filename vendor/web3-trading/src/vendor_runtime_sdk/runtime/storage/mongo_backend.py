# -*- coding: utf-8 -*-
"""
MongoStorageBackend — production Web backend implementation.

Sprint 0 PR-B delivery (docs/TUI-Web-Runtime同构化技术方案.md §A2 + §E).

Wraps the 9 existing production data sources behind the
``StorageBackend`` Protocol:

* Mongo via ``agent.schema`` models (SessionModel / QAModel / MemoryModel)
  and the ``ai_assistant_db.kia_*`` collections directly for HITL gates.
* Mongo via ``dao.thread_dao.ThreadDAO`` for coordinator threads —
  re-exposed through the existing ``MongoCoordinatorStateStore`` adapter
  that ``state_store.py:395`` already maintains.
* MySQL via ``dao.mysql.cost_record.CostRecordDao`` for cost
  attribution (it's not actually Mongo, but it's the production cost
  sink that pairs with the Mongo / Redis stack — grouping under the
  "mongo" backend keeps the dichotomy clean for the consumer).
* Redis via the :class:`runtime.protocols.session_cache.SessionCache`
  Protocol for the SSE stream sink (PR-E*c — the ai-buddy adapter
  wraps ``web.api.chat.cache.RedisCache`` underneath).
* Local filesystem via ``CheckpointManager`` + ``TrajectoryRecorder``
  for artifacts (Mongo upgrade per Sprint 9 toggles handled inside
  those classes — backend just calls through).

Lazy-init contract
------------------
``__init__`` does NO Mongo / Redis / MySQL / disk I/O. It wires
adapter classes that defer their actual data-source touches to the
first method call. This keeps Sprint 1 PR-E's flip-to-storage-backend
free of construction-time latency regression: every chat request now
allocates 9 lightweight wrappers, no connection setup.

Sprint 0 PR-B specifically ships a "passive" version — the
``ConversationRuntime`` accepts ``storage`` as an optional kwarg but
the mixins do NOT yet call ``self._storage.*``. PR-E flips actual
usage. Until then the backend exists for type-system + factory contract
verification, and ``chat.py`` constructs+passes it so the wiring path
is exercised.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal, Optional

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# Workspace ContextVar assertion helper (Sprint 1 PR-H review M1 fix)
# ──────────────────────────────────────────────────────────────────────────


class WorkspaceIsolationError(RuntimeError):
    """Raised when an explicit ``workspace_id`` kwarg disagrees with the
    ambient ``OwnershipMiddleware`` ContextVar.

    Existing DAO adapters wrap ``SessionModel.get`` / ``QAModel.get`` /
    ``MemoryModel.get`` which read workspace from the ContextVar set by
    ``OwnershipMiddleware`` (HTTP) or ``set_ownership`` (Celery / CLI).
    The Protocol exposes ``workspace_id`` as a kwarg — when callers pass
    a value, the two MUST agree or we have an isolation breach in the
    making (a Sprint 2+ caller from a context where the ContextVar
    points at a different workspace than the one the caller intends).

    Fail-closed: raise rather than silently honour either value.
    """


def _assert_workspace_or_fall_back(workspace_id: str, *, adapter: str) -> None:
    """Three-way check against ``OwnershipMiddleware`` ContextVar:

    * Both empty → DAO will see "" and skip the workspace filter
      (legacy admin-tooling path). Allowed.
    * Both set, agree → consistent — no-op.
    * Both set, disagree → raise ``WorkspaceIsolationError`` (fail-
      closed; isolation contract broken).
    * Caller empty, CtxVar set → DAO honours CtxVar (legacy HTTP path).
      Allowed.
    * Caller set, CtxVar empty → DAO will skip the workspace filter
      and the caller's intent is lost. Raise — this is the silent
      cross-workspace bug the review flagged.

    Defensive: any unexpected exception from the middleware import
    (e.g. tests that monkeypatch ``web.middleware``) falls through to
    "no assertion" — the existing legacy behaviour is preserved.
    """
    if not workspace_id:
        return  # caller didn't promise anything; defer to ContextVar.
    try:
        # PR-E2 (SDK extraction §5 PR-E2): get_workspace_id is now sourced
        # from runtime.context.  The legacy web.middleware.get_workspace_id
        # continues to populate the same value via the fallback path, so
        # the runtime behaviour is unchanged in Phase 0.  Phase 2 removes
        # the fallback when web/ leaves the engine import surface.
        from vendor_runtime_sdk.runtime.context import get_workspace_id as _get_ws
        ctx_ws = _get_ws()
    except Exception:  # noqa: BLE001 — middleware unreachable; skip check
        return
    if not ctx_ws:
        # Caller passed an explicit workspace but the ContextVar is
        # empty — the DAO would ignore the caller's intent.
        raise WorkspaceIsolationError(
            f"{adapter}: caller passed workspace_id={workspace_id!r} but "
            "OwnershipMiddleware ContextVar is empty — DAO would skip "
            "the workspace filter, silently leaking across workspaces. "
            "Call ``set_ownership(workspace_id, owner_id)`` before "
            "invoking this adapter from Celery / CLI / script contexts."
        )
    if ctx_ws != workspace_id:
        raise WorkspaceIsolationError(
            f"{adapter}: caller passed workspace_id={workspace_id!r} "
            f"but ContextVar is {ctx_ws!r} — these MUST agree."
        )


# ──────────────────────────────────────────────────────────────────────────
# Sub-Protocol adapters — each wraps an existing DAO / sink lazily.
# ──────────────────────────────────────────────────────────────────────────


class _MongoSessionRepo:
    """SessionRepository — wraps ``agent.schema.SessionModel`` + direct
    ``ai_assistant_db.kia_sessions`` access for list / soft-delete.

    Workspace isolation: ``SessionModel.get`` already consults the
    ``OwnershipMiddleware`` ContextVar so HTTP-path calls inherit
    workspace correctly. Daemon/CLI callers must set workspace via
    ``set_ownership`` before invoking — Protocol method takes
    ``workspace_id`` for explicit threading once Sprint 1 wires it.
    """

    async def get_session(
        self, session_id: str, workspace_id: str = ""
    ) -> Optional[Dict[str, Any]]:
        _assert_workspace_or_fall_back(
            workspace_id, adapter="MongoSessionRepo.get_session",
        )
        from vendor_runtime_sdk.agent.schema import SessionModel
        # SessionModel.get returns a raw dict in this codebase.
        # Workspace filter is honoured via ``OwnershipMiddleware``
        # ContextVar (read at ``agent/schema.py:416-420``); the
        # assertion above guarantees the ContextVar and the explicit
        # kwarg agree.
        return await SessionModel.get(session_id)

    async def save_session(self, session: Dict[str, Any]) -> None:
        from vendor_runtime_sdk.agent.schema import SessionModel
        model = SessionModel(**session)
        await model.save()

    async def list_sessions(
        self,
        user_id: str,
        workspace_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> List[Dict[str, Any]]:
        # PR-E3 (SDK extraction §5 PR-E3): ai_assistant_db is now accessed
        # via the ContextStore Protocol.  The legacy
        # dao.mongo.dbs.ai_assistant_db is still used via the
        # _LegacyContextStoreProvider fallback so runtime behaviour is
        # unchanged in Phase 0.  Phase 2 removes the fallback when dao/
        # leaves the engine import surface.
        from vendor_runtime_sdk.runtime.protocols.context_store import get_context_store
        coll = await get_context_store().get_collection("kia_sessions").collection
        cursor = (
            coll.find({"userId": user_id, "workspace_id": workspace_id})
            .sort("createTime", -1)
            .skip(max(0, (page - 1) * page_size))
            .limit(page_size)
        )
        return [doc async for doc in cursor]

    async def delete_session(self, session_id: str, workspace_id: str) -> None:
        # delete_session already threads workspace_id through the
        # matcher (correct shape); add the same assertion so callers
        # passing a workspace different from the ambient ContextVar
        # surface that bug fast rather than corrupting data.
        _assert_workspace_or_fall_back(
            workspace_id, adapter="MongoSessionRepo.delete_session",
        )
        # PR-E3 (SDK extraction §5 PR-E3): ai_assistant_db is now accessed
        # via the ContextStore Protocol.  The legacy
        # dao.mongo.dbs.ai_assistant_db is still used via the
        # _LegacyContextStoreProvider fallback so runtime behaviour is
        # unchanged in Phase 0.  Phase 2 removes the fallback when dao/
        # leaves the engine import surface.
        from vendor_runtime_sdk.agent.schema import get_timestamp
        from vendor_runtime_sdk.runtime.protocols.context_store import get_context_store
        await get_context_store().get_collection("kia_sessions").add_or_update_one(
            matcher={"id": session_id, "workspace_id": workspace_id},
            data={"isDeleted": True, "updateTime": get_timestamp()},
        )


class _MongoQARepo:
    """QARepository — wraps ``agent.schema.QAModel`` static methods."""

    async def get_qa(
        self, qa_id: str, workspace_id: str = ""
    ) -> Optional[Dict[str, Any]]:
        _assert_workspace_or_fall_back(
            workspace_id, adapter="MongoQARepo.get_qa",
        )
        from vendor_runtime_sdk.agent.schema import QAModel
        return await QAModel.get(qa_id)

    async def save_qa(self, qa: Dict[str, Any]) -> None:
        from vendor_runtime_sdk.agent.schema import QAModel
        model = QAModel(**qa)
        await model.save()

    async def get_history(
        self,
        session_id: str,
        user_id: str,
        workspace_id: str = "",
        top_k: int = 20,
    ) -> List[Dict[str, Any]]:
        from vendor_runtime_sdk.agent.schema import QAModel
        return await QAModel.get_history(session_id, user_id, top_k=top_k)


class _MongoMemoryRepo:
    """MemoryRepository — wraps ``agent.schema.MemoryModel`` + direct
    ``ai_assistant_db.kia_memory`` for listing.

    Memory's primary surface is ``MemoryStore`` / Mem0AI (vector
    service); ``kia_memory`` collection is the raw fallback store.
    This adapter targets the raw collection — same shape as the rest
    of the schema-level CRUD wrappers.
    """

    async def get_memory(
        self, memory_id: str, workspace_id: str = ""
    ) -> Optional[Dict[str, Any]]:
        _assert_workspace_or_fall_back(
            workspace_id, adapter="MongoMemoryRepo.get_memory",
        )
        # PR-E3 (SDK extraction §5 PR-E3): ai_assistant_db is now accessed
        # via the ContextStore Protocol.  The legacy
        # dao.mongo.dbs.ai_assistant_db is still used via the
        # _LegacyContextStoreProvider fallback so runtime behaviour is
        # unchanged in Phase 0.  Phase 2 removes the fallback when dao/
        # leaves the engine import surface.
        from vendor_runtime_sdk.runtime.protocols.context_store import get_context_store
        coll = await get_context_store().get_collection("kia_memory").collection
        # Sprint 1 PR-H review M1 fix: thread workspace_id into the
        # query when set so we don't lean ONLY on the ContextVar (which
        # ``find_one`` doesn't auto-inject — only ``DaoHelper`` wrapper
        # methods do).
        query: Dict[str, Any] = {"id": memory_id}
        if workspace_id:
            query["workspace_id"] = workspace_id
        return await coll.find_one(query)

    async def save_memory(self, memory: Dict[str, Any]) -> None:
        from vendor_runtime_sdk.agent.schema import MemoryModel
        model = MemoryModel(**memory)
        await model.save()

    async def list_memory(
        self,
        user_id: str,
        workspace_id: str = "",
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        # PR-E3 (SDK extraction §5 PR-E3): ai_assistant_db is now accessed
        # via the ContextStore Protocol.  The legacy
        # dao.mongo.dbs.ai_assistant_db is still used via the
        # _LegacyContextStoreProvider fallback so runtime behaviour is
        # unchanged in Phase 0.  Phase 2 removes the fallback when dao/
        # leaves the engine import surface.
        from vendor_runtime_sdk.runtime.protocols.context_store import get_context_store
        query: Dict[str, Any] = {}
        if user_id:
            query["userId"] = user_id
        if workspace_id:
            query["workspace_id"] = workspace_id
        if session_id:
            query["sessionId"] = session_id
        coll = await get_context_store().get_collection("kia_memory").collection
        return [doc async for doc in coll.find(query)]


class _MongoCostRepo:
    """CostRepository — wraps ``dao.mysql.cost_record.CostRecordDao``.

    Cost records live in MySQL (``cost_records`` table) in production;
    grouping under the "mongo" backend keeps the dichotomy clean for
    consumers (mongo backend = the entire production stack;
    sqlite backend = local).
    """

    async def add_cost_record(self, record: Dict[str, Any]) -> None:
        from dao.mysql.cost_record import get_cost_record_dao
        dao = get_cost_record_dao()
        await dao.add_record(record)

    async def list_pending(
        self, workspace_id: str, limit: int = 100
    ) -> List[Dict[str, Any]]:
        # Production CLI offline-sync path — server has no pending queue.
        return []

    async def mark_synced(self, record_id: str) -> None:
        # No-op on server (CLI offline-sync is a one-way push).
        return None


class _MongoHitlGateRepo:
    """HitlGateRepository — direct ``ai_assistant_db.kia_sessions``
    field writes, mirroring the existing ``_persist_hitl_pending`` /
    ``_handle_approve`` bodies. No Mongo I/O at __init__.

    Sprint 1 PR-E will replace the inline ``_persist_hitl_pending``
    body in ``_stream.py`` with a call to this adapter. Until then this
    method is callable but not yet invoked by the runtime.
    """

    async def save_pending(
        self,
        *,
        session_id: str,
        workspace_id: str,
        qa_id: str,
        envelope: Dict[str, Any],
    ) -> None:
        # PR-E3 (SDK extraction §5 PR-E3): ai_assistant_db is now accessed
        # via the ContextStore Protocol.  The legacy
        # dao.mongo.dbs.ai_assistant_db is still used via the
        # _LegacyContextStoreProvider fallback so runtime behaviour is
        # unchanged in Phase 0.  Phase 2 removes the fallback when dao/
        # leaves the engine import surface.
        from vendor_runtime_sdk.agent.schema import get_timestamp
        from vendor_runtime_sdk.runtime.protocols.context_store import get_context_store
        _arguments = envelope.get("arguments") or envelope.get("tool_args") or {}
        await get_context_store().get_collection("kia_sessions").add_or_update_one(
            matcher={"id": session_id},
            data={
                "hitl_pending": {
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
                    "saved_at": get_timestamp(),
                },
                "updateTime": get_timestamp(),
            },
        )

    async def get_pending(
        self, *, session_id: str, workspace_id: str
    ) -> Optional[Dict[str, Any]]:
        from vendor_runtime_sdk.agent.schema import SessionModel
        doc = await SessionModel.get(session_id)
        if not doc:
            return None
        return (doc or {}).get("hitl_pending") or None

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
        # PR-E3 (SDK extraction §5 PR-E3): ai_assistant_db is now accessed
        # via the ContextStore Protocol.  The legacy
        # dao.mongo.dbs.ai_assistant_db is still used via the
        # _LegacyContextStoreProvider fallback so runtime behaviour is
        # unchanged in Phase 0.  Phase 2 removes the fallback when dao/
        # leaves the engine import surface.
        from vendor_runtime_sdk.agent.schema import get_timestamp
        from vendor_runtime_sdk.runtime.protocols.context_store import get_context_store
        # Mirrors hitl.py:_handle_approve / _handle_reject body shape.
        is_approve = decision == "approve"
        update_data: Dict[str, Any] = {
            "hitl_pending": None,
            "hitl_approved": is_approve,
            "hitl_rejected": (not is_approve),
            "hitl_reason": reason or "",
            "hitl_at": get_timestamp(),
            "hitl_decision_v2": {
                "action": decision,
                "approval_id": approval_id,
                "decided_at": get_timestamp(),
            },
            "updateTime": get_timestamp(),
        }
        if is_approve:
            update_data["hitl_approved_by"] = decided_by
        else:
            update_data["hitl_rejected_by"] = decided_by
        await get_context_store().get_collection("kia_sessions").add_or_update_one(
            matcher={"id": session_id}, data=update_data,
        )

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
        # Delegate to the existing ``runtime.policy.decision_memory.record``
        # so the Mongo write path stays single-sourced. This adapter
        # only adds the Protocol shape; the persistence logic + the
        # double-await fix for DaoHelper.collection live there.
        #
        # Sprint 1 PR-H review M3 fix: thread ``decided_by`` through as
        # ``user_id`` so the audit trail row carries the actor identity.
        # Empty fallback to ``""`` preserves pre-fix behaviour when
        # callers don't supply ``decided_by`` (legacy unit tests, etc.).
        from vendor_runtime_sdk.runtime.policy.decision_memory import record as _hitl_record
        await _hitl_record(
            session_id=session_id,
            user_id=decided_by or "",
            workspace_id=workspace_id,
            tool_name=tool_name,
            arguments={},
            scope="session",
            decided_by=decided_by,
            args_pattern=args_pattern,
        )

    async def lookup_session_decision(
        self,
        *,
        session_id: str,
        workspace_id: str,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Sprint 2 PR-O0 — delegate to existing ``decision_memory.lookup``.

        Mongo backend already has a richer lookup that also checks
        forever (user×workspace) decisions; we forward to it directly.
        ``user_id`` isn't carried at this Protocol layer — only session
        scope matches via ``session_id``. Forever-scope hits via this
        path require future enhancement of threading ``user_id``
        through the runtime → dispatch → repository chain.

        Fail-soft: any exception → return ``None`` so the agent loop
        falls back to the normal prompter path.
        """
        try:
            from vendor_runtime_sdk.runtime.policy.decision_memory import lookup as _hitl_lookup
            return await _hitl_lookup(
                session_id=session_id,
                user_id="",  # session-scope only; forever requires user_id threading
                workspace_id=workspace_id,
                tool_name=tool_name,
                arguments=arguments,
            )
        except Exception as exc:  # noqa: BLE001 — fail-soft per Protocol contract
            logger.debug(
                "MongoHitlGateRepo.lookup_session_decision raised "
                "(%s) — returning None so agent loop continues",
                exc,
            )
            return None


class _MongoCoordinatorThreadRepoAdapter:
    """CoordinatorThreadRepository — re-uses the existing
    ``state_store.MongoCoordinatorStateStore`` which already wraps
    ``ThreadDAO`` with the Protocol's exact 3 methods. We delegate to
    the live instance via the global ``get_coordinator_state_store``
    factory so workspace_id propagation matches what coordinator code
    already does.

    Lazy: we don't instantiate the underlying store at __init__ —
    deferred to first method call.
    """

    def __init__(self) -> None:
        self._delegate = None  # populated on first call

    def _get_delegate(self) -> Any:
        if self._delegate is None:
            from vendor_runtime_sdk.agent.coordinator.state_store import get_coordinator_state_store
            self._delegate = get_coordinator_state_store()
        return self._delegate

    async def upsert_thread(
        self, workspace_id: str, doc: Dict[str, Any]
    ) -> None:
        await self._get_delegate().upsert_thread(workspace_id, doc)

    async def find_by_session(
        self, workspace_id: str, coordinator_session_id: str
    ) -> List[Dict[str, Any]]:
        return await self._get_delegate().find_by_session(
            workspace_id, coordinator_session_id
        )

    async def get_thread(
        self, workspace_id: str, thread_id: str
    ) -> Optional[Dict[str, Any]]:
        return await self._get_delegate().get_thread(workspace_id, thread_id)


class _MongoArtifactStore:
    """ArtifactStore — composes ``CheckpointManager`` + ``TrajectoryRecorder``.

    Both already gracefully degrade to local FS when their respective
    Mongo toggles (``checkpoint_mongo`` / ``trajectory_mongo``) are off.
    This adapter just adds the Protocol facade and threads ``workspace_id``
    for future per-workspace sharding.
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
        # CheckpointManager.save signature: (session_id, state, metadata).
        # workspace_id flows through metadata for the Mongo sink.
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


class _RedisStreamSink:
    """StreamSink — proxies through the :class:`SessionCache` Protocol.

    PR-E*c (SDK extraction §5 PR-E*c): each call resolves the
    installed :class:`runtime.protocols.session_cache.SessionCache`
    instance via :func:`get_session_cache`. In Phase 0 that returns
    a lazy adapter wrapping ``web.api.chat.cache.RedisCache`` so the
    runtime behaviour is byte-identical. Phase 2 removes the
    re-export when ``web/`` leaves the engine import surface.
    """

    @staticmethod
    def _cache():
        from vendor_runtime_sdk.runtime.protocols.session_cache import get_session_cache
        return get_session_cache()

    async def append_token(
        self,
        *,
        session_id: str,
        qa_id: str,
        token: str,
        ttl: int = 600,
    ) -> Optional[int]:
        return await self._cache().append_token(
            session_id=session_id, qa_id=qa_id, token=token, ttl=ttl,
        )

    async def update_session_status(
        self,
        *,
        session_id: str,
        qa_id: str,
        status: str,
        log: str = "",
        ttl: int = 600,
    ) -> None:
        await self._cache().update_session_status(
            session_id=session_id,
            qa_id=qa_id,
            status=status,
            log=log,
            ttl=ttl,
        )

    async def publish_complete(
        self, *, session_id: str, qa_id: str
    ) -> None:
        await self._cache().publish_complete(
            session_id=session_id, qa_id=qa_id,
        )

    async def get_session_meta(
        self, *, session_id: str, qa_id: str
    ) -> Optional[dict]:
        return await self._cache().get_session_meta(
            session_id=session_id, qa_id=qa_id,
        )

    async def get_token_count(
        self, *, session_id: str, qa_id: str
    ) -> int:
        return await self._cache().get_token_count(
            session_id=session_id, qa_id=qa_id,
        )

    async def get_tokens(
        self,
        *,
        session_id: str,
        qa_id: str,
        start: int = 0,
        end: int = -1,
    ) -> List[Any]:
        return await self._cache().get_tokens(
            session_id=session_id, qa_id=qa_id, start=start, end=end,
        )


# ──────────────────────────────────────────────────────────────────────────
# Composition root
# ──────────────────────────────────────────────────────────────────────────


class MongoStorageBackend:
    """Production-stack StorageBackend (Mongo + MySQL + Redis + FS).

    Wires 9 adapter wrappers around existing DAOs. ``__init__`` performs
    zero data-source I/O — every wrapper defers its calls. This keeps
    Sprint 1 PR-E's flip safe: constructing a backend per request adds
    only a handful of object allocations, no connection setup.

    Satisfies the ``runtime.storage.backend.StorageBackend`` Protocol
    (composition by attribute, not inheritance).
    """

    name: Literal["mongo"] = "mongo"

    def __init__(self) -> None:
        self.sessions = _MongoSessionRepo()
        self.qa = _MongoQARepo()
        self.memory = _MongoMemoryRepo()
        self.cost = _MongoCostRepo()
        self.coordinator_threads = _MongoCoordinatorThreadRepoAdapter()
        self.hitl_gates = _MongoHitlGateRepo()
        self.artifacts = _MongoArtifactStore()
        self.stream_sink = _RedisStreamSink()
        # RegistryStore lives behind its own factory (Redis vs in-process
        # decided by ``registry_redis`` toggle + Redis availability).
        from vendor_runtime_sdk.runtime.cache.registry_store import get_registry_store
        self.registry_store = get_registry_store()


__all__ = ["MongoStorageBackend"]
