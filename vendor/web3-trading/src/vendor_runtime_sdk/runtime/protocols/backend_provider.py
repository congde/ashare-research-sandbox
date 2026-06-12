# -*- coding: utf-8 -*-
"""
BackendClientProvider — PR-E5 of the Agent Engine SDK extraction plan.

See ``docs/Agent-Engine-SDK-剥离方案.md`` §5 Phase 0 PR-E5.

Goal
----
Replace the engine layer's direct dependency on ``web.component.
ComponentService`` (the ai-buddy-specific service container) with a
Protocol-based seam. SDK consumers install their own provider at boot;
ai-buddy installs an adapter that wraps ``ComponentService`` so the
existing engine code path is byte-identical.

Today every engine call site that needs the Mongo motor client or the
Redis client does::

    from web.component import component
    redis = await component.get("redis").get_client          # Group A pattern
    mongo = await component.get("mongo").get_client          # Group A pattern
    # or:
    svc = ComponentService(); db = svc.mongodb; r = svc.redis  # Group B pattern
                                                              # (Celery workers)

That import path is unreachable when the engine is packaged as the SDK
:mod:`kucoin-agent-runtime-sdk` (``web/`` is the business layer, kept
outside the SDK). PR-E5 introduces the abstraction.

Scope (V1)
----------
This PR handles the **6 Group A call sites** in:

* ``src/runtime/tools/tool_compressor.py``
* ``src/runtime/alert/service.py``
* ``src/runtime/mcp_config/manager.py``
* ``src/runtime/budget/token_quota.py``
* ``src/agent/deep_think.py``
* ``src/agent/_reload_broadcaster.py``

Plus the internal helper in ``runtime/cache/registry_store.py:_try_get_redis_client``
which already had a singleton-cached ComponentService.

The 6 Group B ``ComponentService()`` construction sites in Celery worker
contexts (schedule_tasks / worker_pool / evaluation) keep their direct
construction for now; PR-E5b will migrate them after PR-E5 lands.

Fall-back path (PR-E5 only; deleted in Phase 2)
-----------------------------------------------
When no provider is installed via :func:`set_backend_provider`,
:func:`get_backend_provider` lazily synthesises one that wraps
``web.component.ComponentService``. This makes PR-E5 a zero-behaviour-
change refactor for ai-buddy's current boot path. SDK consumers
(Phase 2) must call ``set_backend_provider(...)`` at boot before any
engine path runs.

Same pattern as PR-E1 :class:`EngineConfig` — see
``src/runtime/protocols/engine_config.py`` for the precedent.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


class BackendProviderNotInstalledError(RuntimeError):
    """Raised when :func:`get_backend_provider` is called before any
    provider has been installed AND the legacy ``web.component``
    fallback is not reachable.

    SDK consumers (Phase 2 onwards) MUST call
    ``set_backend_provider(...)`` during boot before any engine module
    runs.
    """


@runtime_checkable
class BackendClientProvider(Protocol):
    """Pluggable provider for the small set of process-level backends
    the engine layer touches: an async Mongo (motor) client and a
    Redis client (which may itself be sync or async).

    SDK consumers implement this Protocol against whatever container
    framework / DI they use, and call :func:`set_backend_provider` at
    boot. Engine modules call :func:`get_backend_provider` and then
    ``await provider.get_mongo_client()`` etc. at use time.
    """

    async def get_mongo_client(self) -> Any:
        """Return the active motor async Mongo client (or None when
        Mongo is intentionally not configured).
        """
        ...

    async def get_redis_client(self) -> Any:
        """Return the active Redis client (or None when Redis is
        intentionally not configured).

        Implementations may return either ``redis.asyncio.Redis`` or a
        sync ``redis.Redis`` — engine callers use
        :func:`_maybe_await` (see :mod:`runtime.cache.registry_store`)
        to tolerate both.
        """
        ...


# ── Module-level singleton ──────────────────────────────────────────────


_backend_provider: Optional[BackendClientProvider] = None


def set_backend_provider(provider: BackendClientProvider) -> None:
    """Install the BackendClientProvider used by all engine modules.

    Idempotent — subsequent calls overwrite. Logs at INFO so boot
    order is auditable. Provider IS NOT validated at install time —
    the protocol's methods are called lazily at use time, so a faulty
    implementation surfaces at first use, not at boot.
    """
    global _backend_provider
    _backend_provider = provider
    logger.info(
        "BackendClientProvider installed: %s",
        type(provider).__name__,
    )


def get_backend_provider() -> BackendClientProvider:
    """Return the installed provider, falling back to a lazy adapter
    that wraps :class:`web.component.ComponentService` when no
    explicit provider is installed.

    The fall-back is PR-E5-only and will be deleted in Phase 2 of the
    SDK extraction plan. SDK consumers MUST install a provider at
    boot.

    Raises:
        BackendProviderNotInstalledError: when no provider is
            installed AND ``web.component`` is not importable.
    """
    if _backend_provider is not None:
        return _backend_provider

    # PR-E5 fall-back. Probe ``web.component`` module reachability —
    # only the module needs to exist; the legacy adapter handles the
    # case where the ``component`` singleton inside it is None or
    # missing keys.
    try:
        import importlib
        importlib.import_module("web.component")
    except ImportError as exc:
        raise BackendProviderNotInstalledError(
            "BackendClientProvider has not been installed and "
            "web.component is not importable. Call "
            "set_backend_provider(provider) at boot before any engine "
            "code path runs."
        ) from exc

    # Lazy-construct on first miss; cache so subsequent calls skip
    # ComponentService re-construction (its Eureka/Apollo init is
    # expensive).
    return _LegacyComponentBackendProvider.get_singleton()


def reset_backend_provider_for_test() -> None:
    """Test-only helper to clear the installed provider between cases.

    NOT for production use. Mirrors
    :func:`runtime.protocols.engine_config.reset_engine_config_for_test`.
    """
    global _backend_provider
    _backend_provider = None
    _LegacyComponentBackendProvider.reset_singleton_for_test()


# ── Legacy ComponentService adapter (fallback) ──────────────────────────


class _LegacyComponentBackendProvider:
    """Adapter that exposes :data:`web.component.component` (the
    pre-built ComponentService singleton in ai-buddy) via the
    :class:`BackendClientProvider` Protocol.

    Used only via the fall-back path in :func:`get_backend_provider`
    when no SDK-side provider is installed. ai-buddy can choose to
    install this adapter explicitly at boot (cleaner audit trail) or
    rely on the fall-back (zero boot wiring).

    Reads ``web.component.component`` lazily inside each method so the
    adapter survives early-boot scenarios where the singleton hasn't
    been constructed yet (e.g. import-time agent module loads). When
    the singleton is None or the requested component isn't registered,
    each method returns ``None`` — mirroring the existing fail-soft
    pattern that engine consumers already wrap in try/except.
    """

    _SINGLETON: Optional["_LegacyComponentBackendProvider"] = None

    @classmethod
    def get_singleton(cls) -> "_LegacyComponentBackendProvider":
        if cls._SINGLETON is None:
            cls._SINGLETON = cls()
        return cls._SINGLETON

    @classmethod
    def reset_singleton_for_test(cls) -> None:
        cls._SINGLETON = None

    @staticmethod
    def _service() -> Any:
        """Read the ai-buddy ComponentService singleton lazily.

        ``web.component.component`` is the module-level instance built
        by ``web/component.py:105`` after boot init runs; before that
        line executes the attribute is ``None``. We re-read on every
        call instead of caching so a late init still resolves.
        """
        try:
            from web import component as _web_component_mod
        except ImportError:
            return None
        return getattr(_web_component_mod, "component", None)

    async def get_mongo_client(self) -> Any:
        svc = self._service()
        if svc is None:
            return None
        comp = svc.get("mongo") if hasattr(svc, "get") else None
        if comp is None:
            return None
        client = getattr(comp, "get_client", None)
        if client is None:
            return comp
        # ``get_client`` may be a coroutine-returning property or sync.
        import inspect
        if inspect.isawaitable(client):
            return await client
        return client

    async def get_redis_client(self) -> Any:
        svc = self._service()
        if svc is None:
            return None
        comp = svc.get("redis") if hasattr(svc, "get") else None
        if comp is None:
            return None
        client = getattr(comp, "get_client", None)
        if client is None:
            return comp
        import inspect
        if inspect.isawaitable(client):
            return await client
        return client


__all__ = [
    "BackendClientProvider",
    "BackendProviderNotInstalledError",
    "set_backend_provider",
    "get_backend_provider",
    "reset_backend_provider_for_test",
]
