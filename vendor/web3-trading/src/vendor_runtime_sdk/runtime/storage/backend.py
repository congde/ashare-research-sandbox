# -*- coding: utf-8 -*-
"""
StorageBackend Protocol — passive composition container.

Sprint 0 PR-A (docs/TUI-Web-Runtime同构化技术方案.md §A2).

Aggregates the 9 sub-Protocols a ``ConversationRuntime`` needs in one
place so callers inject ONE backend handle rather than 9 separate
DAOs. The actual implementations (``MongoStorageBackend``,
``SqliteStorageBackend``) land in PR-B / PR-C.

Composition rules
-----------------
* All 9 fields are read-only attributes (the Protocol declares them as
  attributes, not methods, so backends can wire them up however they
  like — typically as immutable instance fields populated in
  ``__init__``).
* The ``name`` field identifies the backend choice at runtime (Mongo
  vs SQLite) for telemetry / log tags / fail-closed interlocks.
* No method on the backend itself — composition only. Each sub-
  Protocol carries its own methods.

Why composition over inheritance
--------------------------------
Mongo and SQLite backends share NOTHING (different DBs, different
serialization, different lifecycle). Inheritance would force a
Liskov-violating shared base. Composition lets each backend wire its
9 children independently, and the tests can assert against the
Protocol surface alone (``isinstance(backend, StorageBackend)`` works
via ``runtime_checkable``).
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

# v0.1.1 SDK extraction patch: dao.protocols is an ai-buddy business
# layer module; pure SDK consumers may not have it.  Guard with None
# fallbacks so module load succeeds.  Phase 2 migrates these to
# runtime.protocols.* (mirrors PR-E4 Repository pattern).
try:
    from dao.protocols import (
        ArtifactStore,
        CoordinatorThreadRepository,
        CostRepository,
        HitlGateRepository,
        MemoryRepository,
        QARepository,
        SessionRepository,
    )
except ImportError:
    ArtifactStore = None  # type: ignore[assignment,misc]
    CoordinatorThreadRepository = None  # type: ignore[assignment,misc]
    CostRepository = None  # type: ignore[assignment,misc]
    HitlGateRepository = None  # type: ignore[assignment,misc]
    MemoryRepository = None  # type: ignore[assignment,misc]
    QARepository = None  # type: ignore[assignment,misc]
    SessionRepository = None  # type: ignore[assignment,misc]
from vendor_runtime_sdk.runtime.cache.registry_store import RegistryStore
from vendor_runtime_sdk.runtime.storage.stream_sink import StreamSink


@runtime_checkable
class StorageBackend(Protocol):
    """Composition of the 9 sub-Protocols ``ConversationRuntime`` needs.

    Field naming intentionally lowercased + snake_case so call sites
    read naturally: ``self._storage.sessions.get_session(...)``,
    ``self._storage.hitl_gates.save_pending(...)``,
    ``self._storage.stream_sink.append_token(...)``.
    """

    # ── DAO Protocols (defined in dao/protocols.py) ───────────────────────
    sessions: SessionRepository
    qa: QARepository
    memory: MemoryRepository
    cost: CostRepository
    coordinator_threads: CoordinatorThreadRepository
    hitl_gates: HitlGateRepository
    artifacts: ArtifactStore

    # ── Runtime-layer protocols ───────────────────────────────────────────
    stream_sink: StreamSink
    registry_store: RegistryStore

    # ── Identity ──────────────────────────────────────────────────────────
    name: Literal["mongo", "sqlite"]
    """Backend tag for telemetry / interlock checks.

    Used by:
    * ``validate_runtime_interlocks`` to refuse boot when
      ``ENVIRONMENT=cli`` + ``name=mongo`` (CLI shouldn't connect to
      production Mongo).
    * SpanEvent metadata so the dashboard can partition runtime metrics
      by backend.
    * ``logger.info("ConversationRuntime[%s]: backend=%s", ...)``
      diagnostic lines.
    """
