"""RegistryStore — pluggable snapshot backend for the live runtime registry.

See ``docs/服务端数据本地化整改技术方案.md`` §3.1.

Two implementations:

* ``InProcessRegistryStore`` — legacy behavior: snapshots live in a module-level
  ``dict[str, dict]`` scoped to the current Python process. Used when the
  ``registry_redis`` toggle is OFF. Returns ``None`` cross-pod — the frontend
  retrying on the "wrong" pod sees 404.

* ``RedisRegistryStore`` — snapshots written to Redis at
  ``ws:{workspace_id}:runtime:snapshot:{session_id}`` with 30-minute TTL.
  Multi-replica deployments can fetch the snapshot from any pod.

Both expose the same interface, selected at module init via
:func:`get_registry_store()`. A note on semantics:

*The store holds SNAPSHOTS (plain JSON dicts), not live ``ConversationRuntime``
instances.* Cross-pod lifecycle actions (cancel, nudge) still require the
caller to be on the pod that owns the session — those are orchestrated
via pod-routing in the load balancer (sticky sessions) or explicit RPC.

The live-instance registry in ``runtime.conversation._RUNTIME_REGISTRY`` is
preserved in-process for actions; this module is specifically for the
read-side snapshot endpoint.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from vendor_runtime_sdk.runtime.config.toggles import get_toggles

logger = logging.getLogger(__name__)

__all__ = [
    "RegistryStore",
    "InProcessRegistryStore",
    "RedisRegistryStore",
    "get_registry_store",
    "reset_registry_store",
]

_SNAPSHOT_TTL_SECONDS = 1800  # 30 minutes — matches plan §3.1


class RegistryStore(Protocol):
    """Protocol for the snapshot persistence backend."""

    async def put_snapshot(
        self,
        session_id: str,
        workspace_id: str,
        snapshot: dict[str, Any],
    ) -> None: ...

    async def get_snapshot(
        self,
        session_id: str,
        workspace_id: str | None = None,
    ) -> dict[str, Any] | None: ...

    async def delete_snapshot(
        self,
        session_id: str,
        workspace_id: str | None = None,
    ) -> None: ...


# ── In-process implementation (legacy baseline) ───────────────────────────────

class InProcessRegistryStore:
    """Module-local snapshot dict. Single-pod visibility only."""

    def __init__(self) -> None:
        self._snapshots: dict[str, dict[str, Any]] = {}

    async def put_snapshot(
        self,
        session_id: str,
        workspace_id: str,
        snapshot: dict[str, Any],
    ) -> None:
        if not session_id:
            return
        self._snapshots[session_id] = snapshot

    async def get_snapshot(
        self,
        session_id: str,
        workspace_id: str | None = None,
    ) -> dict[str, Any] | None:
        return self._snapshots.get(session_id)

    async def delete_snapshot(
        self,
        session_id: str,
        workspace_id: str | None = None,
    ) -> None:
        self._snapshots.pop(session_id, None)


# ── Redis implementation ─────────────────────────────────────────────────────

def _snapshot_key(workspace_id: str, session_id: str) -> str:
    """Build the Redis key for the snapshot. Bypasses the thread-local
    ownership resolver in ``redis_keys.ws_key`` because this function is
    called from background threads (checkpoint writers) where the context
    var is not populated; workspace_id is passed in explicitly."""
    if not workspace_id or workspace_id.lower() in {"global", "default", "none"}:
        raise ValueError(
            f"RedisRegistryStore snapshot key requires a real workspace_id, got {workspace_id!r}"
        )
    if not session_id:
        raise ValueError("RedisRegistryStore snapshot key requires a session_id")
    return f"ws:{workspace_id}:runtime:snapshot:{session_id}"


class RedisRegistryStore:
    """Persist snapshots in Redis. Fail-soft on any Redis error — the
    in-flight turn must not abort because the snapshot backend is down.
    """

    def __init__(self, redis_client: Any, *, ttl_seconds: int = _SNAPSHOT_TTL_SECONDS) -> None:
        self._redis = redis_client
        self._ttl = int(ttl_seconds)

    async def put_snapshot(
        self,
        session_id: str,
        workspace_id: str,
        snapshot: dict[str, Any],
    ) -> None:
        if not session_id:
            return
        try:
            key = _snapshot_key(workspace_id, session_id)
            payload = json.dumps(snapshot, default=_json_default, ensure_ascii=False)
            await _maybe_await(self._redis.set(key, payload, ex=self._ttl))
        except Exception as exc:
            logger.warning(
                "RedisRegistryStore.put_snapshot failed for session=%s workspace=%s: %s",
                session_id,
                workspace_id,
                exc,
            )

    async def get_snapshot(
        self,
        session_id: str,
        workspace_id: str | None = None,
    ) -> dict[str, Any] | None:
        if not session_id:
            return None
        if not workspace_id:
            # Without workspace_id we cannot build the key — callers must pass
            # it through. Return None (soft-miss) rather than raising so the
            # management endpoint can fall back to in-process lookup.
            logger.debug(
                "RedisRegistryStore.get_snapshot: workspace_id missing for session=%s — soft miss",
                session_id,
            )
            return None
        try:
            key = _snapshot_key(workspace_id, session_id)
            raw = await _maybe_await(self._redis.get(key))
            if not raw:
                return None
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            return json.loads(raw)
        except Exception as exc:
            logger.warning(
                "RedisRegistryStore.get_snapshot failed for session=%s: %s",
                session_id,
                exc,
            )
            return None

    async def delete_snapshot(
        self,
        session_id: str,
        workspace_id: str | None = None,
    ) -> None:
        if not session_id or not workspace_id:
            return
        try:
            key = _snapshot_key(workspace_id, session_id)
            await _maybe_await(self._redis.delete(key))
        except Exception as exc:
            logger.warning(
                "RedisRegistryStore.delete_snapshot failed for session=%s: %s",
                session_id,
                exc,
            )


# ── Factory / singleton ──────────────────────────────────────────────────────

_STORE_SINGLETON: RegistryStore | None = None


def get_registry_store() -> RegistryStore:
    """Return the process-wide RegistryStore singleton.

    Selection rule:
      * ``registry_redis`` toggle on + redis client obtainable → RedisRegistryStore
      * otherwise                                               → InProcessRegistryStore
    """
    global _STORE_SINGLETON
    if _STORE_SINGLETON is not None:
        return _STORE_SINGLETON

    toggles = get_toggles()
    if toggles.is_enabled("registry_redis"):
        redis_client = _try_get_redis_client()
        if redis_client is not None:
            logger.info("RegistryStore: using RedisRegistryStore (registry_redis=on)")
            _STORE_SINGLETON = RedisRegistryStore(redis_client)
            return _STORE_SINGLETON
        logger.warning(
            "RegistryStore: registry_redis=on but redis client unavailable; "
            "falling back to InProcessRegistryStore"
        )

    _STORE_SINGLETON = InProcessRegistryStore()
    return _STORE_SINGLETON


def reset_registry_store() -> None:
    """Clear the cached singleton — primarily for tests."""
    global _STORE_SINGLETON
    _STORE_SINGLETON = None


_COMPONENT_SERVICE_SINGLETON: Any | None = None


def _try_get_redis_client() -> Any | None:
    """Pull the async redis client from the ComponentService. Returns None on
    any failure so the caller can fall back gracefully.

    The ``ComponentService`` instance is cached across calls — some
    implementations of ComponentService do expensive init on construction
    (Eureka/Apollo client setup), and while :func:`get_registry_store` only
    invokes this once per process today, a tests-scoped :func:`reset_registry_store`
    call otherwise re-pays the construction cost on every reset.
    """
    global _COMPONENT_SERVICE_SINGLETON
    try:
        if _COMPONENT_SERVICE_SINGLETON is None:
            from web.component import ComponentService
            _COMPONENT_SERVICE_SINGLETON = ComponentService()
        svc = _COMPONENT_SERVICE_SINGLETON
        redis_component = svc.get("redis") if hasattr(svc, "get") else None
        if redis_component is None:
            return None
        # Prefer ``.client`` attribute (async client) per repo convention,
        # falling back to the component itself if it acts as a client.
        return getattr(redis_component, "client", redis_component)
    except Exception as exc:
        logger.debug("RegistryStore: redis client lookup failed: %s", exc)
        return None


async def _maybe_await(result: Any) -> Any:
    """Tolerate sync-or-async redis clients. ``redis.asyncio`` returns an
    awaitable; the sync shim used in CLI / tests returns a plain value."""
    if hasattr(result, "__await__"):
        return await result
    return result


def _json_default(obj: Any) -> Any:
    """JSON fallback for non-standard types we may store in a snapshot."""
    # datetime-ish objects
    if hasattr(obj, "isoformat"):
        try:
            return obj.isoformat()
        except Exception:
            pass
    # Enum
    if hasattr(obj, "value") and hasattr(obj, "name"):
        return obj.value
    # sets / frozensets
    if isinstance(obj, (set, frozenset)):
        return list(obj)
    return str(obj)
