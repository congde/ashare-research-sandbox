# -*- coding: utf-8 -*-
"""
runtime.storage — StorageBackend Protocol composition + selector.

Sprint 0 PR-A delivery (docs/TUI-Web-Runtime同构化技术方案.md §A2).

Contents
--------
* ``StorageBackend`` — composes 9 sub-Protocols (sessions / qa / memory
  / cost / coordinator_threads / hitl_gates / artifacts / stream_sink /
  registry_store) into a single injection handle.
* ``StreamSink`` — Protocol for SSE event queue + status + completion
  channel (replaces direct RedisCache access in ``_resume.py`` /
  ``_stream.py``).
* ``get_storage_backend(backend="auto"|"mongo"|"sqlite")`` — factory
  selector. PR-A ships the ladder; PR-B / PR-C land the backend
  implementations.

This package is import-clean in Sprint 0 (no side effects, no Mongo /
Redis / SQLite connection on import). Calling ``get_storage_backend``
in PR-A's scope raises ``NotImplementedError`` because the actual
backend constructors aren't here yet — that's intentional, the
selector contract is what PR-B / PR-C need pinned.
"""

from __future__ import annotations

from vendor_runtime_sdk.runtime.storage.backend import StorageBackend
from vendor_runtime_sdk.runtime.storage.factory import get_storage_backend
from vendor_runtime_sdk.runtime.storage.stream_sink import StreamSink

__all__ = [
    "StorageBackend",
    "StreamSink",
    "get_storage_backend",
]
