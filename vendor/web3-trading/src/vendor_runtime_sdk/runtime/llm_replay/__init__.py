# -*- coding: utf-8 -*-
"""Sprint 10 PR-5 · LLM-layer record-replay cassette.

Per plan ``zesty-roaming-wilkes`` T2.2.

Production-grade record / replay infrastructure that wraps
:func:`llm.llm.stream_llm` so CI / dev can run integration tests
without burning real LLM tokens.  Driven by env vars; default
``mode=none`` means production behaviour is byte-identical to
pre-Sprint-10.

  LLM_CASSETTE_MODE   none (default) | record | replay
  LLM_CASSETTE_PATH   absolute path to JSONL cassette file

Replay-miss is fail-closed by design — CI catching stale cassettes
is the whole point.

Key public API:

  * :func:`get_runtime_mode` — env-resolved policy (live, not cached)
  * :func:`get_cassette` — singleton accessor (path-keyed)
  * :func:`request_key` — deterministic SHA-256 hash of canonicalised
    request (excluding volatile fields)
  * :func:`fetch_replay` — return cached deltas+usage or None
  * :func:`record_session` — context manager that buffers deltas and
    commits on success
"""
from __future__ import annotations

from .cassette import (
    Cassette,
    CassetteEntry,
    CassetteMissError,
    request_key,
)
from .runtime import (
    PolicyMode,
    fetch_replay,
    get_cassette,
    get_runtime_mode,
    record_session,
    reset_for_test,
)

__all__ = [
    "Cassette",
    "CassetteEntry",
    "CassetteMissError",
    "PolicyMode",
    "fetch_replay",
    "get_cassette",
    "get_runtime_mode",
    "record_session",
    "request_key",
    "reset_for_test",
]
