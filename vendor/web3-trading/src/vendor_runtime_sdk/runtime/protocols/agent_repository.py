# -*- coding: utf-8 -*-
"""
AgentRepository — PR-E4b of the Agent Engine SDK extraction plan.

See ``docs/Agent-Engine-SDK-剥离方案.md`` §5 Phase 0 PR-E4b.

Goal
----
Replace the engine layer's direct dependency on ``dao.mysql.agent`` (the
ai-buddy-specific MySQL DAO singleton) with a Protocol-based seam. SDK
consumers install their own :class:`AgentRepository` at boot; ai-buddy
installs an adapter that wraps :func:`dao.mysql.agent.get_agent_dao` so
the existing engine code path is byte-identical.

Today the engine call sites that need agent state do::

    from dao.mysql.agent import get_agent_dao, AgentRow
    dao = get_agent_dao()
    await dao.get_by_id(agent_id)
    await dao.create(agent)
    await dao.update_status(agent_id, "working")
    await dao.get_max_concurrent(agent_id)
    await dao.list_agents(active_only=False)

That import path is unreachable when the engine is packaged as the SDK
:mod:`kucoin-agent-runtime-sdk` (``dao/`` is the business layer kept out
of the SDK). PR-E4b introduces the abstraction.

Scope (V1)
----------
Five methods chosen by audit across the engine candidate directories —
the smallest surface that drains the 20 callsites:

* :meth:`AgentRepository.get_by_id` — 5 call sites (rule_engine,
  task_dispatcher, dag_execution catalog, agent_task_dispatcher)
* :meth:`AgentRepository.create` — orchestration/task_dispatcher
* :meth:`AgentRepository.update_status` — orchestration/task_dispatcher
  + schedule/agent_task_dispatcher
* :meth:`AgentRepository.get_max_concurrent` — agent_task_dispatcher
* :meth:`AgentRepository.list_agents` — agent_task_dispatcher
  (active=False to enumerate every agent on every dispatcher tick)

The admin-only surfaces (``count_recent`` / ``count_agents`` /
``count_by_owner`` / ``list_by_owner`` / ``update`` / ``delete``) stay
on the concrete ``AgentDao`` — they're called from HTTP API routers,
not engine code paths.

AgentRow re-export
------------------
:class:`AgentRow` currently lives in ``src/dao/mysql/agent.py``. PR-E4b
re-exports it from this protocol module via a guarded import: when
``dao.mysql.agent`` is reachable we re-export the canonical dataclass;
otherwise we synthesise a minimal local replica with the same field
surface. In Phase 2 (post-extraction) the local replica becomes the
canonical definition and the ``dao.mysql`` version is deleted.

Fall-back path (PR-E4b only; deleted in Phase 2)
------------------------------------------------
When no provider is installed via :func:`set_agent_repository`,
:func:`get_agent_repository` lazily synthesises one that wraps
:func:`dao.mysql.agent.get_agent_dao`. This makes PR-E4b a
zero-behaviour-change refactor for ai-buddy's current boot path. SDK
consumers (Phase 2) MUST call ``set_agent_repository(...)`` at boot
before any engine path runs.

Same pattern as PR-E4 :class:`WorkflowRunRepository` /
:class:`CostRecordRepository` — engine carries its own contract;
business layer keeps its own concrete types; the SDK seam lives at the
import boundary.
"""

from __future__ import annotations

import copy
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, List, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ── AgentRow re-export ─────────────────────────────────────────────────
#
# Re-export the canonical dataclass when ``dao.mysql.agent`` is
# reachable so engine code only needs to know the Protocol module.

try:
    from dao.mysql.agent import AgentRow as _LegacyAgentRow
    AgentRow = _LegacyAgentRow  # type: ignore[misc,assignment]
except ImportError:  # pragma: no cover — exercised only in SDK-extracted scenario
    @dataclass
    class AgentRow:  # type: ignore[no-redef]
        """Minimal local replica of :class:`dao.mysql.agent.AgentRow`.

        Mirrors the field surface used by engine call sites. Activated
        only when ``dao.mysql.agent`` is not importable — i.e. the
        SDK-extracted scenario where the ``dao/`` package is no longer
        on the import path.
        """

        id: str = ""
        name: str = ""
        position: Optional[str] = None
        specialty: Optional[str] = None
        persona: Optional[str] = None
        owner: Optional[str] = None
        department: Optional[str] = None
        model: Optional[str] = None
        skills: List[str] = field(default_factory=list)
        rules: List[str] = field(default_factory=list)
        knowledge: List[str] = field(default_factory=list)
        tools: List[str] = field(default_factory=list)
        is_active: bool = True
        context_usage: int = 0
        token_quota: int = 10000
        budget_limit: float = 0
        budget_period: str = "monthly"
        status: str = "idle"
        max_concurrent_tasks: int = 5
        owner_user_id: Optional[str] = None
        owner_lark_uid: Optional[str] = None
        owner_name: Optional[str] = None
        owner_department: Optional[str] = None
        lark_integration_id: Optional[str] = None
        created_at: str = ""
        updated_at: str = ""


class AgentRepositoryNotInstalledError(RuntimeError):
    """Raised when :func:`get_agent_repository` is called before any
    repository is installed AND the legacy ``dao.mysql.agent`` fallback
    is not reachable.

    SDK consumers (Phase 2 onwards) MUST call
    ``set_agent_repository(repo)`` during boot before any engine module
    runs.
    """


@runtime_checkable
class AgentRepository(Protocol):
    """Pluggable repository for agent CRUD + status reconciliation.

    Methods are coarse-grained business operations matched 1:1 to the
    20 audited engine call sites in ``src/agent/dag_execution.py``,
    ``src/agent/dag_execution/_catalog.py``,
    ``src/agent/orchestration/rule_engine.py``,
    ``src/agent/orchestration/task_dispatcher.py``, and
    ``src/agent/schedule/agent_task_dispatcher.py``.

    Implementations MUST be safe to call concurrently from asyncio
    tasks — the scheduler fans out to multiple agents in parallel.
    """

    async def get_by_id(self, agent_id: str) -> Optional[AgentRow]:
        """Return the agent row, or ``None`` if not found.

        Implementations MUST return a fresh instance (or a deep copy);
        engine code mutates fields like ``status`` / ``skills`` during
        the dispatch loop and must not leak back into the store.
        """
        ...

    async def create(self, agent: AgentRow) -> str:
        """Insert a new agent row. Returns the (possibly server-assigned)
        ``id`` of the inserted row.

        When ``agent.id`` is empty, implementations MAY generate one
        (the real DAO uses ``uuid.uuid4()``); the returned id is the
        canonical row identifier.
        """
        ...

    async def update_status(
        self, agent_id: str, new_status: str
    ) -> bool:
        """Update the agent's runtime status (``idle`` / ``working`` /
        ``offline``).

        Returns ``True`` on a single-row update; ``False`` when the
        status is rejected or the agent row is missing. The real DAO
        validates ``new_status`` against the FSM allow-list — invalid
        values return ``False`` rather than raising.
        """
        ...

    async def get_max_concurrent(self, agent_id: str) -> int:
        """Return ``max_concurrent_tasks`` for the agent.

        Returns the default (``5``) when the agent row is missing or
        the DAO is in DB-access-denied mode — preserves the legacy
        permissive contract used by
        :class:`AgentTaskQueueDispatcher._dispatch_single`.
        """
        ...

    async def list_agents(
        self, *, active_only: bool = False
    ) -> List[AgentRow]:
        """Return every agent row, optionally filtered to ``is_active=1``.

        Used by the dispatcher tick loop to enumerate agents on every
        scan. Implementations MUST return a list (never ``None``); on
        DAO failure the legacy implementation returns an empty list.
        """
        ...


# ── Module-level singleton ──────────────────────────────────────────────


_agent_repository: Optional[AgentRepository] = None


def set_agent_repository(repo: AgentRepository) -> None:
    """Install the AgentRepository used by engine modules.

    Idempotent — subsequent calls overwrite. Logs at INFO so boot order
    is auditable. **Never** logs the repo contents.

    Raises:
        TypeError: when ``repo`` does not satisfy the
            :class:`AgentRepository` Protocol at the structural level.
    """
    if not isinstance(repo, AgentRepository):
        raise TypeError(
            f"set_agent_repository: repo must satisfy "
            f"AgentRepository Protocol (get_by_id / create / "
            f"update_status / get_max_concurrent / list_agents), "
            f"got {type(repo).__name__}"
        )
    global _agent_repository
    _agent_repository = repo
    logger.info("AgentRepository installed: %s", type(repo).__name__)


def get_agent_repository() -> AgentRepository:
    """Return the installed repository, falling back to a lazy adapter
    that wraps :func:`dao.mysql.agent.get_agent_dao` when no explicit
    repository is installed.

    The fall-back is PR-E4b-only and will be deleted in Phase 2 of the
    SDK extraction plan. SDK consumers MUST install a repository at
    boot.

    Raises:
        AgentRepositoryNotInstalledError: when no repository is
            installed AND ``dao.mysql.agent`` is not importable.
    """
    if _agent_repository is not None:
        return _agent_repository

    # PR-E4b fall-back. Probe ``dao.mysql.agent`` reachability.
    try:
        import importlib
        importlib.import_module("dao.mysql.agent")
    except ImportError as exc:
        raise AgentRepositoryNotInstalledError(
            "AgentRepository has not been installed and "
            "dao.mysql.agent is not importable. Call "
            "set_agent_repository(repo) at boot before any "
            "engine code path runs."
        ) from exc

    return _LegacyAgentRepository.get_singleton()


def reset_agent_repository_for_test() -> None:
    """Test-only helper to clear the installed repository between cases.

    NOT for production use. Mirrors
    :func:`runtime.protocols.workflow_run_repository.reset_workflow_run_repository_for_test`.
    """
    global _agent_repository
    _agent_repository = None
    _LegacyAgentRepository.reset_singleton_for_test()


# ── Legacy agent_dao adapter (fallback) ─────────────────────────────────


class _LegacyAgentRepository:
    """Adapter that exposes :func:`dao.mysql.agent.get_agent_dao` (the
    pre-built singleton in ai-buddy) via the :class:`AgentRepository`
    Protocol.

    Used only via the fall-back path in :func:`get_agent_repository`
    when no SDK-side repository is installed. ai-buddy can choose to
    install this adapter explicitly at boot (cleaner audit trail) or
    rely on the fall-back (zero boot wiring).

    Reads ``get_agent_dao()`` lazily inside each method so the adapter
    survives early-boot scenarios where the MySQL pool isn't ready yet
    — same fail-soft pattern as
    :class:`runtime.protocols.context_store._LegacyContextStoreProvider`.
    """

    _SINGLETON: Optional["_LegacyAgentRepository"] = None

    @classmethod
    def get_singleton(cls) -> "_LegacyAgentRepository":
        if cls._SINGLETON is None:
            cls._SINGLETON = cls()
        return cls._SINGLETON

    @classmethod
    def reset_singleton_for_test(cls) -> None:
        cls._SINGLETON = None

    @staticmethod
    def _dao() -> Any:
        try:
            from dao.mysql.agent import get_agent_dao
        except ImportError:
            return None
        return get_agent_dao()

    async def get_by_id(self, agent_id: str) -> Optional[AgentRow]:
        dao = self._dao()
        if dao is None:
            raise AgentRepositoryNotInstalledError(
                "_LegacyAgentRepository: dao.mysql.agent not importable; "
                f"requested agent_id={agent_id!r}"
            )
        return await dao.get_by_id(agent_id)

    async def create(self, agent: AgentRow) -> str:
        dao = self._dao()
        if dao is None:
            raise AgentRepositoryNotInstalledError(
                "_LegacyAgentRepository: dao.mysql.agent not importable; "
                "cannot insert agent row"
            )
        return await dao.create(agent)

    async def update_status(
        self, agent_id: str, new_status: str
    ) -> bool:
        dao = self._dao()
        if dao is None:
            raise AgentRepositoryNotInstalledError(
                "_LegacyAgentRepository: dao.mysql.agent not importable; "
                f"requested agent_id={agent_id!r}"
            )
        return bool(await dao.update_status(agent_id, new_status))

    async def get_max_concurrent(self, agent_id: str) -> int:
        dao = self._dao()
        if dao is None:
            raise AgentRepositoryNotInstalledError(
                "_LegacyAgentRepository: dao.mysql.agent not importable; "
                f"requested agent_id={agent_id!r}"
            )
        return int(await dao.get_max_concurrent(agent_id))

    async def list_agents(
        self, *, active_only: bool = False
    ) -> List[AgentRow]:
        dao = self._dao()
        if dao is None:
            raise AgentRepositoryNotInstalledError(
                "_LegacyAgentRepository: dao.mysql.agent not importable; "
                "cannot list agents"
            )
        # Real DAO uses positional ``active_only`` — preserve that
        # to stay compatible with the audited call sites.
        return list(await dao.list_agents(active_only=active_only))


# ── In-memory AgentRepository for tests + SDK default ──────────────────


# Valid statuses mirroring the production AgentDao FSM allowlist.
_VALID_STATUSES: frozenset[str] = frozenset({"idle", "working", "offline"})


class InMemoryAgentRepository:
    """AgentRepository impl for tests and SDK self-bundled default.

    Backed by a single dict ``_agents: Dict[str, AgentRow]`` keyed by
    agent id. All reads return a *copy* (via :func:`copy.deepcopy`) so
    engine code can mutate the returned dataclass without leaking back
    into the store.

    Concurrency: dict-mutation is not strictly atomic across asyncio
    tasks, but the linear-scan footprint per call is small enough that
    realistic test workloads never race. Production multi-pod
    deployments must NOT share an in-memory repository — install the
    legacy MySQL adapter or a custom SDK provider instead.
    """

    def __init__(self) -> None:
        self._agents: dict[str, AgentRow] = {}

    async def get_by_id(self, agent_id: str) -> Optional[AgentRow]:
        existing = self._agents.get(agent_id)
        if existing is None:
            return None
        return copy.deepcopy(existing)

    async def create(self, agent: AgentRow) -> str:
        rec_id = getattr(agent, "id", "") or str(uuid.uuid4())
        try:
            agent.id = rec_id
        except (AttributeError, TypeError):
            # frozen dataclass — fall through; store the row as-is.
            pass
        self._agents[rec_id] = copy.deepcopy(agent)
        return rec_id

    async def update_status(
        self, agent_id: str, new_status: str
    ) -> bool:
        """Atomically swap the stored row.  Deep-copy before mutating
        so a concurrent ``get_by_id`` returns either the OLD complete
        row or the NEW complete row — never a partial mid-update
        state.  Review feedback HIGH: pre-fix mutated the live store
        row in place, opening a partial-update window."""
        if new_status not in _VALID_STATUSES:
            return False
        row = self._agents.get(agent_id)
        if row is None:
            return False
        new_row = copy.deepcopy(row)
        new_row.status = new_status
        self._agents[agent_id] = new_row
        return True

    async def get_max_concurrent(self, agent_id: str) -> int:
        row = self._agents.get(agent_id)
        if row is None:
            return 5
        return int(getattr(row, "max_concurrent_tasks", 5) or 5)

    async def list_agents(
        self, *, active_only: bool = False
    ) -> List[AgentRow]:
        rows = list(self._agents.values())
        if active_only:
            rows = [r for r in rows if bool(getattr(r, "is_active", True))]
        return [copy.deepcopy(r) for r in rows]

    # ── Test helpers (not part of the Protocol) ──────────────────

    def seed(self, agent: AgentRow) -> None:
        """Insert / overwrite an agent row.  Test-only convenience."""
        rec_id = getattr(agent, "id", "") or str(uuid.uuid4())
        try:
            agent.id = rec_id
        except (AttributeError, TypeError):
            pass
        self._agents[rec_id] = copy.deepcopy(agent)

    def list_ids(self) -> List[str]:
        return list(self._agents.keys())

    def clear(self) -> None:
        self._agents.clear()


__all__ = [
    "AgentRow",
    "AgentRepository",
    "AgentRepositoryNotInstalledError",
    "InMemoryAgentRepository",
    "set_agent_repository",
    "get_agent_repository",
    "reset_agent_repository_for_test",
]
# ``_LegacyAgentRepository`` is intentionally NOT exported — same
# convention as ``_LegacyWorkflowRunRepository`` / ``_LegacyCostRecordRepository``.
