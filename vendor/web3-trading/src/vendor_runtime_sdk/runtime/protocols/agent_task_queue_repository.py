# -*- coding: utf-8 -*-
"""
AgentTaskQueueRepository — PR-E4b of the Agent Engine SDK extraction plan.

See ``docs/Agent-Engine-SDK-剥离方案.md`` §5 Phase 0 PR-E4b.

Goal
----
Replace the engine layer's direct dependency on
``dao.mysql.agent_task_queue`` (the ai-buddy-specific MySQL DAO
singleton) with a Protocol-based seam. SDK consumers install their own
:class:`AgentTaskQueueRepository` at boot; ai-buddy installs an adapter
that wraps :func:`dao.mysql.agent_task_queue.get_agent_task_queue_dao`
so the existing engine code path is byte-identical.

Today the engine call sites that need queue state do::

    from dao.mysql.agent_task_queue import get_agent_task_queue_dao
    dao = get_agent_task_queue_dao()
    await dao.get_by_id(queue_id)
    await dao.create(item)
    await dao.update_status(queue_id, "running", error=None)
    await dao.count_active_by_agent(agent_id)
    await dao.list_pending_cancels(agent_id)
    await dao.ack_cancel(task_id)
    # plus claim_for_worker / update_status_cas / list_by_agent

That import path is unreachable when the engine is packaged as the SDK
:mod:`kucoin-agent-runtime-sdk` (``dao/`` is the business layer, kept
outside the SDK).

Scope (V1)
----------
This PR handles the 10 engine call sites concentrated in
``src/agent/schedule/agent_task_dispatcher.py``. The Protocol surface
covers:

* :meth:`get_by_id` — single-task lookup (dispatch_now / fall-back
  lookup inside ``_dispatch_single``).
* :meth:`create` — exposed for future engine paths that spawn queue
  rows (kept symmetric with :class:`AgentRepository.create`); the
  current dispatcher only reads.
* :meth:`update_status` — FSM transition path with optional
  ``error_message`` carry. Non-CAS only; the CAS-guarded variant
  ``update_status_cas`` and ``claim_for_worker`` (§Gap 6
  worker-CAS pair gated by ``worker_cas_verification``) plus
  ``list_by_agent`` stay on the concrete ``AgentTaskQueueDao`` —
  they are deferred to PR-E4c when the CAS Protocol surface is
  designed alongside the rest of the dispatcher loop.
* :meth:`count_active_by_agent` — capacity probe before every dispatch.
* :meth:`list_pending_cancels` — the per-tick staff-CLI cancel feed.
* :meth:`ack_cancel` — worker-side cancel completion stamp.

The HTTP / CLI-only surfaces (``list_queued_user_ids`` /
``list_queued_tasks_for_user`` / ``cancel_by_issue`` /
``request_cancel``) stay on the concrete ``AgentTaskQueueDao`` —
they're called from staff API routers + watchdog services, not engine
code paths.

AgentTaskQueueRow + WorkerClaimResult re-export
-----------------------------------------------
Both dataclasses currently live in
``src/dao/mysql/agent_task_queue.py``. PR-E4b re-exports them from this
protocol module via a guarded import: when ``dao.mysql.agent_task_queue``
is reachable we re-export the canonical dataclasses; otherwise we
synthesise minimal local replicas with the same field surface. In
Phase 2 (post-extraction) the local replicas become canonical.

Fall-back path (PR-E4b only; deleted in Phase 2)
------------------------------------------------
When no provider is installed via
:func:`set_agent_task_queue_repository`,
:func:`get_agent_task_queue_repository` lazily synthesises one that
wraps :func:`dao.mysql.agent_task_queue.get_agent_task_queue_dao`.

Same pattern as PR-E4 :class:`WorkflowRunRepository` /
:class:`CostRecordRepository` — engine carries its own contract;
business layer keeps its own concrete types; the SDK seam lives at the
import boundary.
"""

from __future__ import annotations

import copy
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ── AgentTaskQueueRow + WorkerClaimResult re-export ────────────────────


try:
    from dao.mysql.agent_task_queue import (
        AgentTaskQueueRow as _LegacyAgentTaskQueueRow,
    )
    from dao.mysql.agent_task_queue import (
        WorkerClaimResult as _LegacyWorkerClaimResult,
    )
    AgentTaskQueueRow = _LegacyAgentTaskQueueRow  # type: ignore[misc,assignment]
    WorkerClaimResult = _LegacyWorkerClaimResult  # type: ignore[misc,assignment]
except ImportError:  # pragma: no cover — exercised only in SDK-extracted scenario
    @dataclass
    class AgentTaskQueueRow:  # type: ignore[no-redef]
        """Minimal local replica of
        :class:`dao.mysql.agent_task_queue.AgentTaskQueueRow`.

        Activated only when ``dao.mysql.agent_task_queue`` is not
        importable — i.e. the SDK-extracted scenario.
        """

        id: str = ""
        agent_id: str = ""
        issue_id: str = ""
        status: str = "queued"
        priority: int = 0
        dispatched_at: Optional[str] = None
        started_at: Optional[str] = None
        completed_at: Optional[str] = None
        result: Optional[Dict[str, Any]] = None
        error: Optional[str] = None
        created_at: str = ""
        cancel_requested_at: Optional[str] = None
        cancelled_by: Optional[str] = None
        cancel_reason: Optional[str] = None
        cancel_ack_at: Optional[str] = None
        worker_id: Optional[str] = None
        worker_claimed_at: Optional[str] = None

    @dataclass(frozen=True)
    class WorkerClaimResult:  # type: ignore[no-redef]
        """Minimal local replica of
        :class:`dao.mysql.agent_task_queue.WorkerClaimResult`."""

        acquired: bool = False
        task_id: str = ""
        worker_id: str = ""
        held_by: Optional[str] = None
        reason: str = ""


class AgentTaskQueueRepositoryNotInstalledError(RuntimeError):
    """Raised when :func:`get_agent_task_queue_repository` is called
    before any repository is installed AND the legacy
    ``dao.mysql.agent_task_queue`` fallback is not reachable.
    """


_ACTIVE_STATUSES: frozenset[str] = frozenset(
    {"queued", "dispatched", "running"}
)
# ``_TERMINAL_STATUSES`` was defined here for the deferred
# ``claim_for_worker`` CAS path but had no reachable consumer — removed
# in the PR-E4b review pass.  When PR-E4c reintroduces claim_for_worker
# the constant should live alongside that method.


@runtime_checkable
class AgentTaskQueueRepository(Protocol):
    """Pluggable repository for agent_task_queue persistence.

    Methods are coarse-grained business operations matched 1:1 to the
    10 audited engine call sites in
    ``src/agent/schedule/agent_task_dispatcher.py``.

    Implementations MUST be safe to call concurrently — the dispatcher
    fans out per-agent claims in parallel.
    """

    async def get_by_id(self, queue_id: str) -> Optional[AgentTaskQueueRow]:
        """Return the queue row, or ``None`` if not found.

        Implementations MUST return a fresh instance (or a deep copy);
        engine code mutates the returned row during the dispatch loop.
        """
        ...

    async def create(self, item: AgentTaskQueueRow) -> str:
        """Insert a new queue row. Returns the inserted ``id`` (server-
        assigned via :func:`uuid.uuid4` when ``item.id`` is empty).
        """
        ...

    async def update_status(
        self,
        queue_id: str,
        new_status: str,
        *,
        error_message: Optional[str] = None,
    ) -> int:
        """Apply an FSM-style status update.

        The legacy DAO accepts ``result`` and ``error`` kwargs; the
        Protocol exposes only ``error_message`` because that's all the
        audited engine paths pass. Implementations MAY accept extra
        kwargs through ``**kwargs`` for forward compatibility.

        Returns the number of rows affected (``1`` on success, ``0``
        when the row vanished mid-flight).
        """
        ...

    async def count_active_by_agent(self, agent_id: str) -> int:
        """Return the number of rows for ``agent_id`` in
        ``queued`` / ``dispatched`` / ``running`` status.
        """
        ...

    async def list_pending_cancels(
        self, agent_id: str
    ) -> List[AgentTaskQueueRow]:
        """Rows with an outstanding cancel-request — i.e.
        ``cancel_requested_at IS NOT NULL AND cancel_ack_at IS NULL``.

        Returned list MAY be empty; implementations MUST NOT return
        ``None``. Order matches the staff CLI's expectation of
        ``cancel_requested_at ASC``.
        """
        ...

    async def ack_cancel(self, task_id: str) -> int:
        """Worker-side ack that the in-flight run has stopped.

        Writes ``cancel_ack_at = NOW()`` AND flips the row to
        ``status='cancelled'`` with ``completed_at = NOW()``. Returns
        the number of rows affected (``1`` on success, ``0`` when the
        row never had ``cancel_requested_at`` set or has already been
        ack'd).
        """
        ...


# ── Module-level singleton ──────────────────────────────────────────────


_agent_task_queue_repository: Optional[AgentTaskQueueRepository] = None


def set_agent_task_queue_repository(
    repo: AgentTaskQueueRepository,
) -> None:
    """Install the AgentTaskQueueRepository used by engine modules.

    Idempotent — subsequent calls overwrite. Logs at INFO so boot order
    is auditable.

    Raises:
        TypeError: when ``repo`` does not satisfy the
            :class:`AgentTaskQueueRepository` Protocol at the
            structural level.
    """
    if not isinstance(repo, AgentTaskQueueRepository):
        raise TypeError(
            f"set_agent_task_queue_repository: repo must satisfy "
            f"AgentTaskQueueRepository Protocol (get_by_id / create / "
            f"update_status / count_active_by_agent / "
            f"list_pending_cancels / ack_cancel), "
            f"got {type(repo).__name__}"
        )
    global _agent_task_queue_repository
    _agent_task_queue_repository = repo
    logger.info(
        "AgentTaskQueueRepository installed: %s", type(repo).__name__
    )


def get_agent_task_queue_repository() -> AgentTaskQueueRepository:
    """Return the installed repository, falling back to a lazy adapter
    that wraps :func:`dao.mysql.agent_task_queue.get_agent_task_queue_dao`
    when no explicit repository is installed.

    The fall-back is PR-E4b-only and will be deleted in Phase 2 of the
    SDK extraction plan.

    Raises:
        AgentTaskQueueRepositoryNotInstalledError: when no repository
            is installed AND ``dao.mysql.agent_task_queue`` is not
            importable.
    """
    if _agent_task_queue_repository is not None:
        return _agent_task_queue_repository

    try:
        import importlib
        importlib.import_module("dao.mysql.agent_task_queue")
    except ImportError as exc:
        raise AgentTaskQueueRepositoryNotInstalledError(
            "AgentTaskQueueRepository has not been installed and "
            "dao.mysql.agent_task_queue is not importable. Call "
            "set_agent_task_queue_repository(repo) at boot before any "
            "engine code path runs."
        ) from exc

    return _LegacyAgentTaskQueueRepository.get_singleton()


def reset_agent_task_queue_repository_for_test() -> None:
    """Test-only helper to clear the installed repository between cases."""
    global _agent_task_queue_repository
    _agent_task_queue_repository = None
    _LegacyAgentTaskQueueRepository.reset_singleton_for_test()


# ── Legacy agent_task_queue_dao adapter (fallback) ──────────────────────


class _LegacyAgentTaskQueueRepository:
    """Adapter that exposes
    :func:`dao.mysql.agent_task_queue.get_agent_task_queue_dao` via the
    :class:`AgentTaskQueueRepository` Protocol.

    Reads the singleton lazily so the adapter survives early-boot.
    """

    _SINGLETON: Optional["_LegacyAgentTaskQueueRepository"] = None

    @classmethod
    def get_singleton(cls) -> "_LegacyAgentTaskQueueRepository":
        if cls._SINGLETON is None:
            cls._SINGLETON = cls()
        return cls._SINGLETON

    @classmethod
    def reset_singleton_for_test(cls) -> None:
        cls._SINGLETON = None

    @staticmethod
    def _dao() -> Any:
        try:
            from dao.mysql.agent_task_queue import get_agent_task_queue_dao
        except ImportError:
            return None
        return get_agent_task_queue_dao()

    async def get_by_id(
        self, queue_id: str
    ) -> Optional[AgentTaskQueueRow]:
        dao = self._dao()
        if dao is None:
            raise AgentTaskQueueRepositoryNotInstalledError(
                "_LegacyAgentTaskQueueRepository: "
                "dao.mysql.agent_task_queue not importable; "
                f"requested queue_id={queue_id!r}"
            )
        return await dao.get_by_id(queue_id)

    async def create(self, item: AgentTaskQueueRow) -> str:
        dao = self._dao()
        if dao is None:
            raise AgentTaskQueueRepositoryNotInstalledError(
                "_LegacyAgentTaskQueueRepository: "
                "dao.mysql.agent_task_queue not importable; "
                "cannot create queue row"
            )
        return await dao.create(item)

    async def update_status(
        self,
        queue_id: str,
        new_status: str,
        *,
        error_message: Optional[str] = None,
    ) -> int:
        dao = self._dao()
        if dao is None:
            raise AgentTaskQueueRepositoryNotInstalledError(
                "_LegacyAgentTaskQueueRepository: "
                "dao.mysql.agent_task_queue not importable; "
                f"requested queue_id={queue_id!r}"
            )
        # The real DAO signature: update_status(queue_id, new_status,
        # result=None, error=None).  Forward the error_message via the
        # ``error`` kwarg.
        return int(
            await dao.update_status(queue_id, new_status, error=error_message)
        )

    async def count_active_by_agent(self, agent_id: str) -> int:
        dao = self._dao()
        if dao is None:
            raise AgentTaskQueueRepositoryNotInstalledError(
                "_LegacyAgentTaskQueueRepository: "
                "dao.mysql.agent_task_queue not importable; "
                f"requested agent_id={agent_id!r}"
            )
        return int(await dao.count_active_by_agent(agent_id))

    async def list_pending_cancels(
        self, agent_id: str
    ) -> List[AgentTaskQueueRow]:
        dao = self._dao()
        if dao is None:
            raise AgentTaskQueueRepositoryNotInstalledError(
                "_LegacyAgentTaskQueueRepository: "
                "dao.mysql.agent_task_queue not importable; "
                f"requested agent_id={agent_id!r}"
            )
        return list(await dao.list_pending_cancels(agent_id))

    async def ack_cancel(self, task_id: str) -> int:
        dao = self._dao()
        if dao is None:
            raise AgentTaskQueueRepositoryNotInstalledError(
                "_LegacyAgentTaskQueueRepository: "
                "dao.mysql.agent_task_queue not importable; "
                f"requested task_id={task_id!r}"
            )
        return int(await dao.ack_cancel(task_id))


# ── In-memory AgentTaskQueueRepository for tests + SDK default ─────────


class InMemoryAgentTaskQueueRepository:
    """AgentTaskQueueRepository impl for tests and SDK self-bundled
    default.

    Backed by a single dict ``_rows: Dict[str, AgentTaskQueueRow]``
    keyed by queue row id. All reads return deep copies so engine
    mutation never leaks.

    Concurrency: not strictly atomic across asyncio tasks — production
    multi-pod deployments must NOT share an in-memory repository.
    """

    def __init__(self) -> None:
        self._rows: dict[str, AgentTaskQueueRow] = {}

    async def get_by_id(
        self, queue_id: str
    ) -> Optional[AgentTaskQueueRow]:
        existing = self._rows.get(queue_id)
        if existing is None:
            return None
        return copy.deepcopy(existing)

    async def create(self, item: AgentTaskQueueRow) -> str:
        rec_id = getattr(item, "id", "") or str(uuid.uuid4())
        try:
            item.id = rec_id
        except (AttributeError, TypeError):
            pass
        if not getattr(item, "created_at", None):
            try:
                item.created_at = datetime.now(timezone.utc).isoformat()
            except (AttributeError, TypeError):
                pass
        self._rows[rec_id] = copy.deepcopy(item)
        return rec_id

    async def update_status(
        self,
        queue_id: str,
        new_status: str,
        *,
        error_message: Optional[str] = None,
    ) -> int:
        """Atomic swap: deep-copy → mutate → replace.  Closes the
        partial-update window flagged in PR-E4b review."""
        row = self._rows.get(queue_id)
        if row is None:
            return 0
        new_row = copy.deepcopy(row)
        new_row.status = new_status
        now_iso = datetime.now(timezone.utc).isoformat()
        if new_status == "dispatched":
            new_row.dispatched_at = now_iso
        elif new_status == "running":
            new_row.started_at = now_iso
        elif new_status in ("completed", "failed", "cancelled"):
            new_row.completed_at = now_iso
        if error_message is not None:
            new_row.error = error_message
        self._rows[queue_id] = new_row
        return 1

    async def count_active_by_agent(self, agent_id: str) -> int:
        return sum(
            1
            for r in self._rows.values()
            if r.agent_id == agent_id and r.status in _ACTIVE_STATUSES
        )

    async def list_pending_cancels(
        self, agent_id: str
    ) -> List[AgentTaskQueueRow]:
        rows = [
            r
            for r in self._rows.values()
            if r.agent_id == agent_id
            and getattr(r, "cancel_requested_at", None) is not None
            and getattr(r, "cancel_ack_at", None) is None
        ]
        rows.sort(
            key=lambda r: getattr(r, "cancel_requested_at", "") or ""
        )
        return [copy.deepcopy(r) for r in rows]

    async def ack_cancel(self, task_id: str) -> int:
        """Atomic swap: deep-copy → mutate → replace.  Same anti-
        partial-update discipline as ``update_status``."""
        row = self._rows.get(task_id)
        if row is None:
            return 0
        if getattr(row, "cancel_requested_at", None) is None:
            return 0
        if getattr(row, "cancel_ack_at", None) is not None:
            return 0
        new_row = copy.deepcopy(row)
        now_iso = datetime.now(timezone.utc).isoformat()
        new_row.cancel_ack_at = now_iso
        new_row.status = "cancelled"
        new_row.completed_at = now_iso
        self._rows[task_id] = new_row
        return 1

    # ── Test helpers (not part of the Protocol) ──────────────────

    def seed(self, item: AgentTaskQueueRow) -> None:
        """Insert / overwrite a queue row.  Test-only convenience."""
        rec_id = getattr(item, "id", "") or str(uuid.uuid4())
        try:
            item.id = rec_id
        except (AttributeError, TypeError):
            pass
        self._rows[rec_id] = copy.deepcopy(item)

    def request_cancel(
        self,
        task_id: str,
        *,
        cancelled_by: str = "test",
        reason: str = "test-cancel",
    ) -> bool:
        """Simulate the cancel-request path used by the real DAO.

        Returns ``False`` when the row is missing or already cancelled.
        """
        row = self._rows.get(task_id)
        if row is None:
            return False
        if getattr(row, "cancel_requested_at", None) is not None:
            return False
        if row.status not in _ACTIVE_STATUSES:
            return False
        now_iso = datetime.now(timezone.utc).isoformat()
        row.cancel_requested_at = now_iso
        row.cancelled_by = cancelled_by
        row.cancel_reason = reason
        return True

    def list_ids(self) -> List[str]:
        return list(self._rows.keys())


__all__ = [
    "AgentTaskQueueRow",
    "WorkerClaimResult",
    "AgentTaskQueueRepository",
    "AgentTaskQueueRepositoryNotInstalledError",
    "InMemoryAgentTaskQueueRepository",
    "set_agent_task_queue_repository",
    "get_agent_task_queue_repository",
    "reset_agent_task_queue_repository_for_test",
]
# ``_LegacyAgentTaskQueueRepository`` intentionally NOT exported.
