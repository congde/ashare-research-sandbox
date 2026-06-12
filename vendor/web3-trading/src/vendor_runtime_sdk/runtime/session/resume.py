"""
Session Resume — 断点续跑 (§5.5)

Restores a Session from MongoDB-persisted state.
On resume, validates that referenced resources still exist (fail-closed semantics):
  - agent_version: must exist (append-only; missing → DataCorruptionError)
  - tool_schemas_sha256: drift → ToolSchemaDriftError
  - environment env_vars: drift → EnvironmentDriftError
  - memory_stores: missing/archived → downgrade with WARN (not fail-closed)

Configuration-deterministic recovery — we restore the *config* that was
in effect at session creation, not a full replay of every message.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# ── Errors ─────────────────────────────────────────────────────────────────────


class ResumeError(Exception):
    """Base class for all session resume failures."""


class DataCorruptionError(ResumeError):
    """
    agent_version record is missing from the append-only table.
    This indicates data corruption; automatic fallback is forbidden.
    """


class ToolSchemaDriftError(ResumeError):
    """
    The tool schemas have changed since the session was created.
    Resuming with a different tool contract could corrupt the conversation.
    """


class EnvironmentDriftError(ResumeError):
    """
    The runtime environment has drifted (env_vars changed or env deleted).
    Fail-closed to prevent non-deterministic replay.
    """


# ── Helpers ────────────────────────────────────────────────────────────────────


def _canonical_json(obj) -> str:
    """Deterministic JSON: keys sorted, no spaces."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


def compute_tool_schemas_sha256(tool_schemas: list[dict]) -> str:
    """
    Compute the canonical fingerprint for a list of tool schemas.

    Uses key-sorted, whitespace-free JSON to ensure deterministic hashing
    regardless of dict insertion order.
    """
    canonical = _canonical_json(tool_schemas)
    return _sha256(canonical)


def compute_env_vars_sha256(env_vars: dict) -> str:
    """
    Compute the fingerprint for an env_vars dict.

    Only the hash is stored in the session snapshot — never the raw values.
    """
    canonical = _canonical_json(env_vars)
    return _sha256(canonical)


# ── Resume context ──────────────────────────────────────────────────────────────


@dataclass
class ResumedConfig:
    """
    The agent configuration successfully restored for a resumed session.

    Callers use this to rebuild the ConversationRuntime with the same
    parameters that were in effect when the session was originally created.
    """

    session_id: str
    agent_version_id: str
    agent_config: dict  # full agent_version.config
    environment_config: Optional[dict]  # creation_snapshot.environment_config (structural)
    active_memory_store_ids: list[str]  # only non-archived stores


# ── Resume logic ───────────────────────────────────────────────────────────────


class SessionResume:
    """
    Implements the §5.5.2 resume flow with fail-closed validation.

    In production this class is injected with live DAO objects; in tests
    you pass lightweight dicts directly.

    Parameters
    ----------
    session_doc : dict
        The MongoDB document from the ``sessions`` collection.
    agent_version_db : dict[str, dict]
        Mapping of agent_version_id → agent_version document.
        (In production: a live DAO call; kept as a dict here for testability.)
    live_tool_schemas : list[dict] | None
        The tool schemas compiled at the moment of resume.  If supplied,
        drift detection runs against the saved ``tool_schemas_sha256``.
    live_environment : dict | None
        The live environment document, used for env_vars drift detection.
    memory_store_db : dict[str, dict]
        Mapping of store_id → memory_store document (or None = missing).
    """

    def __init__(
        self,
        session_doc: dict,
        agent_version_db: dict[str, dict],
        live_tool_schemas: Optional[list[dict]] = None,
        live_environment: Optional[dict] = None,
        memory_store_db: Optional[dict[str, dict]] = None,
    ):
        self._doc = session_doc
        self._agent_version_db = agent_version_db
        self._live_tool_schemas = live_tool_schemas
        self._live_environment = live_environment
        self._memory_store_db = memory_store_db or {}

    def resume(self) -> ResumedConfig:
        """
        Validate and restore the session config.

        Raises
        ------
        DataCorruptionError
            The agent_version record is missing (append-only table).
        ToolSchemaDriftError
            Tool schemas have changed since session creation.
        EnvironmentDriftError
            Environment env_vars have changed or the environment was deleted.

        Returns
        -------
        ResumedConfig
            The restored agent configuration, ready to re-build the runtime.
        """
        session_id = self._doc.get("_id") or self._doc.get("session_id", "<unknown>")

        # ── Step 1: Agent version (append-only — must exist) ──────────────────
        agent_version_id = self._doc.get("agent_version_id")
        agent_config = self._agent_version_db.get(str(agent_version_id))

        if agent_config is None:
            raise DataCorruptionError(
                f"Immutable agent_version '{agent_version_id}' not found for session "
                f"'{session_id}'. Append-only record missing indicates data corruption. "
                f"Refusing to resume — manual investigation required."
            )

        # ── Step 1.5: Tool schema drift detection ─────────────────────────────
        snapshot = self._doc.get("creation_snapshot") or {}
        snap_agent = snapshot.get("agent_config") or {}
        saved_tool_hash: Optional[str] = snap_agent.get("tool_schemas_sha256")

        if saved_tool_hash and self._live_tool_schemas is not None:
            live_hash = compute_tool_schemas_sha256(self._live_tool_schemas)
            if live_hash != saved_tool_hash:
                raise ToolSchemaDriftError(
                    f"Tool schema drift detected for session '{session_id}': "
                    f"saved={saved_tool_hash[:8]!r}, live={live_hash[:8]!r}. "
                    f"Refusing to resume — manual review required."
                )

        # ── Step 2: Environment — structural snapshot + env_vars drift check ──
        env_config: Optional[dict] = snapshot.get("environment_config")
        saved_env_hash: Optional[str] = None
        if env_config:
            saved_env_hash = env_config.get("env_vars_sha256")

        if saved_env_hash:
            if self._live_environment is None:
                raise EnvironmentDriftError(
                    f"Environment '{self._doc.get('environment_id')}' was deleted for "
                    f"session '{session_id}', cannot verify env_vars integrity. "
                    f"Refusing to resume."
                )
            live_env_vars = self._live_environment.get("env_vars") or {}
            live_env_hash = compute_env_vars_sha256(live_env_vars)
            if live_env_hash != saved_env_hash:
                raise EnvironmentDriftError(
                    f"env_vars drift detected for session '{session_id}': "
                    f"saved={saved_env_hash[:8]!r}, live={live_env_hash[:8]!r}. "
                    f"Refusing to resume — manual review required."
                )

        # ── Step 3: Memory stores — downgrade on missing/archived (not fatal) ──
        memory_store_ids: list[str] = self._doc.get("memory_store_ids") or []
        active_stores: list[str] = []

        for store_id in memory_store_ids:
            store = self._memory_store_db.get(str(store_id))
            if store and store.get("archived_at") is None:
                active_stores.append(str(store_id))
            else:
                logger.warning(
                    "MemoryStore '%s' unavailable at resume for session '%s', skipping",
                    store_id,
                    session_id,
                )

        # ── Step 4: Return fully validated config ─────────────────────────────
        return ResumedConfig(
            session_id=str(session_id),
            agent_version_id=str(agent_version_id),
            agent_config=agent_config,
            environment_config=env_config,
            active_memory_store_ids=active_stores,
        )
