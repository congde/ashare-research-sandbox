# -*- coding: utf-8 -*-
"""
SessionCache — PR-E*c of the Agent Engine SDK extraction plan.

See ``docs/Agent-Engine-SDK-剥离方案.md`` §5 PR-E*c.

Goal
----
Replace the engine layer's direct dependency on
``web.api.chat.cache.RedisCache`` (the ai-buddy-specific Redis session
queue + meta + pub/sub helper) with a Protocol-based seam. SDK
consumers install their own :class:`SessionCache` at boot; ai-buddy
installs an adapter that wraps ``web.api.chat.cache.RedisCache`` so
the existing engine code path is byte-identical.

Engine call sites today (all in two files) do::

    from web.api.chat.cache import RedisCache
    cache = RedisCache(session_id=session_id, qa_id=qa_id)
    await cache.session_queue.append_token(token, ttl=ttl)
    await cache.session_channel.publish_complete()
    await cache.session_meta.update_session_status(status, log, ttl=ttl)
    meta = await cache.session_meta.get_session_meta()
    count = await cache.session_queue.get_token_count()
    tokens = await cache.session_queue.get_tokens(start=start, end=end)

That import path is unreachable when the engine is packaged as the
SDK ``kucoin-agent-runtime-sdk`` (``web/`` is the business layer kept
out of the SDK).  PR-E*c introduces the abstraction.

Scope (V1)
----------
Two engine call sites:

* ``src/runtime/conversation/_resume.py`` — three sites that push HITL
  / rejection / continuation envelopes into the chat SSE stream and
  read back the original turn's ``extra_body`` from session meta.
* ``src/runtime/storage/mongo_backend.py`` — six sites inside
  ``_RedisStreamSink`` that fan out token writes, status updates,
  publish-complete signals, and meta/tokens reads.

Methods exposed
---------------
Engine code uses six coarse-grained verbs from the underlying
``RedisCache``; the Protocol surface mirrors them 1:1:

* :meth:`SessionCache.append_token` — push a token into the SSE queue
* :meth:`SessionCache.update_session_status` — update status + log
* :meth:`SessionCache.publish_complete` — pub/sub completion signal
* :meth:`SessionCache.get_session_meta` — read meta hash
* :meth:`SessionCache.get_token_count` — list length of queued tokens
* :meth:`SessionCache.get_tokens` — slice of queued tokens

All methods take ``session_id`` + ``qa_id`` as keyword arguments —
the underlying RedisCache class is constructed per-call inside the
adapter; engine code never sees the instance.

Fall-back path (PR-E*c only; deleted in Phase 2)
------------------------------------------------
When no provider is installed via :func:`set_session_cache`,
:func:`get_session_cache` lazily synthesises one that wraps
``web.api.chat.cache.RedisCache``.  This makes PR-E*c a
zero-behaviour-change refactor for ai-buddy's current boot path.
SDK consumers (Phase 2) MUST call ``set_session_cache(...)`` at boot
before any engine path runs.

Same pattern as PR-E4 :class:`CostRecordRepository`, PR-E4b
:class:`AgentRepository`, and PR-E4c :class:`InboxRepository`.
"""

from __future__ import annotations

import asyncio
import copy
import logging
from collections import defaultdict
from typing import Any, List, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


class SessionCacheNotInstalledError(RuntimeError):
    """Raised when :func:`get_session_cache` is called before any
    cache is installed AND the legacy ``web.api.chat.cache.RedisCache``
    fallback is not reachable.

    SDK consumers (Phase 2 onwards) MUST call
    ``set_session_cache(cache)`` during boot before any engine module
    runs.
    """


@runtime_checkable
class SessionCache(Protocol):
    """Pluggable cache for chat session SSE-stream coordination.

    The shape mirrors the six verbs used by engine code today.  All
    methods are scoped to ``(session_id, qa_id)`` — implementations
    construct per-call backend state without exposing the underlying
    Redis / in-memory primitive.

    Implementations MUST be safe to call concurrently from asyncio
    tasks — the HITL resume path and the production chat fan-out both
    write into the same session queue from different coroutines.
    """

    async def append_token(
        self,
        *,
        session_id: str,
        qa_id: str,
        token: str,
        ttl: int = 600,
    ) -> Optional[int]:
        """Append a single SSE token to the session queue.

        Returns the queue length after the push when the underlying
        store exposes it; otherwise ``None`` (production RedisCache
        intentionally returns ``None`` since its ``append_token`` does
        not surface ``LLEN``).
        """
        ...

    async def update_session_status(
        self,
        *,
        session_id: str,
        qa_id: str,
        status: str,
        log: str = "",
        ttl: int = 600,
    ) -> None:
        """Update the session status (and optional log) on the meta hash."""
        ...

    async def publish_complete(
        self,
        *,
        session_id: str,
        qa_id: str,
    ) -> None:
        """Publish a completion signal on the session pub/sub channel."""
        ...

    async def get_session_meta(
        self,
        *,
        session_id: str,
        qa_id: str,
    ) -> Optional[dict]:
        """Return the session meta hash, or ``None`` when absent.

        The shape mirrors the Redis ``HGETALL`` result — values MAY be
        ``bytes`` (real Redis client) or ``str`` (some adapters).
        Engine call sites already defend against both.
        """
        ...

    async def get_token_count(
        self,
        *,
        session_id: str,
        qa_id: str,
    ) -> int:
        """Return the current queue length (``LLEN`` semantics)."""
        ...

    async def get_tokens(
        self,
        *,
        session_id: str,
        qa_id: str,
        start: int = 0,
        end: int = -1,
    ) -> List[Any]:
        """Return a slice of queued tokens (``LRANGE`` semantics)."""
        ...


# ── Module-level singleton ──────────────────────────────────────────────


_session_cache: Optional[SessionCache] = None


def set_session_cache(cache: SessionCache) -> None:
    """Install the SessionCache used by engine modules.

    Idempotent — subsequent calls overwrite. Logs at INFO so boot
    order is auditable. **Never** logs the cache contents — session
    meta carries operator ``query`` strings and the queue holds raw
    SSE token payloads.

    Raises:
        TypeError: when ``cache`` does not satisfy the
            :class:`SessionCache` Protocol at the structural level.
    """
    if not isinstance(cache, SessionCache):
        raise TypeError(
            "set_session_cache: cache must satisfy SessionCache Protocol "
            "(append_token / update_session_status / publish_complete / "
            "get_session_meta / get_token_count / get_tokens), "
            f"got {type(cache).__name__}"
        )
    global _session_cache
    _session_cache = cache
    logger.info("SessionCache installed: %s", type(cache).__name__)


def get_session_cache() -> SessionCache:
    """Return the installed cache, falling back to a lazy adapter
    that wraps ``web.api.chat.cache.RedisCache`` when no explicit
    cache is installed.

    The fall-back is PR-E*c-only and will be deleted in Phase 2 of
    the SDK extraction plan. SDK consumers MUST install a cache at
    boot.

    Raises:
        SessionCacheNotInstalledError: when no cache is installed
            AND ``web.api.chat.cache`` is not importable.
    """
    if _session_cache is not None:
        return _session_cache

    try:
        import importlib
        importlib.import_module("web.api.chat.cache")
    except ImportError as exc:
        raise SessionCacheNotInstalledError(
            "SessionCache has not been installed and "
            "web.api.chat.cache is not importable. Call "
            "set_session_cache(cache) at boot before any "
            "engine code path runs."
        ) from exc

    return _LegacyRedisSessionCache.get_singleton()


def reset_session_cache_for_test() -> None:
    """Test-only helper to clear the installed cache between cases.

    NOT for production use.
    """
    global _session_cache
    _session_cache = None
    _LegacyRedisSessionCache.reset_singleton_for_test()


# ── Legacy RedisCache adapter (fallback) ────────────────────────────────


class _LegacyRedisSessionCache:
    """Adapter that exposes the legacy
    ``web.api.chat.cache.RedisCache`` (the production Redis-backed
    session helper in ai-buddy) via the :class:`SessionCache` Protocol.

    Lazy ``RedisCache`` lookup inside every method so the adapter
    survives early-boot scenarios where ``component.get("redis")``
    has not yet been wired.
    """

    _SINGLETON: Optional["_LegacyRedisSessionCache"] = None

    @classmethod
    def get_singleton(cls) -> "_LegacyRedisSessionCache":
        if cls._SINGLETON is None:
            cls._SINGLETON = cls()
        return cls._SINGLETON

    @classmethod
    def reset_singleton_for_test(cls) -> None:
        cls._SINGLETON = None

    @staticmethod
    def _build(session_id: str, qa_id: str) -> Any:
        # Lazy import — running the engine without web/ on the path
        # raises SessionCacheNotInstalledError up at get_session_cache,
        # so this branch is only reached when the import succeeded once.
        from web.api.chat.cache import RedisCache  # type: ignore
        return RedisCache(session_id=session_id, qa_id=qa_id)

    async def append_token(
        self,
        *,
        session_id: str,
        qa_id: str,
        token: str,
        ttl: int = 600,
    ) -> Optional[int]:
        cache = self._build(session_id, qa_id)
        return await cache.session_queue.append_token(token, ttl=ttl)

    async def update_session_status(
        self,
        *,
        session_id: str,
        qa_id: str,
        status: str,
        log: str = "",
        ttl: int = 600,
    ) -> None:
        cache = self._build(session_id, qa_id)
        await cache.session_meta.update_session_status(status, log, ttl=ttl)

    async def publish_complete(
        self,
        *,
        session_id: str,
        qa_id: str,
    ) -> None:
        cache = self._build(session_id, qa_id)
        await cache.session_channel.publish_complete()

    async def get_session_meta(
        self,
        *,
        session_id: str,
        qa_id: str,
    ) -> Optional[dict]:
        cache = self._build(session_id, qa_id)
        return await cache.session_meta.get_session_meta()

    async def get_token_count(
        self,
        *,
        session_id: str,
        qa_id: str,
    ) -> int:
        cache = self._build(session_id, qa_id)
        return await cache.session_queue.get_token_count()

    async def get_tokens(
        self,
        *,
        session_id: str,
        qa_id: str,
        start: int = 0,
        end: int = -1,
    ) -> List[Any]:
        cache = self._build(session_id, qa_id)
        return await cache.session_queue.get_tokens(start=start, end=end)


# ── In-memory SessionCache for tests + SDK default ──────────────────────


class InMemorySessionCache:
    """SessionCache impl for tests and SDK self-bundled default.

    Backed by per-``(session_id, qa_id)`` dicts (meta) + lists
    (tokens). No real pub/sub; ``publish_complete`` records the call
    so tests can assert it fired.

    Concurrency: methods take an asyncio.Lock per key — safe for
    interleaved coroutines in a single process. Production multi-pod
    deployments must NOT share an in-memory cache.
    """

    def __init__(self) -> None:
        self._meta: dict[tuple[str, str], dict[str, Any]] = {}
        self._tokens: dict[tuple[str, str], list[str]] = defaultdict(list)
        self._complete_events: list[tuple[str, str]] = []
        self._lock: defaultdict[tuple[str, str], asyncio.Lock] = defaultdict(asyncio.Lock)

    def _key(self, session_id: str, qa_id: str) -> tuple[str, str]:
        return (session_id, qa_id)

    async def append_token(
        self,
        *,
        session_id: str,
        qa_id: str,
        token: str,
        ttl: int = 600,
    ) -> Optional[int]:
        key = self._key(session_id, qa_id)
        async with self._lock[key]:
            self._tokens[key].append(token)
            return len(self._tokens[key])

    async def update_session_status(
        self,
        *,
        session_id: str,
        qa_id: str,
        status: str,
        log: str = "",
        ttl: int = 600,
    ) -> None:
        key = self._key(session_id, qa_id)
        async with self._lock[key]:
            meta = self._meta.setdefault(key, {})
            meta["status"] = status
            if log:
                meta["log"] = log

    async def publish_complete(
        self,
        *,
        session_id: str,
        qa_id: str,
    ) -> None:
        self._complete_events.append(self._key(session_id, qa_id))

    async def get_session_meta(
        self,
        *,
        session_id: str,
        qa_id: str,
    ) -> Optional[dict]:
        key = self._key(session_id, qa_id)
        meta = self._meta.get(key)
        if meta is None:
            return None
        return copy.deepcopy(meta)

    async def get_token_count(
        self,
        *,
        session_id: str,
        qa_id: str,
    ) -> int:
        return len(self._tokens.get(self._key(session_id, qa_id), []))

    async def get_tokens(
        self,
        *,
        session_id: str,
        qa_id: str,
        start: int = 0,
        end: int = -1,
    ) -> List[Any]:
        toks = list(self._tokens.get(self._key(session_id, qa_id), []))
        # Mirror Redis LRANGE semantics: inclusive end; -1 means "to end".
        if end == -1:
            slice_end: Optional[int] = None
        else:
            slice_end = end + 1
        return toks[start:slice_end]

    # ── Test helpers (not part of the Protocol) ──────────────────

    def seed_meta(
        self,
        *,
        session_id: str,
        qa_id: str,
        meta: dict[str, Any],
    ) -> None:
        self._meta[self._key(session_id, qa_id)] = dict(meta)

    def complete_events(self) -> list[tuple[str, str]]:
        return list(self._complete_events)

    def clear(self) -> None:
        self._meta.clear()
        self._tokens.clear()
        self._complete_events.clear()


__all__ = [
    "SessionCache",
    "SessionCacheNotInstalledError",
    "InMemorySessionCache",
    "set_session_cache",
    "get_session_cache",
    "reset_session_cache_for_test",
]
# ``_LegacyRedisSessionCache`` is intentionally NOT exported.
