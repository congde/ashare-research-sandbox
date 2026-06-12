# -*- coding: utf-8 -*-
"""
get_storage_backend(backend="auto"|"mongo"|"sqlite") — selector for
``ConversationRuntime``'s ``StorageBackend`` injection.

Sprint 0 PR-A (docs/TUI-Web-Runtime同构化技术方案.md §A2).

This file ONLY ships the selector + auto-detect logic. The actual
``MongoStorageBackend`` and ``SqliteStorageBackend`` implementations
ride in PR-B and PR-C respectively. Calling ``get_storage_backend``
in PR-A's scope returns ``NotImplementedError`` for both backend
flavours — Sprint 1 PR-E is when ``ConversationRuntime`` starts
calling this; until then, the function exists for IMPORT discovery
(downstream code can ``from runtime.storage import get_storage_backend``
without crashing).

Auto-detection priority (when ``backend="auto"``)
-------------------------------------------------
Same pattern as ``get_persistent_worker_backend`` in
``runtime.config.toggles`` (the proven precedent the plan cites):

1. **Environment override**: ``RUNTIME__STORAGE_BACKEND=mongo|sqlite``
   wins over auto-detect — operator pin for CI, single-tenant pods, etc.
2. **CLI / TUI / daemon contexts**: ``ENVIRONMENT in {"cli","tui","daemon"}``
   → SQLite. Local-first commitment; daemon must not depend on Mongo.
3. **Mongo reachable within 200 ms**: probe ``ai_assistant_db`` admin
   ping → Mongo. Web/HTTP path almost always lands here.
4. **Fallback**: SQLite. Better to degrade to local sqlite than fail
   boot when Mongo is briefly down.

Sprint 1 PR-E will start calling this from ``ConversationRuntime``
construction. Sprint 0 PR-A's purpose: lock the contract so PR-B / PR-C
can implement against a stable interface.
"""

from __future__ import annotations

import logging
import os
from typing import Literal

from vendor_runtime_sdk.runtime.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


_BackendName = Literal["auto", "mongo", "sqlite"]


def _resolve_backend_choice(backend: _BackendName) -> Literal["mongo", "sqlite"]:
    """Resolve an explicit ``"mongo"`` / ``"sqlite"`` from the user-
    supplied ``"auto"`` sentinel.

    Sprint 0: the auto-detect ladder is fully implemented at the
    selector level, but the backend constructors (``MongoStorageBackend``
    / ``SqliteStorageBackend``) don't exist yet — both return
    ``NotImplementedError`` in this PR. The ladder is finalized here so
    PR-B / PR-C can land their constructors without touching factory
    logic.
    """
    # Step 1 — Explicit operator pin via env var beats everything.
    env_override = os.environ.get("RUNTIME__STORAGE_BACKEND", "").strip().lower()
    if env_override in ("mongo", "sqlite"):
        if backend != "auto" and backend != env_override:
            logger.warning(
                "get_storage_backend: caller asked for %r but env override is %r — "
                "honouring env override (operator pin wins)",
                backend, env_override,
            )
        return env_override  # type: ignore[return-value]

    # Step 2 — Caller-explicit pin.
    if backend == "mongo":
        return "mongo"
    if backend == "sqlite":
        return "sqlite"

    # Step 3 — CLI / TUI / daemon → SQLite (local-first commitment).
    environment = os.environ.get("ENVIRONMENT", "").strip().lower()
    if environment in ("cli", "tui", "daemon"):
        logger.debug(
            "get_storage_backend: ENVIRONMENT=%s → sqlite (local-first)",
            environment,
        )
        return "sqlite"

    # Step 4 — Mongo reachable probe. Sprint 0 stub: defer the probe to
    # PR-B (which actually has a Mongo backend to call). For now,
    # if we got here from "auto" without env override, default to
    # mongo (matches current Web behaviour — the only thing
    # ConversationRuntime knows today).
    return "mongo"


def get_storage_backend(backend: _BackendName = "auto") -> StorageBackend:
    """Return a fully wired ``StorageBackend`` for the current runtime
    context.

    Args:
        backend: ``"auto"`` (default) auto-detects per the ladder above;
            ``"mongo"`` / ``"sqlite"`` force an explicit choice.

    Raises:
        NotImplementedError: in Sprint 0 PR-A the concrete backend
            classes haven't been written. The factory exists so
            ``ConversationRuntime``'s import chain can resolve and
            type-check the call site; the actual call only fires after
            Sprint 1 PR-E flips ``ConversationRuntime`` to use the
            backend.
    """
    chosen = _resolve_backend_choice(backend)
    if chosen == "mongo":
        from vendor_runtime_sdk.runtime.storage.mongo_backend import MongoStorageBackend
        return MongoStorageBackend()
    if chosen == "sqlite":
        # PR-C lands ``SqliteStorageBackend`` — wraps the existing
        # ``cli/adapters/storage_sqlite.py:SqliteStorage`` (5/5 DAO
        # Protocols, verified in docs/Sprint0-Pre-work-报告.md §1) plus
        # the 4 new sub-protocols (HitlGate / Artifact / StreamSink /
        # RegistryStore). db_path resolution lives inside the constructor:
        # explicit kwarg → AIBUDDY_RUNTIME_DB env → ~/.aibuddy/runtime.db.
        from vendor_runtime_sdk.runtime.storage.sqlite_backend import SqliteStorageBackend
        return SqliteStorageBackend()
    # Unreachable — _resolve_backend_choice returns Literal["mongo","sqlite"]
    raise RuntimeError(f"get_storage_backend: unexpected choice={chosen!r}")


__all__ = ["get_storage_backend"]
