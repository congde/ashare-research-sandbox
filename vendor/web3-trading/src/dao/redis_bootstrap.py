# -*- coding: utf-8 -*-
"""Bootstrap Redis / SessionCache for local vs production."""

from __future__ import annotations

import logging
import os
from typing import Optional, Union

from dao.cache.memory_redis import InMemoryRedis

logger = logging.getLogger(__name__)

_memory_redis: Optional[InMemoryRedis] = None
_use_memory_redis: Optional[bool] = None


def _local_mode() -> bool:
    backend = os.environ.get("RUNTIME__STORAGE_BACKEND", "").strip().lower()
    server_env = os.environ.get("serverEnv", "local").strip().lower()
    if backend == "redis":
        return False
    return server_env == "local" or backend in ("memory", "sqlite")


def init_redis() -> None:
    """Install in-memory Redis + SessionCache when running locally."""
    global _use_memory_redis, _memory_redis

    if not _local_mode():
        _use_memory_redis = False
        logger.info("Redis: production cluster client")
        return

    _use_memory_redis = True
    _memory_redis = InMemoryRedis()

    from vendor_runtime_sdk.runtime.protocols.session_cache import (
        InMemorySessionCache,
        set_session_cache,
    )

    set_session_cache(InMemorySessionCache())
    logger.info(
        "Redis: InMemoryRedis + InMemorySessionCache enabled (serverEnv=%s, no Redis cluster)",
        os.environ.get("serverEnv", "local"),
    )


def get_redis_client() -> Union[InMemoryRedis, object]:
    """Return local in-memory Redis or the configured cluster client."""
    if _use_memory_redis is None:
        init_redis()
    if _use_memory_redis:
        assert _memory_redis is not None
        return _memory_redis

    from web.component import component
    return component.get("redis").client
