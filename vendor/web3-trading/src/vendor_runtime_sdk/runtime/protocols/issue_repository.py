# -*- coding: utf-8 -*-
"""
IssueRepository — PR-E4b of the Agent Engine SDK extraction plan.

See ``docs/Agent-Engine-SDK-剥离方案.md`` §5 Phase 0 PR-E4b.

Goal
----
Replace the engine layer's direct dependency on ``dao.mysql.issue`` (the
ai-buddy-specific MySQL DAO singleton) with a Protocol-based seam. SDK
consumers install their own :class:`IssueRepository` at boot; ai-buddy
installs an adapter that wraps :func:`dao.mysql.issue.get_issue_dao` so
the existing engine code path is byte-identical.

Today the engine call sites that need issue state do::

    from dao.mysql.issue import get_issue_dao, IssueRow
    dao = get_issue_dao()
    await dao.get_by_id(issue_id)
    await dao.create(issue)
    await dao.update(issue_id, {"status": "in_progress"})
    await dao.change_status(issue_id, "done")
    await dao.list_workflow_node_task_dicts_for_run(workspace_id, run_id)
    await dao.workflow_node_subtasks_completion_for_gate(workspace_id, run_id, node_id)

That import path is unreachable when the engine is packaged as the SDK
:mod:`kucoin-agent-runtime-sdk` (``dao/`` is the business layer kept
out of the SDK).

Scope (V1)
----------
The audit identifies 29 engine call sites across:

* ``src/agent/mixins/response_mixin.py`` — three lazy ``get_by_id``
  call sites that load issue subtask context for prompts.
* ``src/agent/schedule/agent_task_dispatcher.py`` — ``get_by_id`` +
  ``change_status`` calls during agent dispatch.
* ``src/runtime/workflow_executor/_handlers_task.py`` — ``create`` for
  workflow-node task synthesis.
* ``src/runtime/workflow_executor/_lifecycle.py`` —
  ``workflow_node_subtasks_completion_for_gate`` poll for run-subtask
  completion.

The Protocol surface stays narrow (six methods). Admin-only surfaces
(``list_issues`` / ``board`` / ``tree`` / ``pool_view`` / etc.) stay on
the concrete ``IssueDao``.

IssueRow re-export
------------------
:class:`IssueRow` currently lives in ``src/dao/mysql/issue.py``. PR-E4b
re-exports it from this protocol module via a guarded import: when
``dao.mysql.issue`` is reachable we re-export the canonical dataclass;
otherwise we synthesise a minimal local replica with the same field
surface. In Phase 2 (post-extraction) the local replica becomes
canonical.

Fall-back path (PR-E4b only; deleted in Phase 2)
------------------------------------------------
When no provider is installed via :func:`set_issue_repository`,
:func:`get_issue_repository` lazily synthesises one that wraps
:func:`dao.mysql.issue.get_issue_dao`.

Same pattern as PR-E4 :class:`WorkflowRunRepository` /
:class:`CostRecordRepository`.
"""

from __future__ import annotations

import copy
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ── IssueRow re-export ─────────────────────────────────────────────────


try:
    from dao.mysql.issue import IssueRow as _LegacyIssueRow
    IssueRow = _LegacyIssueRow  # type: ignore[misc,assignment]
except ImportError:  # pragma: no cover — SDK-extracted scenario only
    @dataclass
    class IssueRow:  # type: ignore[no-redef]
        """Minimal local replica of :class:`dao.mysql.issue.IssueRow`.

        Mirrors the field surface used by engine call sites. Activated
        only when ``dao.mysql.issue`` is not importable.
        """

        id: str = ""
        workspace_id: str = ""
        issue_type: str = "story"
        issue_number: int = 0
        title: str = ""
        description: Optional[str] = None
        status: str = "backlog"
        priority: str = "none"
        assignee_type: Optional[str] = None
        assignee_id: Optional[str] = None
        creator_type: str = "member"
        creator_id: str = ""
        owner_type: Optional[str] = None
        owner_id: Optional[str] = None
        parent_issue_id: Optional[str] = None
        team_id: Optional[str] = None
        version_id: Optional[str] = None
        source_type: Optional[str] = None
        labels: List[str] = field(default_factory=list)
        custom_fields: Dict[str, Any] = field(default_factory=dict)
        type_config: Dict[str, Any] = field(default_factory=dict)
        position: float = 0.0
        due_date: Optional[str] = None
        estimated_hours: Optional[float] = None
        acceptance_criteria: List[Any] = field(default_factory=list)
        context_refs: List[Any] = field(default_factory=list)
        workflow_run_id: Optional[str] = None
        workflow_graph_node_id: Optional[str] = None
        llm_model_key: Optional[str] = None
        created_at: str = ""
        updated_at: str = ""


class IssueRepositoryNotInstalledError(RuntimeError):
    """Raised when :func:`get_issue_repository` is called before any
    repository is installed AND the legacy ``dao.mysql.issue`` fallback
    is not reachable.
    """


# Display-status map used by InMemoryIssueRepository's gate helpers —
# mirrors ``dao.mysql.issue.map_issue_task_status_to_workflow_node_display``.
_ISSUE_TO_DISPLAY: Dict[str, str] = {
    "pending": "todo",
    "in_progress": "doing",
    "completed": "done",
    "blocked": "blocked",
    "cancelled": "cancelled",
}

_SUBTASK_TERMINAL_DISPLAY: frozenset[str] = frozenset({"done", "cancelled"})


@runtime_checkable
class IssueRepository(Protocol):
    """Pluggable repository for issue CRUD + workflow node-task helpers.

    Methods are coarse-grained business operations matched 1:1 to the
    29 audited engine call sites. The mixin's ``update_run``-shaped
    ``update`` accepts a partial-payload dict because the audit shows
    multiple distinct partial-update shapes; modelling each as a typed
    method would explode the surface for no SDK-consumer benefit.

    Implementations MUST be safe to call concurrently from asyncio
    tasks.
    """

    async def get_by_id(self, issue_id: str) -> Optional[IssueRow]:
        """Return the issue row, or ``None`` if not found.

        Implementations MUST return a fresh instance (or deep copy);
        engine code mutates the returned row during prompt assembly.
        """
        ...

    async def create(self, issue: IssueRow) -> str:
        """Insert a new issue row. Returns the inserted ``id``."""
        ...

    async def update(self, issue_id: str, data: Dict[str, Any]) -> int:
        """Apply a partial update to the issue row.

        ``data`` keys are column names; values are JSON-serialisable
        scalars or dict/list (which the real DAO serialises via
        ``json.dumps``). Returns the number of rows affected.
        """
        ...

    async def change_status(
        self, issue_id: str, new_status: str
    ) -> int:
        """Convenience wrapper over :meth:`update` that only writes
        ``status``. Returns rows affected.
        """
        ...

    async def list_workflow_node_task_dicts_for_run(
        self,
        *,
        workspace_id: str,
        run_id: str,
    ) -> List[Dict[str, Any]]:
        """Return all task-type issues for one workflow run (any DAG
        node) as Meegle-style dicts.

        Workspace-scoped — implementations MUST filter by
        ``workspace_id`` in addition to ``run_id`` because tenants
        share the issue table.
        """
        ...

    async def get_workflow_node_task_issue(
        self,
        *,
        workspace_id: str,
        run_id: str,
        graph_node_id: str,
    ) -> Optional[IssueRow]:
        """Return the canonical task-type issue anchored to
        ``(workspace_id, run_id, graph_node_id)`` or ``None`` when none
        exists.

        Workflow-engine vocabulary — the workflow executor uses this
        to decide whether to spawn a new task row vs reuse an existing
        one on resume.
        """
        ...


# ── Module-level singleton ──────────────────────────────────────────────


_issue_repository: Optional[IssueRepository] = None


def set_issue_repository(repo: IssueRepository) -> None:
    """Install the IssueRepository used by engine modules.

    Idempotent — subsequent calls overwrite. Logs at INFO so boot
    order is auditable.  **Never** logs the repo contents.

    Raises:
        TypeError: when ``repo`` does not satisfy the
            :class:`IssueRepository` Protocol at the structural level.
    """
    if not isinstance(repo, IssueRepository):
        raise TypeError(
            f"set_issue_repository: repo must satisfy "
            f"IssueRepository Protocol (get_by_id / create / update / "
            f"change_status / list_workflow_node_task_dicts_for_run / "
            f"get_workflow_node_task_issue), "
            f"got {type(repo).__name__}"
        )
    global _issue_repository
    _issue_repository = repo
    logger.info("IssueRepository installed: %s", type(repo).__name__)


def get_issue_repository() -> IssueRepository:
    """Return the installed repository, falling back to a lazy adapter
    that wraps :func:`dao.mysql.issue.get_issue_dao` when no explicit
    repository is installed.

    Raises:
        IssueRepositoryNotInstalledError: when no repository is
            installed AND ``dao.mysql.issue`` is not importable.
    """
    if _issue_repository is not None:
        return _issue_repository

    try:
        import importlib
        importlib.import_module("dao.mysql.issue")
    except ImportError as exc:
        raise IssueRepositoryNotInstalledError(
            "IssueRepository has not been installed and "
            "dao.mysql.issue is not importable. Call "
            "set_issue_repository(repo) at boot before any "
            "engine code path runs."
        ) from exc

    return _LegacyIssueRepository.get_singleton()


def reset_issue_repository_for_test() -> None:
    """Test-only helper to clear the installed repository between cases."""
    global _issue_repository
    _issue_repository = None
    _LegacyIssueRepository.reset_singleton_for_test()


# ── Legacy issue_dao adapter (fallback) ─────────────────────────────────


class _LegacyIssueRepository:
    """Adapter that exposes :func:`dao.mysql.issue.get_issue_dao` (the
    pre-built singleton in ai-buddy) via the :class:`IssueRepository`
    Protocol.

    Lazy DAO lookup inside every method so the adapter survives early-
    boot.
    """

    _SINGLETON: Optional["_LegacyIssueRepository"] = None

    @classmethod
    def get_singleton(cls) -> "_LegacyIssueRepository":
        if cls._SINGLETON is None:
            cls._SINGLETON = cls()
        return cls._SINGLETON

    @classmethod
    def reset_singleton_for_test(cls) -> None:
        cls._SINGLETON = None

    @staticmethod
    def _dao() -> Any:
        try:
            from dao.mysql.issue import get_issue_dao
        except ImportError:
            return None
        return get_issue_dao()

    async def get_by_id(self, issue_id: str) -> Optional[IssueRow]:
        dao = self._dao()
        if dao is None:
            raise IssueRepositoryNotInstalledError(
                "_LegacyIssueRepository: dao.mysql.issue not importable; "
                f"requested issue_id={issue_id!r}"
            )
        return await dao.get_by_id(issue_id)

    async def create(self, issue: IssueRow) -> str:
        dao = self._dao()
        if dao is None:
            raise IssueRepositoryNotInstalledError(
                "_LegacyIssueRepository: dao.mysql.issue not importable; "
                "cannot create issue row"
            )
        return await dao.create(issue)

    async def update(self, issue_id: str, data: Dict[str, Any]) -> int:
        dao = self._dao()
        if dao is None:
            raise IssueRepositoryNotInstalledError(
                "_LegacyIssueRepository: dao.mysql.issue not importable; "
                f"requested issue_id={issue_id!r}"
            )
        return int(await dao.update(issue_id, data))

    async def change_status(
        self, issue_id: str, new_status: str
    ) -> int:
        dao = self._dao()
        if dao is None:
            raise IssueRepositoryNotInstalledError(
                "_LegacyIssueRepository: dao.mysql.issue not importable; "
                f"requested issue_id={issue_id!r}"
            )
        return int(await dao.change_status(issue_id, new_status))

    async def list_workflow_node_task_dicts_for_run(
        self,
        *,
        workspace_id: str,
        run_id: str,
    ) -> List[Dict[str, Any]]:
        dao = self._dao()
        if dao is None:
            raise IssueRepositoryNotInstalledError(
                "_LegacyIssueRepository: dao.mysql.issue not importable; "
                f"requested run_id={run_id!r}"
            )
        return list(
            await dao.list_workflow_node_task_dicts_for_run(
                workspace_id, run_id
            )
        )

    async def get_workflow_node_task_issue(
        self,
        *,
        workspace_id: str,
        run_id: str,
        graph_node_id: str,
    ) -> Optional[IssueRow]:
        dao = self._dao()
        if dao is None:
            raise IssueRepositoryNotInstalledError(
                "_LegacyIssueRepository: dao.mysql.issue not importable; "
                f"requested run_id={run_id!r} node={graph_node_id!r}"
            )
        # Real DAO exposes `get_workflow_node_task_issue(task_id, workspace_id)`
        # — the engine call sites for that method look up by task_id.
        # However the Protocol's matched call shape (workspace + run +
        # graph_node) is needed by the workflow executor.  Iterate the
        # per-run list and select the matching node.
        rows = await dao.list_workflow_node_task_dicts_for_run(
            workspace_id, run_id
        )
        for d in rows or []:
            if str(d.get("node_id") or "") == str(graph_node_id):
                issue_id = d.get("id")
                if not issue_id:
                    return None
                return await dao.get_by_id(issue_id)
        return None


# ── In-memory IssueRepository for tests + SDK default ──────────────────


class InMemoryIssueRepository:
    """IssueRepository impl for tests and SDK self-bundled default.

    Backed by a single dict ``_issues: Dict[str, IssueRow]`` keyed by
    issue id. All reads return deep copies so engine mutation does not
    leak.

    Concurrency: not strictly atomic across asyncio tasks — production
    multi-pod deployments must NOT share an in-memory repository.
    """

    def __init__(self) -> None:
        self._issues: dict[str, IssueRow] = {}

    async def get_by_id(self, issue_id: str) -> Optional[IssueRow]:
        existing = self._issues.get(issue_id)
        if existing is None:
            return None
        return copy.deepcopy(existing)

    async def create(self, issue: IssueRow) -> str:
        rec_id = getattr(issue, "id", "") or str(uuid.uuid4())
        try:
            issue.id = rec_id
        except (AttributeError, TypeError):
            pass
        self._issues[rec_id] = copy.deepcopy(issue)
        return rec_id

    async def update(self, issue_id: str, data: Dict[str, Any]) -> int:
        """Atomic swap: deep-copy → mutate → replace.  Closes the
        partial-update window flagged in PR-E4b review (pre-fix the
        live store row was mutated field-by-field which leaked into
        concurrent ``get_by_id`` callers).
        """
        row = self._issues.get(issue_id)
        if row is None or not data:
            return 0
        new_row = copy.deepcopy(row)
        for k, v in data.items():
            try:
                setattr(new_row, k, v)
            except (AttributeError, TypeError):
                # Unknown column — silently skip in the in-memory impl
                # (real DAO would raise via SQL).
                continue
        self._issues[issue_id] = new_row
        return 1

    async def change_status(
        self, issue_id: str, new_status: str
    ) -> int:
        return await self.update(issue_id, {"status": new_status})

    async def list_workflow_node_task_dicts_for_run(
        self,
        *,
        workspace_id: str,
        run_id: str,
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for r in self._issues.values():
            if getattr(r, "workspace_id", "") != workspace_id:
                continue
            if getattr(r, "issue_type", "") != "task":
                continue
            if str(getattr(r, "workflow_run_id", "") or "") != str(run_id):
                continue
            disp = _ISSUE_TO_DISPLAY.get(
                str(getattr(r, "status", "") or "").strip(), "todo"
            )
            owner_t = getattr(r, "assignee_type", None) or getattr(
                r, "owner_type", None
            )
            owner_i = getattr(r, "assignee_id", None) or getattr(
                r, "owner_id", None
            )
            out.append(
                {
                    "id": r.id,
                    "workspace_id": r.workspace_id,
                    "run_id": str(
                        getattr(r, "workflow_run_id", "") or ""
                    ),
                    "node_id": str(
                        getattr(r, "workflow_graph_node_id", "") or ""
                    ),
                    "title": r.title or "",
                    "owner_type": owner_t,
                    "owner_id": owner_i,
                    "status": disp,
                    "position": float(getattr(r, "position", 0) or 0),
                    "created_at": getattr(r, "created_at", ""),
                    "updated_at": getattr(r, "updated_at", ""),
                }
            )
        out.sort(key=lambda d: (d.get("node_id", ""), d.get("position", 0.0)))
        return out

    async def get_workflow_node_task_issue(
        self,
        *,
        workspace_id: str,
        run_id: str,
        graph_node_id: str,
    ) -> Optional[IssueRow]:
        for r in self._issues.values():
            if getattr(r, "workspace_id", "") != workspace_id:
                continue
            if getattr(r, "issue_type", "") != "task":
                continue
            if str(getattr(r, "workflow_run_id", "") or "") != str(run_id):
                continue
            if (
                str(getattr(r, "workflow_graph_node_id", "") or "")
                != str(graph_node_id)
            ):
                continue
            return copy.deepcopy(r)
        return None

    # ── Test helpers (not part of the Protocol) ──────────────────

    def seed(self, issue: IssueRow) -> None:
        rec_id = getattr(issue, "id", "") or str(uuid.uuid4())
        try:
            issue.id = rec_id
        except (AttributeError, TypeError):
            pass
        self._issues[rec_id] = copy.deepcopy(issue)

    def list_ids(self) -> List[str]:
        return list(self._issues.keys())

    def clear(self) -> None:
        self._issues.clear()


__all__ = [
    "IssueRow",
    "IssueRepository",
    "IssueRepositoryNotInstalledError",
    "InMemoryIssueRepository",
    "set_issue_repository",
    "get_issue_repository",
    "reset_issue_repository_for_test",
]
# ``_LegacyIssueRepository`` intentionally NOT exported.
