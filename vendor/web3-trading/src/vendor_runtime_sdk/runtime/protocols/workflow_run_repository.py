# -*- coding: utf-8 -*-
"""
WorkflowRunRepository — PR-E4 of the Agent Engine SDK extraction plan.

See ``docs/Agent-Engine-SDK-剥离方案.md`` §5 Phase 0 PR-E4.

Goal
----
Replace the NL Workflow Engine's direct dependency on
``dao.mysql.runtime_workflow`` (the ai-buddy-specific MySQL DAO
singleton) with a Protocol-based seam. SDK consumers install their own
WorkflowRunRepository at boot; ai-buddy installs an adapter that wraps
``get_runtime_workflow_dao()`` so the existing engine code path is
byte-identical.

Today every engine call site that needs run-state persistence does::

    from dao.mysql.runtime_workflow import get_runtime_workflow_dao
    dao = get_runtime_workflow_dao()
    await dao.update_run(run_id, payload)
    await dao.claim_run(run_id, pod_id, workspace_id)
    await dao.heartbeat(run_id, pod_id)
    await dao.is_cancel_requested(run_id)
    await dao.get_run(run_id)
    await dao.get_by_id(workflow_id)

That import path is unreachable when the engine is packaged as the
SDK :mod:`kucoin-agent-runtime-sdk` (``dao/`` is the business layer,
kept outside the SDK). PR-E4 introduces the abstraction.

Scope (V1)
----------
This PR handles the 3 tier-1 call-site anchors in
``src/runtime/workflow_executor/``:

* ``_persistence.py`` — pure-write seam (``update_run`` x2 +
  workflow_node_assignment which is deferred to PR-E4b)
* ``_handlers_io.py`` — single READ callsite (``get_workflow_by_id`` at
  line 109 for nested-workflow dispatch)
* ``_core.py`` — load-bearing 试金石 covering every Protocol method
  (``claim_run`` + ``heartbeat`` + ``is_cancel_requested`` + 4x
  ``update_run`` + ``get_run``)

Coarse-grained business operations only
---------------------------------------
The Protocol surface is intentionally narrow:

* No raw SQL is passed through any method.
* ``update_run`` accepts a partial-payload dict because the audit
  shows 5 distinct partial-update shapes (``{node_results}`` /
  ``{workflow_context, node_results}`` / ``{status, started_at}`` /
  ``{status, error, completed_at}`` / ``{runtime_snapshot}``) —
  modelling each as a typed method would explode the surface 5x for
  no SDK-consumer benefit.
* ``claim_run`` / ``heartbeat`` / ``is_cancel_requested`` are
  inherently workflow-engine vocabulary, not generic CRUD.
* ``get_workflow_by_id`` is the read companion needed for nested
  sub-workflow dispatch — no write methods for the workflow
  definition itself (that lives in admin API and is out of engine
  scope).

Fall-back path (PR-E4 only; deleted in Phase 2)
-----------------------------------------------
When no provider is installed via :func:`set_workflow_run_repository`,
:func:`get_workflow_run_repository` lazily synthesises one that wraps
:func:`dao.mysql.runtime_workflow.get_runtime_workflow_dao`. This
makes PR-E4 a zero-behaviour-change refactor for ai-buddy's current
boot path. SDK consumers (Phase 2) must call
``set_workflow_run_repository(...)`` at boot before any engine path
runs.

Same pattern as PR-E1 :class:`EngineConfig`, PR-E3
:class:`ContextStore` and PR-E5 :class:`BackendClientProvider` —
engine carries its own contract; business layer keeps its own
concrete types; the SDK seam lives at the import boundary.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


class WorkflowRunRepositoryNotInstalledError(RuntimeError):
    """Raised when :func:`get_workflow_run_repository` is called before
    any repository is installed AND the legacy
    ``dao.mysql.runtime_workflow`` fallback is not reachable.

    SDK consumers (Phase 2 onwards) MUST call
    ``set_workflow_run_repository(repo)`` during boot before any
    engine module runs.
    """


@runtime_checkable
class WorkflowRunRepository(Protocol):
    """Pluggable repository for the NL Workflow Engine's run-state
    surface.

    Methods are coarse-grained business operations matched 1:1 to the
    13 audited engine call sites in ``src/runtime/workflow_executor/``.
    No method passes raw SQL; ``update_run`` accepts a partial-payload
    dict because the audit shows 5 distinct partial-update shapes
    (node_results / workflow_context+node_results / status+started_at /
    status+error+completed_at / runtime_snapshot) — modelling each as
    a typed method would 5x the surface for no SDK-consumer benefit.

    Implementations MUST be safe to call concurrently from asyncio
    tasks (the workflow executor fires heartbeat +
    persist_node_results in parallel via asyncio.gather).
    """

    async def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Return the run row as a dict (or ``None`` if not found).

        Engine callers read fields ``status / workflow_context /
        node_results / claimed_by_pod_id / last_heartbeat_at``. Returns
        a *copy* — implementations must NOT return a live reference to
        their internal storage (the engine occasionally mutates the
        returned dict in-place when reconstructing context for resume).
        """
        ...

    async def update_run(self, run_id: str, payload: Dict[str, Any]) -> None:
        """Apply a partial update to the run row.

        ``payload`` keys are column names; values are JSON-serialisable
        scalars or dict/list (which the real DAO serialises via
        ``json.dumps``). Unknown keys SHOULD raise in the legacy
        adapter (the real DAO has a column allowlist) but the Protocol
        does not mandate this so an InMemory impl can be permissive.

        Fire-and-forget — engine callers wrap every call in try/except
        and continue on failure. Returns ``None`` on success; raises
        on unrecoverable storage errors (which the caller logs +
        swallows).
        """
        ...

    async def claim_run(
        self, run_id: str, pod_id: str, workspace_id: str
    ) -> bool:
        """Attempt to claim ``run_id`` for ``pod_id``.

        Returns ``True`` on successful first-claim, ``False`` if
        another pod has already claimed the run (multi-instance race).
        The real DAO uses ``UPDATE ... WHERE claimed_by_pod IS NULL``
        CAS; InMemory impl uses dict pre-check. ``workspace_id`` is
        the tenant scope — implementations MAY use it for compound-
        index lookup or audit logging.
        """
        ...

    async def heartbeat(self, run_id: str, pod_id: str) -> None:
        """Update the run's heartbeat timestamp.

        Called every 60 s by the workflow executor's heartbeat loop.
        The real DAO sets ``heartbeat_at = NOW()``; InMemory impl uses
        ``datetime.utcnow()``. Engine callers swallow exceptions
        (``logger.debug``) so heartbeat failure does NOT abort the
        run.
        """
        ...

    async def is_cancel_requested(self, run_id: str) -> bool:
        """Return ``True`` if cancel has been requested for this run.

        Read-heavy — called inside the per-level executor loop at
        ``runtime/workflow_executor/_core.py:339``. Implementations
        MUST be cheap; the real DAO has a covering index on
        ``runtime_workflow_runs.cancel_requested_at``.
        """
        ...

    async def get_workflow_by_id(
        self, workflow_id: str
    ) -> Optional[Dict[str, Any]]:
        """Return the workflow definition row (or ``None``).

        Used for nested-workflow dispatch in
        ``runtime/workflow_executor/_handlers_io.py:109``. Returns the
        full workflow definition including ``graph_data``,
        ``runtime_config``, ``variables``. Returns a *copy* — same
        no-live-reference contract as :meth:`get_run`.
        """
        ...


# ── Module-level singleton ──────────────────────────────────────────────


_workflow_run_repository: Optional[WorkflowRunRepository] = None


def set_workflow_run_repository(repo: WorkflowRunRepository) -> None:
    """Install the WorkflowRunRepository used by engine modules.

    Idempotent — subsequent calls overwrite. Logs at INFO so boot
    order is auditable. **Never** logs the repo contents — run rows
    can hold prompt text + workspace_id (PII).

    Raises:
        TypeError: when ``repo`` does not satisfy the
            :class:`WorkflowRunRepository` Protocol at the structural
            level.
    """
    if not isinstance(repo, WorkflowRunRepository):
        raise TypeError(
            f"set_workflow_run_repository: repo must satisfy "
            f"WorkflowRunRepository Protocol (get_run / update_run / "
            f"claim_run / heartbeat / is_cancel_requested / "
            f"get_workflow_by_id), got {type(repo).__name__}"
        )
    global _workflow_run_repository
    _workflow_run_repository = repo
    logger.info(
        "WorkflowRunRepository installed: %s",
        type(repo).__name__,
    )


def get_workflow_run_repository() -> WorkflowRunRepository:
    """Return the installed repository, falling back to a lazy adapter
    that wraps
    :func:`dao.mysql.runtime_workflow.get_runtime_workflow_dao` when
    no explicit repository is installed.

    The fall-back is PR-E4-only and will be deleted in Phase 2 of the
    SDK extraction plan. SDK consumers MUST install a repository at
    boot.

    Raises:
        WorkflowRunRepositoryNotInstalledError: when no repository is
            installed AND ``dao.mysql.runtime_workflow`` is not
            importable.
    """
    if _workflow_run_repository is not None:
        return _workflow_run_repository

    # PR-E4 fall-back. Probe ``dao.mysql.runtime_workflow`` module
    # reachability — only the module needs to exist; the legacy
    # adapter handles the case where the singleton's MySQL pool is
    # not yet ready.
    try:
        import importlib
        importlib.import_module("dao.mysql.runtime_workflow")
    except ImportError as exc:
        raise WorkflowRunRepositoryNotInstalledError(
            "WorkflowRunRepository has not been installed and "
            "dao.mysql.runtime_workflow is not importable. Call "
            "set_workflow_run_repository(repo) at boot before any "
            "engine code path runs."
        ) from exc

    # Lazy-construct on first miss; cache so subsequent calls skip
    # the importlib probe.
    return _LegacyWorkflowRunRepository.get_singleton()


def reset_workflow_run_repository_for_test() -> None:
    """Test-only helper to clear the installed repository between
    cases.

    NOT for production use. Mirrors
    :func:`runtime.protocols.context_store.reset_context_store_for_test`.
    """
    global _workflow_run_repository
    _workflow_run_repository = None
    _LegacyWorkflowRunRepository.reset_singleton_for_test()


# ── Legacy runtime_workflow_dao adapter (fallback) ──────────────────────


class _LegacyWorkflowRunRepository:
    """Adapter that exposes
    :func:`dao.mysql.runtime_workflow.get_runtime_workflow_dao` (the
    pre-built singleton in ai-buddy) via the
    :class:`WorkflowRunRepository` Protocol.

    Used only via the fall-back path in
    :func:`get_workflow_run_repository` when no SDK-side repository
    is installed. ai-buddy can choose to install this adapter
    explicitly at boot (cleaner audit trail) or rely on the fall-back
    (zero boot wiring).

    Reads ``get_runtime_workflow_dao()`` lazily inside each method so
    the adapter survives early-boot scenarios where the MySQL pool
    isn't ready yet — same fail-soft pattern as
    :class:`runtime.protocols.context_store._LegacyContextStoreProvider`.

    The adapter forwards the partial-update payload dict UNVALIDATED;
    the real DAO has a column allowlist for SQL injection safety.
    Engine callers already build payloads from typed dicts (not user
    input) so this is safe in V1, but PR-E4b should add a typed
    Update DTO before SDK extraction completes.
    """

    _SINGLETON: Optional["_LegacyWorkflowRunRepository"] = None

    @classmethod
    def get_singleton(cls) -> "_LegacyWorkflowRunRepository":
        if cls._SINGLETON is None:
            cls._SINGLETON = cls()
        return cls._SINGLETON

    @classmethod
    def reset_singleton_for_test(cls) -> None:
        cls._SINGLETON = None

    @staticmethod
    def _dao() -> Any:
        """Read the ai-buddy ``get_runtime_workflow_dao()`` singleton
        lazily.

        Returns ``None`` when ``dao.mysql.runtime_workflow`` isn't
        importable — callers see
        :class:`WorkflowRunRepositoryNotInstalledError` on first use.
        """
        try:
            from dao.mysql.runtime_workflow import get_runtime_workflow_dao
        except ImportError:
            return None
        return get_runtime_workflow_dao()

    async def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        dao = self._dao()
        if dao is None:
            raise WorkflowRunRepositoryNotInstalledError(
                "_LegacyWorkflowRunRepository: "
                "dao.mysql.runtime_workflow not importable; "
                f"requested run_id={run_id!r}"
            )
        return await dao.get_run(run_id)

    async def update_run(
        self, run_id: str, payload: Dict[str, Any]
    ) -> None:
        dao = self._dao()
        if dao is None:
            raise WorkflowRunRepositoryNotInstalledError(
                "_LegacyWorkflowRunRepository: "
                "dao.mysql.runtime_workflow not importable; "
                f"requested run_id={run_id!r}"
            )
        # Real DAO returns bool; engine callers don't use the value,
        # so we drop it to match the Protocol's ``None`` return.
        await dao.update_run(run_id, payload)

    async def claim_run(
        self, run_id: str, pod_id: str, workspace_id: str
    ) -> bool:
        dao = self._dao()
        if dao is None:
            raise WorkflowRunRepositoryNotInstalledError(
                "_LegacyWorkflowRunRepository: "
                "dao.mysql.runtime_workflow not importable; "
                f"requested run_id={run_id!r}"
            )
        return bool(
            await dao.claim_run(run_id, pod_id, workspace_id)
        )

    async def heartbeat(self, run_id: str, pod_id: str) -> None:
        dao = self._dao()
        if dao is None:
            raise WorkflowRunRepositoryNotInstalledError(
                "_LegacyWorkflowRunRepository: "
                "dao.mysql.runtime_workflow not importable; "
                f"requested run_id={run_id!r}"
            )
        # Real DAO returns bool; the Protocol drops it.
        await dao.heartbeat(run_id, pod_id)

    async def is_cancel_requested(self, run_id: str) -> bool:
        dao = self._dao()
        if dao is None:
            raise WorkflowRunRepositoryNotInstalledError(
                "_LegacyWorkflowRunRepository: "
                "dao.mysql.runtime_workflow not importable; "
                f"requested run_id={run_id!r}"
            )
        return bool(await dao.is_cancel_requested(run_id))

    async def get_workflow_by_id(
        self, workflow_id: str
    ) -> Optional[Dict[str, Any]]:
        dao = self._dao()
        if dao is None:
            raise WorkflowRunRepositoryNotInstalledError(
                "_LegacyWorkflowRunRepository: "
                "dao.mysql.runtime_workflow not importable; "
                f"requested workflow_id={workflow_id!r}"
            )
        return await dao.get_by_id(workflow_id)


# ── In-memory WorkflowRunRepository for tests + SDK default ─────────────


class InMemoryWorkflowRunRepository:
    """WorkflowRunRepository impl for tests and SDK self-bundled
    default.

    Backed by two dict-keyed maps: ``_runs`` (run_id → payload) and
    ``_workflows`` (workflow_id → definition). All reads return a
    *copy* — preserves the no-live-reference contract documented on
    the Protocol.

    Concurrency: dict-mutation is not strictly atomic across asyncio
    tasks, but the linear-scan footprint per call is small enough that
    realistic test workloads never race. Production multi-pod
    deployments must NOT share an in-memory repository — install the
    legacy MySQL adapter or a custom SDK provider instead.
    """

    def __init__(
        self,
        runs: Optional[Dict[str, Dict[str, Any]]] = None,
        workflows: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        # Deep-ish copy so callers can mutate the seeds without
        # contaminating the store.
        self._runs: Dict[str, Dict[str, Any]] = {
            rid: dict(payload) for rid, payload in (runs or {}).items()
        }
        self._workflows: Dict[str, Dict[str, Any]] = {
            wid: dict(payload) for wid, payload in (workflows or {}).items()
        }

    async def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        existing = self._runs.get(run_id)
        # Deep-copy: the Protocol contract documents that callers may
        # mutate the returned dict (including nested ``node_results`` /
        # ``workflow_context`` sub-objects) during resume reconstruction.
        # A shallow ``dict(existing)`` shares references to nested
        # mutable sub-dicts, so a caller mutation would leak back into
        # the in-memory store and break test isolation.
        import copy as _copy
        return _copy.deepcopy(existing) if existing is not None else None

    async def update_run(
        self, run_id: str, payload: Dict[str, Any]
    ) -> None:
        existing = self._runs.get(run_id)
        if existing is None:
            # New row — create from payload (real DAO would no-op when
            # WHERE matches zero rows; we mirror best-effort upsert
            # semantics for tests that pre-seed sparse state).
            self._runs[run_id] = dict(payload)
            return
        existing.update(payload)

    async def claim_run(
        self, run_id: str, pod_id: str, workspace_id: str
    ) -> bool:
        run = self._runs.get(run_id)
        if run is None:
            # No row → no claim. Real DAO returns False here too.
            return False
        # Per design notes — first-claim wins; re-claim by same pod is
        # idempotent (mirrors real DAO's
        # ``WHERE claimed_by_pod IS NULL OR claimed_by_pod = %s``).
        current = run.get("claimed_by_pod")
        if current is not None and current != pod_id:
            return False
        run["claimed_by_pod"] = pod_id
        run["workspace_id"] = run.get("workspace_id", workspace_id)
        from datetime import datetime
        run["heartbeat_at"] = datetime.utcnow().isoformat()
        return True

    async def heartbeat(self, run_id: str, pod_id: str) -> None:
        run = self._runs.get(run_id)
        if run is None:
            return
        # Only refresh heartbeat if owned by the calling pod — matches
        # real DAO's ``WHERE id = %s AND claimed_by_pod = %s``.
        if run.get("claimed_by_pod") != pod_id:
            return
        from datetime import datetime
        run["heartbeat_at"] = datetime.utcnow().isoformat()

    async def is_cancel_requested(self, run_id: str) -> bool:
        run = self._runs.get(run_id)
        if run is None:
            return False
        return run.get("cancel_requested_at") is not None

    async def get_workflow_by_id(
        self, workflow_id: str
    ) -> Optional[Dict[str, Any]]:
        existing = self._workflows.get(workflow_id)
        # Deep-copy: mirrors get_run's no-live-reference contract.
        import copy as _copy
        return _copy.deepcopy(existing) if existing is not None else None

    # ── Test helpers (not part of the Protocol) ──────────────────

    def seed_run(self, run_id: str, payload: Dict[str, Any]) -> None:
        """Insert / overwrite a run row.  Test-only convenience."""
        self._runs[run_id] = dict(payload)

    def seed_workflow(self, workflow_id: str, payload: Dict[str, Any]) -> None:
        """Insert / overwrite a workflow definition.  Test-only
        convenience."""
        self._workflows[workflow_id] = dict(payload)

    def request_cancel(self, run_id: str) -> bool:
        """Simulate the cancel-request path in tests.  Returns
        ``False`` when ``run_id`` is unknown."""
        run = self._runs.get(run_id)
        if run is None:
            return False
        from datetime import datetime
        run["cancel_requested_at"] = datetime.utcnow().isoformat()
        return True

    def list_run_ids(self) -> List[str]:
        """Test introspection helper."""
        return list(self._runs.keys())


__all__ = [
    "WorkflowRunRepository",
    "WorkflowRunRepositoryNotInstalledError",
    "InMemoryWorkflowRunRepository",
    "set_workflow_run_repository",
    "get_workflow_run_repository",
    "reset_workflow_run_repository_for_test",
]
# ``_LegacyWorkflowRunRepository`` is intentionally NOT exported — it
# is the PR-E4-only fallback adapter and matches the PR-E3/E5
# convention (``_LegacyContextStoreProvider`` /
# ``_LegacyComponentBackendProvider`` are also private). Tests import
# it directly by name, which is fine for private symbols.
