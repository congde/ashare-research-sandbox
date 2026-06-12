# -*- coding: utf-8 -*-
"""
ApprovalRequestRepository — PR-E4c of the Agent Engine SDK extraction plan.

See ``docs/Agent-Engine-SDK-剥离方案.md`` §5 Phase 0 PR-E4c.

Goal
----
Replace the engine layer's direct dependency on
``dao.mysql.approval_request`` (the ai-buddy-specific MySQL DAO singleton)
with a Protocol-based seam. SDK consumers install their own
:class:`ApprovalRequestRepository` at boot; ai-buddy installs an adapter
that wraps :func:`dao.mysql.approval_request.get_approval_request_dao` so
the existing engine code path is byte-identical.

Today the engine call sites that need approval-request state do::

    from dao.mysql.approval_request import (
        ApprovalRequestDao,
        ApprovalRequestRow,
        get_approval_request_dao,
    )
    dao = ApprovalRequestDao()  # or get_approval_request_dao()
    await dao.find_unalerted_sla_breaches(threshold_hours=h)
    await dao.mark_sla_alerted(request_id)

That import path is unreachable when the engine is packaged as the SDK
:mod:`kucoin-agent-runtime-sdk` (``dao/`` is the business layer kept out
of the SDK). PR-E4c introduces the abstraction.

Scope (V1)
----------
The audit identifies the engine-side SLA scanner as the cleanest
migration target. Four methods chosen to cover both the SLA scan path
and the create+lookup+status surface (the dispatcher-side carryover in
``orchestration/task_dispatcher.py`` retains a direct DAO import as a
Phase-2 business-layer move — it bundles Lark/tenant-context coupling
that is NOT engine-shaped):

* :meth:`ApprovalRequestRepository.create` — insert + return id
* :meth:`ApprovalRequestRepository.get_by_id` — lookup row by id
* :meth:`ApprovalRequestRepository.find_unalerted_sla_breaches` —
  scanner-side find of stale ``pending`` rows past the SLA threshold
* :meth:`ApprovalRequestRepository.mark_sla_alerted` — CAS that
  guarantees exactly-once Lark notification across racing scanner
  instances

Admin-only surfaces (``list_pending`` / ``list_pending_workspace_joins``
/ ``approve`` / ``reject`` / ``cancel``) stay on the concrete
:class:`ApprovalRequestDao` — they're called from HTTP API routers, not
engine code paths.

ApprovalRequestRow re-export
----------------------------
:class:`ApprovalRequestRow` currently lives in
``src/dao/mysql/approval_request.py``. PR-E4c re-exports it from this
protocol module via a guarded import: when ``dao.mysql.approval_request``
is reachable we re-export the canonical dataclass; otherwise we
synthesise a minimal local replica with the same field surface. In
Phase 2 (post-extraction) the local replica becomes the canonical
definition and the ``dao.mysql`` version is deleted.

Fall-back path (PR-E4c only; deleted in Phase 2)
------------------------------------------------
When no provider is installed via :func:`set_approval_request_repository`,
:func:`get_approval_request_repository` lazily synthesises one that
wraps :func:`dao.mysql.approval_request.get_approval_request_dao`. This
makes PR-E4c a zero-behaviour-change refactor for ai-buddy's current
boot path. SDK consumers (Phase 2) MUST call
``set_approval_request_repository(...)`` at boot before any engine path
runs.

Same pattern as PR-E4 :class:`CostRecordRepository` /
:class:`WorkflowRunRepository` and PR-E4b :class:`AgentRepository` /
:class:`IssueRepository` — engine carries its own contract; business
layer keeps its own concrete types; the SDK seam lives at the import
boundary.
"""

from __future__ import annotations

import copy
import logging
import uuid
from dataclasses import dataclass
from typing import Any, List, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ── ApprovalRequestRow re-export ────────────────────────────────────────


try:
    from dao.mysql.approval_request import (
        ApprovalRequestRow as _LegacyApprovalRequestRow,
    )
    ApprovalRequestRow = _LegacyApprovalRequestRow  # type: ignore[misc,assignment]
except ImportError:  # pragma: no cover — exercised only in SDK-extracted scenario
    @dataclass
    class ApprovalRequestRow:  # type: ignore[no-redef]
        """Minimal local replica of
        :class:`dao.mysql.approval_request.ApprovalRequestRow`.

        Mirrors the field surface used by engine call sites. Activated
        only when ``dao.mysql.approval_request`` is not importable —
        i.e. the SDK-extracted scenario where the ``dao/`` package is
        no longer on the import path.
        """

        # Non-default fields must come first (mirrors real DAO order).
        id: str = ""
        request_type: str = ""
        requester_id: str = ""
        target_entity_type: str = ""
        # Fields with defaults
        workspace_id: Optional[str] = None
        target_entity_id: Optional[str] = None
        title: str = ""
        reason: str = ""
        extra_data: Optional[str] = None
        lark_instance_id: Optional[str] = None
        status: str = "pending"
        reviewer_id: Optional[str] = None
        review_comment: Optional[str] = None
        reviewed_at: Optional[str] = None
        sla_breach_alerted_at: Optional[str] = None
        created_at: str = ""
        updated_at: str = ""


class ApprovalRequestRepositoryNotInstalledError(RuntimeError):
    """Raised when :func:`get_approval_request_repository` is called
    before any repository is installed AND the legacy
    ``dao.mysql.approval_request`` fallback is not reachable.

    SDK consumers (Phase 2 onwards) MUST call
    ``set_approval_request_repository(repo)`` during boot before any
    engine module runs.
    """


# Valid SLA threshold envelope mirroring the production DAO contract;
# the underlying DAO raises ``ValueError`` outside this range.
_SLA_MIN_THRESHOLD_HOURS = 1
_SLA_MAX_THRESHOLD_HOURS = 24 * 365


@runtime_checkable
class ApprovalRequestRepository(Protocol):
    """Pluggable repository for approval-request CRUD + SLA scanner.

    Methods are coarse-grained business operations matched 1:1 to the
    engine-side call sites — the SLA scanner is the cleanest engine
    consumer and the dispatch path (``orchestration/task_dispatcher.py``)
    is a Phase-2 business-layer move (Lark + tenant coupling).

    Implementations MUST be safe to call concurrently from asyncio
    tasks — racing scanner instances are the CAS-on-``mark_sla_alerted``
    use case.
    """

    async def create(self, row: ApprovalRequestRow) -> str:
        """Insert a new approval-request row. Returns the inserted ``id``.

        When ``row.id`` is empty, implementations MAY generate one
        (the real DAO uses ``uuid.uuid4()``); the returned id is the
        canonical row identifier.
        """
        ...

    async def get_by_id(
        self, request_id: str
    ) -> Optional[ApprovalRequestRow]:
        """Return the approval-request row, or ``None`` if not found.

        Implementations MUST return a fresh instance (or deep copy);
        engine code may mutate fields like ``status`` during the
        approval round-trip and must not leak back into the store.
        """
        ...

    async def find_unalerted_sla_breaches(
        self, *, threshold_hours: int,
    ) -> List[ApprovalRequestRow]:
        """Return pending approval rows older than ``threshold_hours``
        that the scanner hasn't notified the approver about yet.

        **Cross-tenant by design**: the SLA scanner is a per-deployment
        beat task that emits notifications for EVERY pending approval
        in EVERY workspace.  This contract intentionally lacks a
        ``workspace_id`` filter because the production scanner runs
        ONCE per beat and dispatches to workspace-scoped notification
        channels via the returned rows' own ``workspace_id`` field.
        SDK consumers that need strict tenant scoping MUST filter the
        returned list themselves; the Protocol's contract is "all
        tenants, one call".  Documented explicitly per PR-E4c review.

        ``threshold_hours`` must be in ``[1, 24*365]``; implementations
        SHOULD raise :class:`ValueError` outside that range — preserves
        the production DAO contract.

        Returns an empty list (never ``None``) on no matches.
        """
        ...

    async def mark_sla_alerted(self, request_id: str) -> bool:
        """Stamp ``sla_breach_alerted_at = NOW()`` so the scanner skips
        this row on the next tick.

        Idempotent CAS — returns ``True`` for the racing instance that
        won the swap; ``False`` for losers (already-alerted rows).
        Raises :class:`ValueError` when ``request_id`` is empty.
        """
        ...


# ── Module-level singleton ──────────────────────────────────────────────


_approval_request_repository: Optional[ApprovalRequestRepository] = None


def set_approval_request_repository(repo: ApprovalRequestRepository) -> None:
    """Install the ApprovalRequestRepository used by engine modules.

    Idempotent — subsequent calls overwrite. Logs at INFO so boot order
    is auditable. **Never** logs the repo contents — approval rows
    carry ``requester_id`` / ``reviewer_id`` (PII).

    Raises:
        TypeError: when ``repo`` does not satisfy the
            :class:`ApprovalRequestRepository` Protocol at the
            structural level.
    """
    if not isinstance(repo, ApprovalRequestRepository):
        raise TypeError(
            f"set_approval_request_repository: repo must satisfy "
            f"ApprovalRequestRepository Protocol (create / get_by_id / "
            f"find_unalerted_sla_breaches / mark_sla_alerted), "
            f"got {type(repo).__name__}"
        )
    global _approval_request_repository
    _approval_request_repository = repo
    logger.info(
        "ApprovalRequestRepository installed: %s", type(repo).__name__
    )


def get_approval_request_repository() -> ApprovalRequestRepository:
    """Return the installed repository, falling back to a lazy adapter
    that wraps :func:`dao.mysql.approval_request.get_approval_request_dao`
    when no explicit repository is installed.

    The fall-back is PR-E4c-only and will be deleted in Phase 2 of the
    SDK extraction plan. SDK consumers MUST install a repository at
    boot.

    Raises:
        ApprovalRequestRepositoryNotInstalledError: when no repository
            is installed AND ``dao.mysql.approval_request`` is not
            importable.
    """
    if _approval_request_repository is not None:
        return _approval_request_repository

    try:
        import importlib
        importlib.import_module("dao.mysql.approval_request")
    except ImportError as exc:
        raise ApprovalRequestRepositoryNotInstalledError(
            "ApprovalRequestRepository has not been installed and "
            "dao.mysql.approval_request is not importable. Call "
            "set_approval_request_repository(repo) at boot before "
            "any engine code path runs."
        ) from exc

    return _LegacyApprovalRequestRepository.get_singleton()


def reset_approval_request_repository_for_test() -> None:
    """Test-only helper to clear the installed repository between cases.

    NOT for production use. Mirrors
    :func:`runtime.protocols.agent_repository.reset_agent_repository_for_test`.
    """
    global _approval_request_repository
    _approval_request_repository = None
    _LegacyApprovalRequestRepository.reset_singleton_for_test()


# ── Legacy approval_request_dao adapter (fallback) ──────────────────────


class _LegacyApprovalRequestRepository:
    """Adapter that exposes
    :func:`dao.mysql.approval_request.get_approval_request_dao` (the
    pre-built singleton in ai-buddy) via the
    :class:`ApprovalRequestRepository` Protocol.

    Lazy DAO lookup inside every method so the adapter survives
    early-boot scenarios where the MySQL pool isn't ready yet.
    """

    _SINGLETON: Optional["_LegacyApprovalRequestRepository"] = None

    @classmethod
    def get_singleton(cls) -> "_LegacyApprovalRequestRepository":
        if cls._SINGLETON is None:
            cls._SINGLETON = cls()
        return cls._SINGLETON

    @classmethod
    def reset_singleton_for_test(cls) -> None:
        cls._SINGLETON = None

    @staticmethod
    def _dao() -> Any:
        try:
            from dao.mysql.approval_request import get_approval_request_dao
        except ImportError:
            return None
        return get_approval_request_dao()

    async def create(self, row: ApprovalRequestRow) -> str:
        dao = self._dao()
        if dao is None:
            raise ApprovalRequestRepositoryNotInstalledError(
                "_LegacyApprovalRequestRepository: "
                "dao.mysql.approval_request not importable; "
                "cannot create approval-request row"
            )
        return await dao.create(row)

    async def get_by_id(
        self, request_id: str
    ) -> Optional[ApprovalRequestRow]:
        dao = self._dao()
        if dao is None:
            raise ApprovalRequestRepositoryNotInstalledError(
                "_LegacyApprovalRequestRepository: "
                "dao.mysql.approval_request not importable; "
                f"requested request_id={request_id!r}"
            )
        return await dao.get_by_id(request_id)

    async def find_unalerted_sla_breaches(
        self, *, threshold_hours: int,
    ) -> List[ApprovalRequestRow]:
        dao = self._dao()
        if dao is None:
            raise ApprovalRequestRepositoryNotInstalledError(
                "_LegacyApprovalRequestRepository: "
                "dao.mysql.approval_request not importable; "
                "cannot scan SLA breaches"
            )
        return list(
            await dao.find_unalerted_sla_breaches(
                threshold_hours=threshold_hours
            )
        )

    async def mark_sla_alerted(self, request_id: str) -> bool:
        dao = self._dao()
        if dao is None:
            raise ApprovalRequestRepositoryNotInstalledError(
                "_LegacyApprovalRequestRepository: "
                "dao.mysql.approval_request not importable; "
                f"requested request_id={request_id!r}"
            )
        return bool(await dao.mark_sla_alerted(request_id))


# ── In-memory ApprovalRequestRepository for tests + SDK default ─────────


class InMemoryApprovalRequestRepository:
    """ApprovalRequestRepository impl for tests and SDK self-bundled
    default.

    Backed by a single dict ``_rows: Dict[str, ApprovalRequestRow]``
    keyed by request id. All reads return deep copies so engine
    mutation does not leak back into the store.

    Concurrency: dict-mutation is not strictly atomic across asyncio
    tasks, but the linear-scan footprint per call is small enough that
    realistic test workloads never race. Production multi-pod
    deployments must NOT share an in-memory repository — install the
    legacy MySQL adapter or a custom SDK provider instead.
    """

    def __init__(self) -> None:
        self._rows: dict[str, ApprovalRequestRow] = {}

    async def create(self, row: ApprovalRequestRow) -> str:
        rec_id = getattr(row, "id", "") or str(uuid.uuid4())
        try:
            row.id = rec_id
        except (AttributeError, TypeError):
            pass
        self._rows[rec_id] = copy.deepcopy(row)
        return rec_id

    async def get_by_id(
        self, request_id: str
    ) -> Optional[ApprovalRequestRow]:
        existing = self._rows.get(request_id)
        if existing is None:
            return None
        return copy.deepcopy(existing)

    async def find_unalerted_sla_breaches(
        self, *, threshold_hours: int,
    ) -> List[ApprovalRequestRow]:
        if (
            threshold_hours < _SLA_MIN_THRESHOLD_HOURS
            or threshold_hours > _SLA_MAX_THRESHOLD_HOURS
        ):
            raise ValueError(
                f"threshold_hours out of range "
                f"({_SLA_MIN_THRESHOLD_HOURS}..{_SLA_MAX_THRESHOLD_HOURS}); "
                f"got {threshold_hours}"
            )
        # In-memory impl matches every pending+unalerted row regardless
        # of created_at — the production DAO compares MySQL NOW(3); a
        # full clock-aware emulation here would tie tests to wall time.
        # Tests use ``seed`` + matching status to drive the scanner.
        out: List[ApprovalRequestRow] = []
        for r in self._rows.values():
            if getattr(r, "status", "") != "pending":
                continue
            if getattr(r, "sla_breach_alerted_at", None):
                continue
            out.append(copy.deepcopy(r))
        # Stable ordering — ``created_at`` ASC mirrors the real DAO.
        out.sort(key=lambda r: getattr(r, "created_at", "") or "")
        return out

    async def mark_sla_alerted(self, request_id: str) -> bool:
        """Atomic CAS: deep-copy → mutate → replace.  Mirrors the
        ``WHERE sla_breach_alerted_at IS NULL`` idempotency guard so
        repeated calls (racing scanner instances) only succeed once.
        """
        if not request_id or not str(request_id).strip():
            raise ValueError("request_id is required")
        row = self._rows.get(request_id)
        if row is None:
            return False
        if getattr(row, "sla_breach_alerted_at", None):
            return False
        new_row = copy.deepcopy(row)
        # Use a stable sentinel rather than wall time so tests are
        # deterministic; production DAO writes ``NOW(3)``.
        new_row.sla_breach_alerted_at = "in-memory-alerted"
        self._rows[request_id] = new_row
        return True

    # ── Test helpers (not part of the Protocol) ──────────────────

    def seed(self, row: ApprovalRequestRow) -> None:
        """Insert / overwrite an approval row.  Test-only convenience."""
        rec_id = getattr(row, "id", "") or str(uuid.uuid4())
        try:
            row.id = rec_id
        except (AttributeError, TypeError):
            pass
        self._rows[rec_id] = copy.deepcopy(row)

    def list_ids(self) -> List[str]:
        return list(self._rows.keys())

    def clear(self) -> None:
        self._rows.clear()


__all__ = [
    "ApprovalRequestRow",
    "ApprovalRequestRepository",
    "ApprovalRequestRepositoryNotInstalledError",
    "InMemoryApprovalRequestRepository",
    "set_approval_request_repository",
    "get_approval_request_repository",
    "reset_approval_request_repository_for_test",
]
# ``_LegacyApprovalRequestRepository`` is intentionally NOT exported —
# same convention as ``_LegacyAgentRepository`` / ``_LegacyIssueRepository``.
