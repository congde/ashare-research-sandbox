# -*- coding: utf-8 -*-
"""Bootstrap ContextStore for local vs production storage."""

import logging
import os

logger = logging.getLogger(__name__)


def init_context_store() -> None:
    """Install the session/QA storage backend before any agent code runs.

    Local dev (``serverEnv=local``) uses :class:`InMemoryContextStore` so
    chat/session/QA never touch MongoDB. Production keeps the legacy Mongo
    adapter via :func:`get_context_store` lazy fallback unless explicitly
    pinned with ``RUNTIME__STORAGE_BACKEND=mongo``.
    """
    backend = os.environ.get("RUNTIME__STORAGE_BACKEND", "").strip().lower()
    server_env = os.environ.get("serverEnv", "local").strip().lower()

    if backend == "mongo":
        logger.info("ContextStore: MongoDB (RUNTIME__STORAGE_BACKEND=mongo)")
        return

    if server_env == "local" or backend in ("memory", "sqlite"):
        from vendor_runtime_sdk.runtime.protocols.context_store import (
            InMemoryContextStore,
            set_context_store,
        )

        set_context_store(InMemoryContextStore())
        logger.info(
            "ContextStore: InMemoryContextStore enabled (serverEnv=%s, no MongoDB)",
            server_env,
        )
        return

    logger.info("ContextStore: MongoDB legacy adapter (serverEnv=%s)", server_env)
