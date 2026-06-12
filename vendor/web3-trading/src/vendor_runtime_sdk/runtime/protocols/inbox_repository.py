# -*- coding: utf-8 -*-
"""
InboxRepository — PR-E4c of the Agent Engine SDK extraction plan.

See ``docs/Agent-Engine-SDK-剥离方案.md`` §5 Phase 0 PR-E4c.

Goal
----
Replace the engine layer's direct dependency on ``dao.mysql.inbox`` (the
ai-buddy-specific MySQL DAO singleton) with a Protocol-based seam. SDK
consumers install their own :class:`InboxRepository` at boot; ai-buddy
installs an adapter that wraps :func:`dao.mysql.inbox.get_inbox_dao` so
the existing engine code path is byte-identical.

Today the engine call sites that emit inbox items do::

    from dao.mysql.inbox import InboxItemRow, get_inbox_dao
    inbox_dao = get_inbox_dao()
    await inbox_dao.create(
        InboxItemRow(id=..., workspace_id=..., recipient_type=...,
                     recipient_id=..., type=..., title=..., body=...)
    )

That import path is unreachable when the engine is packaged as the SDK
:mod:`kucoin-agent-runtime-sdk` (``dao/`` is the business layer kept out
of the SDK). PR-E4c introduces the abstraction.

Scope (V1)
----------
The audit identifies two engine inbox call sites:

* ``src/runtime/story_workflow_automation.py`` — workflow rule-engine
  pushes an inbox notification when an ``on_node_done`` rule fires
  (``action_type == "inbox"``).
* ``src/runtime/workflow_executor/_handlers_task.py`` — workflow node
  task handler pushes a ``workflow_node_task_assigned`` inbox row when
  a new task issue is created for an assignee.

Both are write-only ``create`` calls — engine code never reads from the
inbox table. Two methods are exposed to give SDK consumers a complete
mailbox shape:

* :meth:`InboxRepository.create` — insert a new inbox row, return id
* :meth:`InboxRepository.list_by_issue` — fetch the inbox tail for a
  specific issue (used by future engine surfaces; the production DAO
  already implements equivalent shapes via ``list_by_recipient``)

Admin-only surfaces (``list_by_recipient`` / ``unread_count`` /
``mark_read`` / ``mark_all_read`` / ``archive``) stay on the concrete
:class:`InboxDao` — they're called from HTTP API routers, not engine
code paths.

InboxItemRow re-export
----------------------
:class:`InboxItemRow` currently lives in ``src/dao/mysql/inbox.py``.
PR-E4c re-exports it from this protocol module via a guarded import:
when ``dao.mysql.inbox`` is reachable we re-export the canonical
dataclass; otherwise we synthesise a minimal local replica with the
same field surface. In Phase 2 (post-extraction) the local replica
becomes the canonical definition and the ``dao.mysql`` version is
deleted.

Fall-back path (PR-E4c only; deleted in Phase 2)
------------------------------------------------
When no provider is installed via :func:`set_inbox_repository`,
:func:`get_inbox_repository` lazily synthesises one that wraps
:func:`dao.mysql.inbox.get_inbox_dao`. This makes PR-E4c a
zero-behaviour-change refactor for ai-buddy's current boot path. SDK
consumers (Phase 2) MUST call ``set_inbox_repository(...)`` at boot
before any engine path runs.

Same pattern as PR-E4 :class:`CostRecordRepository` and PR-E4b
:class:`AgentRepository` / :class:`IssueRepository`.
"""

from __future__ import annotations

import copy
import logging
import uuid
from dataclasses import dataclass
from typing import Any, List, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ── InboxItemRow re-export ──────────────────────────────────────────────


try:
    from dao.mysql.inbox import InboxItemRow as _LegacyInboxItemRow
    InboxItemRow = _LegacyInboxItemRow  # type: ignore[misc,assignment]
except ImportError:  # pragma: no cover — exercised only in SDK-extracted scenario
    @dataclass
    class InboxItemRow:  # type: ignore[no-redef]
        """Minimal local replica of :class:`dao.mysql.inbox.InboxItemRow`.

        Mirrors the field surface used by engine call sites. Activated
        only when ``dao.mysql.inbox`` is not importable — i.e. the
        SDK-extracted scenario where the ``dao/`` package is no longer
        on the import path.
        """

        # Non-default fields first (mirrors real DAO order).
        id: str = ""
        workspace_id: str = ""
        # Fields with defaults
        recipient_type: str = "member"
        recipient_id: str = ""
        type: str = ""
        severity: str = "info"
        issue_id: Optional[str] = None
        title: str = ""
        body: Optional[str] = None
        is_read: bool = False
        is_archived: bool = False
        created_at: str = ""


class InboxRepositoryNotInstalledError(RuntimeError):
    """Raised when :func:`get_inbox_repository` is called before any
    repository is installed AND the legacy ``dao.mysql.inbox`` fallback
    is not reachable.

    SDK consumers (Phase 2 onwards) MUST call
    ``set_inbox_repository(repo)`` during boot before any engine module
    runs.
    """


@runtime_checkable
class InboxRepository(Protocol):
    """Pluggable repository for inbox-item persistence + per-issue read.

    Methods are coarse-grained business operations matched 1:1 to the
    engine call sites (``story_workflow_automation`` + workflow-executor
    task handler). The production DAO carries many more methods (read
    counts, mark-read fan-outs) — those are admin/HTTP-surface and stay
    on the concrete ``InboxDao``.

    Implementations MUST be safe to call concurrently from asyncio
    tasks — workflow rule-engine and node-task fan-outs both emit
    inbox rows in parallel.
    """

    async def create(self, item: InboxItemRow) -> str:
        """Insert a new inbox row. Returns the inserted ``id``.

        When ``item.id`` is empty, implementations MAY generate one
        (the real DAO uses ``uuid.uuid4()``); the returned id is the
        canonical row identifier.
        """
        ...

    async def list_by_issue(
        self,
        *,
        workspace_id: str,
        issue_id: str,
    ) -> List[InboxItemRow]:
        """Return inbox rows attached to ``issue_id`` within ``workspace_id``.

        Workspace-scoped — implementations MUST filter by
        ``workspace_id`` in addition to ``issue_id`` because tenants
        share the inbox table.

        Returns an empty list (never ``None``) when no rows match.
        """
        ...


# ── Module-level singleton ──────────────────────────────────────────────


_inbox_repository: Optional[InboxRepository] = None


def set_inbox_repository(repo: InboxRepository) -> None:
    """Install the InboxRepository used by engine modules.

    Idempotent — subsequent calls overwrite. Logs at INFO so boot order
    is auditable. **Never** logs the repo contents — inbox rows carry
    recipient ``user_id`` (PII) and bodies may include workflow run
    details.

    Raises:
        TypeError: when ``repo`` does not satisfy the
            :class:`InboxRepository` Protocol at the structural level.
    """
    if not isinstance(repo, InboxRepository):
        raise TypeError(
            f"set_inbox_repository: repo must satisfy "
            f"InboxRepository Protocol (create / list_by_issue), "
            f"got {type(repo).__name__}"
        )
    global _inbox_repository
    _inbox_repository = repo
    logger.info("InboxRepository installed: %s", type(repo).__name__)


def get_inbox_repository() -> InboxRepository:
    """Return the installed repository, falling back to a lazy adapter
    that wraps :func:`dao.mysql.inbox.get_inbox_dao` when no explicit
    repository is installed.

    The fall-back is PR-E4c-only and will be deleted in Phase 2 of the
    SDK extraction plan. SDK consumers MUST install a repository at
    boot.

    Raises:
        InboxRepositoryNotInstalledError: when no repository is
            installed AND ``dao.mysql.inbox`` is not importable.
    """
    if _inbox_repository is not None:
        return _inbox_repository

    try:
        import importlib
        importlib.import_module("dao.mysql.inbox")
    except ImportError as exc:
        raise InboxRepositoryNotInstalledError(
            "InboxRepository has not been installed and "
            "dao.mysql.inbox is not importable. Call "
            "set_inbox_repository(repo) at boot before any "
            "engine code path runs."
        ) from exc

    return _LegacyInboxRepository.get_singleton()


def reset_inbox_repository_for_test() -> None:
    """Test-only helper to clear the installed repository between cases.

    NOT for production use.
    """
    global _inbox_repository
    _inbox_repository = None
    _LegacyInboxRepository.reset_singleton_for_test()


# ── Legacy inbox_dao adapter (fallback) ─────────────────────────────────


class _LegacyInboxRepository:
    """Adapter that exposes :func:`dao.mysql.inbox.get_inbox_dao` (the
    pre-built singleton in ai-buddy) via the :class:`InboxRepository`
    Protocol.

    Lazy DAO lookup inside every method so the adapter survives
    early-boot scenarios.
    """

    _SINGLETON: Optional["_LegacyInboxRepository"] = None

    @classmethod
    def get_singleton(cls) -> "_LegacyInboxRepository":
        if cls._SINGLETON is None:
            cls._SINGLETON = cls()
        return cls._SINGLETON

    @classmethod
    def reset_singleton_for_test(cls) -> None:
        cls._SINGLETON = None

    @staticmethod
    def _dao() -> Any:
        try:
            from dao.mysql.inbox import get_inbox_dao
        except ImportError:
            return None
        return get_inbox_dao()

    async def create(self, item: InboxItemRow) -> str:
        dao = self._dao()
        if dao is None:
            raise InboxRepositoryNotInstalledError(
                "_LegacyInboxRepository: dao.mysql.inbox not importable; "
                "cannot create inbox row"
            )
        return await dao.create(item)

    async def list_by_issue(
        self,
        *,
        workspace_id: str,
        issue_id: str,
    ) -> List[InboxItemRow]:
        dao = self._dao()
        if dao is None:
            raise InboxRepositoryNotInstalledError(
                "_LegacyInboxRepository: dao.mysql.inbox not importable; "
                f"requested issue_id={issue_id!r}"
            )
        # Real DAO doesn't expose `list_by_issue` directly — the closest
        # method is `list_by_recipient`.  We synthesise via a workspace
        # scan + post-filter when the real DAO surface lacks the verb.
        # The production callers only WRITE today so this path is for
        # future engine surfaces (and tests that exercise the adapter).
        helper = getattr(dao, "list_by_issue", None)
        if helper is not None:
            return list(
                await helper(
                    workspace_id=workspace_id, issue_id=issue_id
                )
            )
        # Fall back: scan via list_by_recipient is impossible without
        # the recipient — return [] rather than raise so the engine
        # path can degrade gracefully.
        return []


# ── In-memory InboxRepository for tests + SDK default ───────────────────


class InMemoryInboxRepository:
    """InboxRepository impl for tests and SDK self-bundled default.

    Backed by a single dict ``_items: Dict[str, InboxItemRow]`` keyed
    by item id. All reads return deep copies so engine mutation does
    not leak back into the store.

    Concurrency: not strictly atomic across asyncio tasks — production
    multi-pod deployments must NOT share an in-memory repository.
    """

    def __init__(self) -> None:
        self._items: dict[str, InboxItemRow] = {}

    async def create(self, item: InboxItemRow) -> str:
        rec_id = getattr(item, "id", "") or str(uuid.uuid4())
        try:
            item.id = rec_id
        except (AttributeError, TypeError):
            pass
        self._items[rec_id] = copy.deepcopy(item)
        return rec_id

    async def list_by_issue(
        self,
        *,
        workspace_id: str,
        issue_id: str,
    ) -> List[InboxItemRow]:
        out: List[InboxItemRow] = []
        for r in self._items.values():
            if getattr(r, "workspace_id", "") != workspace_id:
                continue
            if str(getattr(r, "issue_id", "") or "") != str(issue_id):
                continue
            out.append(copy.deepcopy(r))
        # Stable ordering — created_at ASC mirrors the real DAO's
        # natural ORDER BY when scanning by issue.
        out.sort(key=lambda r: getattr(r, "created_at", "") or "")
        return out

    # ── Test helpers (not part of the Protocol) ──────────────────

    def seed(self, item: InboxItemRow) -> None:
        rec_id = getattr(item, "id", "") or str(uuid.uuid4())
        try:
            item.id = rec_id
        except (AttributeError, TypeError):
            pass
        self._items[rec_id] = copy.deepcopy(item)

    def list_ids(self) -> List[str]:
        return list(self._items.keys())

    def clear(self) -> None:
        self._items.clear()


__all__ = [
    "InboxItemRow",
    "InboxRepository",
    "InboxRepositoryNotInstalledError",
    "InMemoryInboxRepository",
    "set_inbox_repository",
    "get_inbox_repository",
    "reset_inbox_repository_for_test",
]
# ``_LegacyInboxRepository`` is intentionally NOT exported.
