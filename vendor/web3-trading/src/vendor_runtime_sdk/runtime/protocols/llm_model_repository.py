# -*- coding: utf-8 -*-
"""
LlmModelRepository — PR-E4c of the Agent Engine SDK extraction plan.

See ``docs/Agent-Engine-SDK-剥离方案.md`` §5 Phase 0 PR-E4c.

Goal
----
Replace the engine layer's direct dependency on ``dao.mysql.llm_model``
(the ai-buddy-specific MySQL DAO singleton) with a Protocol-based seam.
SDK consumers install their own :class:`LlmModelRepository` at boot;
ai-buddy installs an adapter that wraps
:func:`dao.mysql.llm_model.get_llm_model_dao` so the existing engine
code path is byte-identical.

Today the engine call sites that read LLM model + router config do::

    from dao.mysql.llm_model import get_llm_model_dao
    dao = get_llm_model_dao()
    models = await dao.list_models(active_only=True)
    router_cfg = await dao.get_router_config("default")

That import path is unreachable when the engine is packaged as the SDK
:mod:`kucoin-agent-runtime-sdk` (``dao/`` is the business layer kept
out of the SDK). PR-E4c introduces the abstraction.

Scope (V1)
----------
The audit identifies a single engine call site — ``src/llm/router_llm.py
:_load_router_config_from_db`` — that reads the model catalogue + router
selection on warmup. Two methods cover both reads:

* :meth:`LlmModelRepository.list_models` — return all model rows
  (with API key decrypted to plaintext); ``active_only=True`` filters
  to ``is_active=1``.
* :meth:`LlmModelRepository.get_router_config` — return one router
  config (primary + fallback model ids).

Admin-only surfaces (``create_model`` / ``update_model`` /
``delete_model`` / ``seed_from_yaml`` / etc.) stay on the concrete
:class:`LlmModelDao` — they're called from HTTP API routers, not
engine code paths.

LlmModelRow + RouterLlmConfigRow re-export
------------------------------------------
Both dataclasses currently live in ``src/dao/mysql/llm_model.py``.
PR-E4c re-exports them from this protocol module via a guarded import:
when ``dao.mysql.llm_model`` is reachable we re-export the canonical
dataclasses; otherwise we synthesise minimal local replicas with the
same field surface. In Phase 2 (post-extraction) the local replicas
become the canonical definitions and the ``dao.mysql`` version is
deleted.

Security note
-------------
:attr:`LlmModelRow.api_key` is the **DECRYPTED** plaintext — same as
the production DAO ``_row_to_model`` contract. The repo MUST be
treated as a secret-bearing object: never log row contents, never
serialise to disk without re-encrypting. The InMemory impl is
test-only.

Fall-back path (PR-E4c only; deleted in Phase 2)
------------------------------------------------
When no provider is installed via :func:`set_llm_model_repository`,
:func:`get_llm_model_repository` lazily synthesises one that wraps
:func:`dao.mysql.llm_model.get_llm_model_dao`. This makes PR-E4c a
zero-behaviour-change refactor for ai-buddy's current boot path. SDK
consumers (Phase 2) MUST call ``set_llm_model_repository(...)`` at
boot before any engine path runs.

Same pattern as PR-E4 :class:`CostRecordRepository` and PR-E4b
:class:`AgentRepository` / :class:`IssueRepository`.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ── LlmModelRow + RouterLlmConfigRow re-export ──────────────────────────


try:
    from dao.mysql.llm_model import LlmModelRow as _LegacyLlmModelRow
    LlmModelRow = _LegacyLlmModelRow  # type: ignore[misc,assignment]
except ImportError:  # pragma: no cover — exercised only in SDK-extracted scenario
    @dataclass
    class LlmModelRow:  # type: ignore[no-redef]
        """Minimal local replica of :class:`dao.mysql.llm_model.LlmModelRow`.

        Mirrors the field surface used by engine call sites. Activated
        only when ``dao.mysql.llm_model`` is not importable.

        Note: ``api_key`` is the **DECRYPTED** plaintext. Never log
        row contents.
        """

        # Non-default fields first (mirrors real DAO order).
        id: str = ""
        config_key: str = ""
        display_name: str = ""
        provider: str = ""
        api_base: str = ""
        api_key: str = ""  # Decrypted plaintext
        model_name: str = ""
        # Fields with defaults
        timeout: int = 15
        max_tokens: Optional[int] = None
        temperature: Optional[float] = None
        is_active: bool = True
        priority: int = 0
        metadata: Optional[Dict[str, Any]] = None
        tenant_id: Optional[str] = None
        created_at: str = ""
        updated_at: str = ""


try:
    from dao.mysql.llm_model import (
        RouterLlmConfigRow as _LegacyRouterLlmConfigRow,
    )
    RouterLlmConfigRow = _LegacyRouterLlmConfigRow  # type: ignore[misc,assignment]
except ImportError:  # pragma: no cover — SDK-extracted scenario only
    @dataclass
    class RouterLlmConfigRow:  # type: ignore[no-redef]
        """Minimal local replica of
        :class:`dao.mysql.llm_model.RouterLlmConfigRow`."""

        id: str = ""
        config_key: str = ""
        display_name: str = ""
        primary_model_id: str = ""
        fallback_model_ids: List[str] = field(default_factory=list)
        max_retries: int = 3
        is_active: bool = True
        tenant_id: Optional[str] = None
        created_at: str = ""
        updated_at: str = ""


class LlmModelRepositoryNotInstalledError(RuntimeError):
    """Raised when :func:`get_llm_model_repository` is called before any
    repository is installed AND the legacy ``dao.mysql.llm_model``
    fallback is not reachable.

    SDK consumers (Phase 2 onwards) MUST call
    ``set_llm_model_repository(repo)`` during boot before any engine
    module runs.
    """


@runtime_checkable
class LlmModelRepository(Protocol):
    """Pluggable repository for LLM model catalogue + router config reads.

    Methods are coarse-grained business operations matched 1:1 to the
    engine call site in ``src/llm/router_llm.py:_load_router_config_from_db``.

    Implementations MUST be safe to call concurrently — model catalogue
    warmup may race with hot-reload triggers.
    """

    async def list_models(
        self,
        *,
        active_only: bool = False,
        tenant_id: Optional[str] = None,
    ) -> List[LlmModelRow]:
        """Return LLM model rows visible to ``tenant_id``.

        ``tenant_id=None`` returns the catalogue across **all
        tenants** — mirrors the legacy DAO contract used by the admin
        model registry + LLM router selection paths.  SDK consumers
        that need strict tenant scoping MUST pass an explicit
        ``tenant_id``; otherwise the caller is responsible for
        downstream tenant filtering.  Documented explicitly per
        PR-E4c review (tenant_id=None is cross-tenant by design, not
        an oversight).

        ``active_only=True`` filters to ``is_active=True``. Returns an
        empty list (never ``None``) when the catalogue is empty or
        unreachable (legacy DAO catches ``OperationalError`` and
        returns ``[]`` — preserve that contract).

        ``api_key`` on each returned row is the **decrypted** plaintext.
        Callers MUST treat the result as secret material.
        """
        ...

    async def get_router_config(
        self,
        *,
        config_key: str = "default",
        tenant_id: Optional[str] = None,
    ) -> Optional[RouterLlmConfigRow]:
        """Return the router config keyed by ``config_key`` for
        ``tenant_id``, or ``None`` if not found.

        Used by ``router_llm._load_router_config_from_db`` to resolve
        primary + fallback model selection.
        """
        ...


# ── Module-level singleton ──────────────────────────────────────────────


_llm_model_repository: Optional[LlmModelRepository] = None


def set_llm_model_repository(repo: LlmModelRepository) -> None:
    """Install the LlmModelRepository used by engine modules.

    Idempotent — subsequent calls overwrite. Logs at INFO so boot order
    is auditable. **Never** logs the repo contents — model rows carry
    decrypted ``api_key`` plaintext (secret material).

    Raises:
        TypeError: when ``repo`` does not satisfy the
            :class:`LlmModelRepository` Protocol at the structural
            level.
    """
    if not isinstance(repo, LlmModelRepository):
        raise TypeError(
            f"set_llm_model_repository: repo must satisfy "
            f"LlmModelRepository Protocol (list_models / "
            f"get_router_config), got {type(repo).__name__}"
        )
    global _llm_model_repository
    _llm_model_repository = repo
    logger.info("LlmModelRepository installed: %s", type(repo).__name__)


def get_llm_model_repository() -> LlmModelRepository:
    """Return the installed repository, falling back to a lazy adapter
    that wraps :func:`dao.mysql.llm_model.get_llm_model_dao` when no
    explicit repository is installed.

    The fall-back is PR-E4c-only and will be deleted in Phase 2 of the
    SDK extraction plan. SDK consumers MUST install a repository at
    boot.

    Raises:
        LlmModelRepositoryNotInstalledError: when no repository is
            installed AND ``dao.mysql.llm_model`` is not importable.
    """
    if _llm_model_repository is not None:
        return _llm_model_repository

    try:
        import importlib
        importlib.import_module("dao.mysql.llm_model")
    except ImportError as exc:
        raise LlmModelRepositoryNotInstalledError(
            "LlmModelRepository has not been installed and "
            "dao.mysql.llm_model is not importable. Call "
            "set_llm_model_repository(repo) at boot before any "
            "engine code path runs."
        ) from exc

    return _LegacyLlmModelRepository.get_singleton()


def reset_llm_model_repository_for_test() -> None:
    """Test-only helper to clear the installed repository between cases."""
    global _llm_model_repository
    _llm_model_repository = None
    _LegacyLlmModelRepository.reset_singleton_for_test()


# ── Legacy llm_model_dao adapter (fallback) ─────────────────────────────


class _LegacyLlmModelRepository:
    """Adapter that exposes :func:`dao.mysql.llm_model.get_llm_model_dao`
    (the pre-built singleton in ai-buddy) via the
    :class:`LlmModelRepository` Protocol.

    Lazy DAO lookup inside every method so the adapter survives
    early-boot scenarios.
    """

    _SINGLETON: Optional["_LegacyLlmModelRepository"] = None

    @classmethod
    def get_singleton(cls) -> "_LegacyLlmModelRepository":
        if cls._SINGLETON is None:
            cls._SINGLETON = cls()
        return cls._SINGLETON

    @classmethod
    def reset_singleton_for_test(cls) -> None:
        cls._SINGLETON = None

    @staticmethod
    def _dao() -> Any:
        try:
            from dao.mysql.llm_model import get_llm_model_dao
        except ImportError:
            return None
        return get_llm_model_dao()

    async def list_models(
        self,
        *,
        active_only: bool = False,
        tenant_id: Optional[str] = None,
    ) -> List[LlmModelRow]:
        dao = self._dao()
        if dao is None:
            raise LlmModelRepositoryNotInstalledError(
                "_LegacyLlmModelRepository: "
                "dao.mysql.llm_model not importable; cannot list models"
            )
        # Real DAO accepts (active_only, tenant_id) positionally OR via
        # keyword.  Pass keyword to preserve the audited call shape.
        return list(
            await dao.list_models(
                active_only=active_only, tenant_id=tenant_id
            )
        )

    async def get_router_config(
        self,
        *,
        config_key: str = "default",
        tenant_id: Optional[str] = None,
    ) -> Optional[RouterLlmConfigRow]:
        dao = self._dao()
        if dao is None:
            raise LlmModelRepositoryNotInstalledError(
                "_LegacyLlmModelRepository: "
                "dao.mysql.llm_model not importable; "
                f"requested config_key={config_key!r}"
            )
        return await dao.get_router_config(
            config_key, tenant_id=tenant_id
        )


# ── In-memory LlmModelRepository for tests + SDK default ────────────────


class InMemoryLlmModelRepository:
    """LlmModelRepository impl for tests and SDK self-bundled default.

    Backed by two dicts — ``_models`` keyed by model id and
    ``_routers`` keyed by ``(tenant_id, config_key)``. All reads return
    deep copies so engine mutation does not leak.

    Concurrency: not strictly atomic across asyncio tasks — production
    multi-pod deployments must NOT share an in-memory repository.
    """

    def __init__(self) -> None:
        self._models: dict[str, LlmModelRow] = {}
        # Router configs keyed by (tenant_id_or_empty, config_key).
        self._routers: dict[tuple[str, str], RouterLlmConfigRow] = {}

    async def list_models(
        self,
        *,
        active_only: bool = False,
        tenant_id: Optional[str] = None,
    ) -> List[LlmModelRow]:
        rows: List[LlmModelRow] = []
        for r in self._models.values():
            row_tenant = getattr(r, "tenant_id", None)
            if tenant_id:
                # Match own tenant rows + global (NULL tenant) rows.
                if row_tenant not in (None, "", tenant_id):
                    continue
            if active_only and not bool(
                getattr(r, "is_active", True)
            ):
                continue
            rows.append(copy.deepcopy(r))
        # Mirror production DAO ORDER BY priority DESC.
        rows.sort(
            key=lambda r: -int(getattr(r, "priority", 0) or 0)
        )
        return rows

    async def get_router_config(
        self,
        *,
        config_key: str = "default",
        tenant_id: Optional[str] = None,
    ) -> Optional[RouterLlmConfigRow]:
        # Own-tenant entry wins over global (NULL tenant).
        if tenant_id:
            row = self._routers.get((tenant_id, config_key))
            if row is not None:
                return copy.deepcopy(row)
        global_row = self._routers.get(("", config_key))
        if global_row is None:
            return None
        return copy.deepcopy(global_row)

    # ── Test helpers (not part of the Protocol) ──────────────────

    def seed_model(self, row: LlmModelRow) -> None:
        rec_id = getattr(row, "id", "") or getattr(row, "config_key", "")
        if not rec_id:
            raise ValueError("seed_model requires id or config_key")
        try:
            row.id = rec_id
        except (AttributeError, TypeError):
            pass
        self._models[rec_id] = copy.deepcopy(row)

    def seed_router(self, row: RouterLlmConfigRow) -> None:
        ck = getattr(row, "config_key", "") or "default"
        tid = getattr(row, "tenant_id", None) or ""
        self._routers[(tid, ck)] = copy.deepcopy(row)

    def list_model_ids(self) -> List[str]:
        """Test helper: return all installed model ids.  Mirrors
        :meth:`InMemoryAgentRepository.list_ids` /
        :meth:`InMemoryApprovalRequestRepository.list_ids` /
        :meth:`InMemoryInboxRepository.list_ids` for symmetry across
        the Protocol family.  PR-E4c review feedback."""
        return list(self._models.keys())

    def clear(self) -> None:
        """Clear the in-memory store ONLY.  Does NOT uninstall the
        module-level singleton — to do that, call
        :func:`reset_llm_model_repository_for_test`."""
        self._models.clear()
        self._routers.clear()


__all__ = [
    "LlmModelRow",
    "RouterLlmConfigRow",
    "LlmModelRepository",
    "LlmModelRepositoryNotInstalledError",
    "InMemoryLlmModelRepository",
    "set_llm_model_repository",
    "get_llm_model_repository",
    "reset_llm_model_repository_for_test",
]
# ``_LegacyLlmModelRepository`` is intentionally NOT exported.
