# -*- coding: utf-8 -*-
"""Sprint 10 PR-5 · cassette container — JSONL on disk, in-memory dict.

A simpler peer to ``tests/mocks/llm_cassette.py`` that lives under
production runtime code so ``llm.llm.stream_llm`` can import it
without a circular test-vs-prod dep.

Cassette JSONL format (one entry per line):

  {
    "request_hash": "<sha256>",
    "request": {model, messages, max_tokens, temperature, ...},
    "response": {
      "deltas": ["chunk1", "chunk2", ...],
      "usage": {input_tokens, output_tokens, ...} | null
    }
  }

Volatile fields excluded from the hash so re-runs hit the cache
instead of recording a fresh entry every time.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


_VOLATILE_TOP_LEVEL = frozenset({
    "request_id",
    "user",
    "timestamp",
    "metadata",
    "stream_options",
    "x_request_id",
    "extra_headers",
})


class CassetteMissError(LookupError):
    """Raised when REPLAY policy can't find a recorded response.

    Fail-closed in CI: a missing cassette means either (a) someone
    added a new prompt without re-recording or (b) request shape
    drifted.  Either way the operator must re-record explicitly.
    """


@dataclass(frozen=True)
class CassetteEntry:
    """One recorded request / response pair."""

    request_hash: str
    request: Dict[str, Any]
    deltas: List[str]
    usage: Optional[Dict[str, Any]] = None

    def to_jsonl_line(self) -> str:
        return json.dumps({
            "request_hash": self.request_hash,
            "request": self.request,
            "response": {
                "deltas": list(self.deltas),
                "usage": self.usage,
            },
        }, ensure_ascii=False)


def _redact_secrets(text: str) -> str:
    """Defensive PII / secret scrub before persistence.

    Falls back to a verbatim copy if the security scanner can't be
    imported — ``redact_secrets`` is pure CPU but the import path
    pulls config in some environments.  Cassette callers should not
    fail just because the redactor is unavailable.
    """
    if not isinstance(text, str) or not text:
        return text
    try:
        from security.secret_scanner import redact_secrets

        return redact_secrets(text)
    except Exception:  # noqa: BLE001 — fail-soft per design
        return text


def _redact_request(request: Dict[str, Any]) -> Dict[str, Any]:
    """Apply secret scrub to every string-valued message content
    before hashing / persistence.

    Sprint 10 PR-review fix HIGH-2: multimodal flows (Sprint 9
    ``coder_multimodal_input``) carry list-typed content of
    ``[{"type": "text", "text": "..."}, {"type": "image_url",
    "image_url": {"url": "data:image/png;base64,..."}}]``.  The
    previous implementation only handled string content — list
    parts (text fragments + base64 image data) were persisted to
    the cassette unredacted.  Now we walk lists recursively:

      * ``text`` parts run through :func:`_redact_secrets`.
      * ``image_url`` parts are stripped to ``{"type": "image_url",
        "image_url": {"url": "<redacted>"}}`` because base64 image
        bytes can encode screenshots / OCR-able secrets, and a
        cassette is for replay determinism — the image identity
        doesn't need to round-trip.

    Returns a NEW dict — never mutates the caller's request.
    """
    out: Dict[str, Any] = dict(request)
    messages = out.get("messages")
    if isinstance(messages, list):
        cleaned: List[Any] = []
        for msg in messages:
            if isinstance(msg, dict):
                m = dict(msg)
                content = m.get("content")
                if isinstance(content, str):
                    m["content"] = _redact_secrets(content)
                elif isinstance(content, list):
                    m["content"] = _redact_content_parts(content)
                cleaned.append(m)
            else:
                cleaned.append(msg)
        out["messages"] = cleaned
    return out


def _redact_content_parts(parts: List[Any]) -> List[Any]:
    """Walk a list of multimodal content parts, redacting each one.

    Unknown part shapes (operator-defined custom content blocks)
    pass through untouched — never raise so the cassette never
    blocks a turn.
    """
    cleaned: List[Any] = []
    for part in parts:
        if not isinstance(part, dict):
            cleaned.append(part)
            continue
        ptype = part.get("type")
        if ptype == "text" and isinstance(part.get("text"), str):
            new_part = dict(part)
            new_part["text"] = _redact_secrets(part["text"])
            cleaned.append(new_part)
        elif ptype == "image_url":
            cleaned.append({
                "type": "image_url",
                "image_url": {"url": "<redacted>"},
            })
        elif ptype == "image":
            # Anthropic-style image block: ``{"type": "image",
            # "source": {"type": "base64", "media_type": "...",
            # "data": "..."}}`` — strip the data payload.
            cleaned.append({
                "type": "image",
                "source": {"type": "base64", "data": "<redacted>"},
            })
        else:
            # Unknown type (e.g. tool_use / tool_result blocks):
            # only redact string fields, preserve structure.
            new_part = dict(part)
            for k, v in list(new_part.items()):
                if isinstance(v, str):
                    new_part[k] = _redact_secrets(v)
            cleaned.append(new_part)
    return cleaned


def request_key(request: Dict[str, Any]) -> str:
    """Deterministic SHA-256 hash of a canonicalised + redacted
    request.

    Volatile fields (``request_id`` / ``user`` / ``timestamp`` /
    ``metadata`` / ``stream_options``) are stripped so identical
    semantic requests always produce the same hash, even when the
    OpenAI client appends a fresh ``request_id`` per call.
    Secrets are redacted before hashing — a cassette that survives
    a key rotation is more useful than one that invalidates on
    every secret rotation.
    """
    clean = {
        k: v for k, v in request.items()
        if k not in _VOLATILE_TOP_LEVEL
    }
    clean = _redact_request(clean)
    blob = json.dumps(clean, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass
class Cassette:
    """In-memory cassette backed by a JSONL file on disk."""

    path: Path
    _entries: Dict[str, CassetteEntry] = field(default_factory=dict)
    _loaded: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)

    def load(self) -> None:
        """Load entries from disk.  Idempotent.  Catches narrow
        expected failures (malformed lines / OS errors); programming
        bugs propagate."""
        with self._lock:
            self._entries = {}
            self._loaded = True
            if not self.path.exists():
                return
            try:
                with self.path.open("r", encoding="utf-8") as fh:
                    for raw in fh:
                        raw = raw.strip()
                        if not raw:
                            continue
                        try:
                            payload = json.loads(raw)
                            response = payload.get("response") or {}
                            entry = CassetteEntry(
                                request_hash=str(payload["request_hash"]),
                                request=dict(payload.get("request") or {}),
                                deltas=list(response.get("deltas") or []),
                                usage=response.get("usage"),
                            )
                            self._entries[entry.request_hash] = entry
                        except (json.JSONDecodeError, KeyError, TypeError) as exc:
                            logger.debug(
                                "cassette %s: malformed line skipped (%s)",
                                self.path, exc,
                            )
            except OSError as exc:
                logger.debug("cassette %s: load failed: %s", self.path, exc)

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def find(self, key: str) -> Optional[CassetteEntry]:
        self._ensure_loaded()
        with self._lock:
            return self._entries.get(key)

    def add(
        self,
        key: str,
        request: Dict[str, Any],
        deltas: List[str],
        usage: Optional[Dict[str, Any]] = None,
    ) -> None:
        """First-write-wins — duplicate add of the same key is a
        warning, not a silent overwrite (would mask non-determinism).
        Use :meth:`replace` to refresh."""
        self._ensure_loaded()
        with self._lock:
            if key in self._entries:
                logger.warning(
                    "cassette %s: skipping duplicate add for key=%s "
                    "(use replace() or LLM_CASSETTE_MODE=record to refresh)",
                    self.path, key,
                )
                return
            self._entries[key] = CassetteEntry(
                request_hash=key,
                request=_redact_request(dict(request)),
                deltas=list(deltas),
                usage=dict(usage) if usage else None,
            )

    def replace(
        self,
        key: str,
        request: Dict[str, Any],
        deltas: List[str],
        usage: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._ensure_loaded()
        with self._lock:
            self._entries[key] = CassetteEntry(
                request_hash=key,
                request=_redact_request(dict(request)),
                deltas=list(deltas),
                usage=dict(usage) if usage else None,
            )

    def save(self) -> None:
        """Atomic write: tmp file + ``os.replace`` so a crashed save
        leaves the previous cassette intact.

        Sprint 10 PR-review fix MEDIUM-5: tmp filename includes pid +
        thread-id so two processes / threads sharing the same
        ``LLM_CASSETTE_PATH`` don't clobber each other's tmp file.
        ``os.replace`` is atomic at the filesystem level — last
        replacer wins for the canonical path, but neither writer
        produces a corrupted file.
        """
        import threading as _threading

        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp_suffix = (
                f".{os.getpid()}.{_threading.get_ident()}.tmp"
            )
            tmp = self.path.with_suffix(self.path.suffix + tmp_suffix)
            try:
                with tmp.open("w", encoding="utf-8") as fh:
                    for key in sorted(self._entries):
                        fh.write(
                            self._entries[key].to_jsonl_line() + "\n"
                        )
                os.replace(tmp, self.path)
            except Exception:
                # Best-effort cleanup of the partial tmp on any failure.
                try:
                    if tmp.exists():
                        tmp.unlink()
                except OSError:
                    pass
                raise

    def __len__(self) -> int:
        self._ensure_loaded()
        return len(self._entries)


__all__ = [
    "Cassette",
    "CassetteEntry",
    "CassetteMissError",
    "request_key",
]
