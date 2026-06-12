# -*- coding: utf-8 -*-
"""Sprint 10 PR-5 · runtime mode + record-session glue.

Module-level state:

  * ``_CASSETTE`` — singleton, lazy-loaded keyed by env path.
  * Mode is re-read from env on every call (tests can flip it
    mid-run without re-importing).

Public API: see :mod:`runtime.llm_replay.__init__`.
"""
from __future__ import annotations

import contextlib
import logging
import os
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from .cassette import Cassette, CassetteMissError, request_key

logger = logging.getLogger(__name__)


class PolicyMode(str, Enum):
    NONE = "none"
    RECORD = "record"
    REPLAY = "replay"


_VALID_MODES = {m.value for m in PolicyMode}


def get_runtime_mode() -> PolicyMode:
    """Read ``LLM_CASSETTE_MODE`` env (default ``none``).

    Unknown values fall back to ``none`` with a one-time WARN — a
    typo in CI config shouldn't silently disable cassette behaviour.
    """
    raw = (os.environ.get("LLM_CASSETTE_MODE", "") or "").strip().lower()
    if not raw:
        return PolicyMode.NONE
    if raw not in _VALID_MODES:
        logger.warning(
            "LLM_CASSETTE_MODE=%r is not one of %s; treating as NONE",
            raw, sorted(_VALID_MODES),
        )
        return PolicyMode.NONE
    return PolicyMode(raw)


# ── Singleton cassette (path-keyed) ────────────────────────────────────────


_CASSETTES: Dict[str, Cassette] = {}
# Sprint 10 PR-review fix HIGH-6 — protect the singleton-registry
# check-then-set pattern.  Without this, two threads could both see
# ``key not in _CASSETTES`` and instantiate two ``Cassette`` objects,
# silently discarding one's in-memory state.  The Cassette itself is
# internally locked, but the registry lookup is not.
_CASSETTES_LOCK = threading.Lock()


def _resolve_cassette_path() -> Optional[Path]:
    raw = (os.environ.get("LLM_CASSETTE_PATH", "") or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def get_cassette() -> Optional[Cassette]:
    """Return the cassette for the current ``LLM_CASSETTE_PATH`` env.

    Returns ``None`` when the env is unset (mode=none / misconfig).
    The first call for a given path eagerly loads the file from
    disk; later calls in the same process re-use the in-memory dict.

    Thread-safe via :data:`_CASSETTES_LOCK`.
    """
    path = _resolve_cassette_path()
    if path is None:
        return None
    key = str(path)
    with _CASSETTES_LOCK:
        cas = _CASSETTES.get(key)
        if cas is None:
            cas = Cassette(path=path)
            cas.load()
            _CASSETTES[key] = cas
        return cas


def reset_for_test() -> None:
    """Clear the singleton cache.  Tests that flip
    ``LLM_CASSETTE_PATH`` between cases must call this between
    fixtures so they don't share an in-memory cassette."""
    with _CASSETTES_LOCK:
        _CASSETTES.clear()


# ── Replay path ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReplayResult:
    deltas: List[str]
    usage: Optional[Dict[str, Any]]


def fetch_replay(request: Dict[str, Any]) -> Optional[ReplayResult]:
    """Look up *request* in the active cassette.

    Returns ``None`` when:
      - mode is not REPLAY
      - no cassette path configured
      - request hash not present (caller decides whether to raise
        :class:`CassetteMissError` — for REPLAY mode that's
        fail-closed; for AUTO-style modes the caller may fall
        through to upstream).
    """
    mode = get_runtime_mode()
    if mode is not PolicyMode.REPLAY:
        return None
    cas = get_cassette()
    if cas is None:
        return None
    key = request_key(request)
    entry = cas.find(key)
    if entry is None:
        return None
    return ReplayResult(deltas=list(entry.deltas), usage=entry.usage)


def must_replay(request: Dict[str, Any]) -> ReplayResult:
    """REPLAY-mode helper: lookup or raise :class:`CassetteMissError`.

    Use when a stream_llm caller has already determined that
    REPLAY is active and wants the strict fail-closed contract.
    """
    out = fetch_replay(request)
    if out is None:
        raise CassetteMissError(
            "no cassette entry for the current request "
            "(mode=replay, hash=" + request_key(request) + ")"
        )
    return out


# ── Record path ────────────────────────────────────────────────────────────


@dataclass
class _RecordSession:
    """Buffers deltas / usage for a single LLM call.  On
    ``commit`` writes through the cassette + persists; on
    ``discard`` (e.g. exception inside the upstream stream) the
    buffer is dropped — no half-recorded state on disk."""

    request: Dict[str, Any]
    _deltas: List[str] = field(default_factory=list)
    _usage: Optional[Dict[str, Any]] = None
    _committed: bool = False

    def append_delta(self, delta: str) -> None:
        if not self._committed and isinstance(delta, str):
            self._deltas.append(delta)

    def set_usage(self, usage: Optional[Dict[str, Any]]) -> None:
        if not self._committed and usage is not None:
            self._usage = dict(usage)

    def commit(self) -> None:
        if self._committed:
            return
        self._committed = True
        cas = get_cassette()
        if cas is None:
            logger.debug(
                "record_session commit: no cassette path — dropping %d deltas",
                len(self._deltas),
            )
            return
        try:
            key = request_key(self.request)
            # RECORD mode always overwrites; this is the
            # operator-explicit refresh path.
            cas.replace(
                key=key,
                request=self.request,
                deltas=self._deltas,
                usage=self._usage,
            )
            cas.save()
            logger.info(
                "llm_replay: recorded %d deltas (key=%s, path=%s)",
                len(self._deltas), key[:12], cas.path,
            )
        except Exception:  # noqa: BLE001 — never let cassette IO crash a turn
            logger.exception(
                "llm_replay: failed to persist cassette (deltas dropped)",
            )

    def discard(self) -> None:
        # Caller explicitly chose not to persist (upstream raised).
        self._committed = True
        self._deltas.clear()
        self._usage = None


@contextlib.contextmanager
def record_session(request: Dict[str, Any]) -> Iterator[_RecordSession]:
    """Context manager for RECORD mode.

    Usage::

        with record_session(req) as rec:
            async for delta in upstream_stream():
                rec.append_delta(delta)
                yield delta
            rec.set_usage(final_usage)

    When the body exits without raising, ``commit`` is called
    automatically.  An exception inside the body causes ``discard``
    so half-recorded streams never land on disk.
    """
    rec = _RecordSession(request=dict(request))
    try:
        yield rec
        rec.commit()
    except BaseException:  # noqa: BLE001 — propagate after discard
        rec.discard()
        raise


__all__ = [
    "PolicyMode",
    "ReplayResult",
    "fetch_replay",
    "get_cassette",
    "get_runtime_mode",
    "must_replay",
    "record_session",
    "reset_for_test",
]
