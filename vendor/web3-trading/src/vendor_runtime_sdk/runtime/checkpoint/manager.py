# -*- coding: utf-8 -*-
"""
CheckpointManager — local filesystem session state snapshots.

Each checkpoint is stored as a single JSON file:

  {base_dir}/{session_id[:8]}/{checkpoint_id}/state.json

checkpoint_id is a zero-padded Unix millisecond timestamp:
  e.g. "0001744300000000"

This gives lexicographic ordering (newest-last when sorted ascending,
newest-first when reversed) without requiring a database.

Operations:
  save(session_id, state_dict, metadata=None)  → checkpoint_id
  load(session_id, checkpoint_id=None)         → state_dict | None
  list(session_id)                             → List[CheckpointRecord] newest-first
  prune(session_id, keep_last=5)              → int (deleted count)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_STATE_FILE = "state.json"


def _resolve_default_base() -> Path:
    """Plan §3.2 — checkpoints live on the shared PVC in production.

    Reading :mod:`runtime.config.shared_storage` lazily keeps this module
    importable from tests / scripts that may not have the runtime stack on
    the PYTHONPATH. Falls back to the legacy ``data/checkpoints`` relative
    path only when the shared-storage helper is not importable.
    """
    try:
        from vendor_runtime_sdk.runtime.config.shared_storage import checkpoint_base
        return checkpoint_base()
    except Exception:
        return Path("data/checkpoints")


@dataclass
class CheckpointRecord:
    """Metadata for a single checkpoint (no state payload)."""

    checkpoint_id: str  # zero-padded ms timestamp, e.g. "0001744300000000"
    session_id: str
    created_at_ms: int  # same value as int(checkpoint_id)
    size_bytes: int  # bytes on disk


class CheckpointManager:
    """
    Local filesystem checkpoint manager.

    Thread-safe for reads. Writes are protected by the calling layer's lock
    (the manager itself does not hold an internal lock — checkpoint IDs are
    unique per millisecond so concurrent writes to *different* sessions are
    safe; concurrent writes to the *same* session should be serialised by the
    caller).
    """

    def __init__(self, base_dir: Optional[str] = None) -> None:
        # ``None`` → use the env-resolved default (shared PVC in production,
        # ``~/.ai-buddy/checkpoints`` in local dev). Explicit ``base_dir`` is
        # still honoured so tests / one-off scripts can point elsewhere.
        if base_dir is None:
            self._base = _resolve_default_base()
        else:
            self._base = Path(base_dir)

    # ── Paths ──────────────────────────────────────────────────────────────────

    def _session_dir(self, session_id: str) -> Path:
        return self._base / session_id[:8]

    def _checkpoint_dir(self, session_id: str, checkpoint_id: str) -> Path:
        return self._session_dir(session_id) / checkpoint_id

    # ── Public API ─────────────────────────────────────────────────────────────

    def save(
        self,
        session_id: str,
        state: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Persist *state* to disk and return the checkpoint_id.

        The checkpoint_id is a zero-padded millisecond Unix timestamp
        (16 digits) so that directory listings are chronologically ordered.
        """
        checkpoint_id = f"{int(time.time() * 1000):016d}"
        ckpt_dir = self._checkpoint_dir(session_id, checkpoint_id)
        ckpt_dir.mkdir(parents=True, exist_ok=True)

        doc: Dict[str, Any] = {
            "session_id": session_id,
            "checkpoint_id": checkpoint_id,
            "state": state,
        }
        if metadata:
            doc["metadata"] = metadata

        raw = json.dumps(doc, ensure_ascii=False, indent=2)
        state_file = ckpt_dir / _STATE_FILE
        state_file.write_text(raw, encoding="utf-8")
        logger.debug(
            "CheckpointManager: saved %s/%s (%d bytes)",
            session_id[:8],
            checkpoint_id,
            len(raw),
        )

        # §3.2 — when ``checkpoint_mongo`` is on, record the blob location in
        # Mongo so multi-pod ``list`` queries don't have to ``os.listdir`` a
        # PVC directory that may contain other pods' checkpoints.
        workspace_id = (metadata or {}).get("workspace_id") or ""
        if workspace_id:
            self._record_metadata_fire_and_forget(
                session_id=session_id,
                workspace_id=workspace_id,
                checkpoint_id=checkpoint_id,
                blob_path=str(state_file),
                byte_size=len(raw),
            )
        return checkpoint_id

    @staticmethod
    def _record_metadata_fire_and_forget(
        *,
        session_id: str,
        workspace_id: str,
        checkpoint_id: str,
        blob_path: str,
        byte_size: int,
    ) -> None:
        """Insert Mongo metadata without blocking the caller.

        ``save()`` is synchronous (called from background threads via
        ``asyncio.to_thread``). To write metadata we need to schedule an
        async insert on whichever loop is available. Fail-soft — the blob
        on the PVC is authoritative regardless of metadata success.
        """
        try:
            from vendor_runtime_sdk.runtime.config.toggles import get_toggles
            if not get_toggles().is_enabled("checkpoint_mongo"):
                return
        except Exception:
            return

        try:
            from dao.mongo.checkpoint_meta import get_checkpoint_meta_dao
            dao = get_checkpoint_meta_dao()
            coro = dao.record(
                session_id=session_id,
                workspace_id=workspace_id,
                ts=checkpoint_id,
                blob_path=blob_path,
                byte_size=byte_size,
            )
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None:
                asyncio.ensure_future(coro)
                return
            # No running loop — run synchronously on a fresh loop.
            asyncio.run(coro)
        except Exception as exc:
            logger.debug(
                "CheckpointManager: metadata record skipped session=%s: %s",
                session_id,
                exc,
            )

    def load(
        self,
        session_id: str,
        checkpoint_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Load and return the state dict for *checkpoint_id*.

        If *checkpoint_id* is None, loads the most recent checkpoint.
        Returns None if no checkpoint exists.
        """
        if checkpoint_id is None:
            records = self.list(session_id)
            if not records:
                return None
            checkpoint_id = records[0].checkpoint_id  # newest first

        ckpt_file = self._checkpoint_dir(session_id, checkpoint_id) / _STATE_FILE
        if not ckpt_file.exists():
            return None

        doc = json.loads(ckpt_file.read_text(encoding="utf-8"))
        return doc.get("state")

    def list(self, session_id: str) -> List[CheckpointRecord]:
        """
        Return all checkpoint records for *session_id*, newest first.
        """
        session_dir = self._session_dir(session_id)
        if not session_dir.exists():
            return []

        records: List[CheckpointRecord] = []
        for ckpt_dir in session_dir.iterdir():
            if not ckpt_dir.is_dir():
                continue
            ckpt_file = ckpt_dir / _STATE_FILE
            if not ckpt_file.exists():
                continue
            try:
                created_at_ms = int(ckpt_dir.name)
            except ValueError:
                continue
            records.append(
                CheckpointRecord(
                    checkpoint_id=ckpt_dir.name,
                    session_id=session_id,
                    created_at_ms=created_at_ms,
                    size_bytes=ckpt_file.stat().st_size,
                )
            )

        records.sort(key=lambda r: r.created_at_ms, reverse=True)
        return records

    def prune(self, session_id: str, keep_last: int = 5) -> int:
        """
        Delete all but the *keep_last* most recent checkpoints.

        Returns the number of deleted checkpoints.
        """
        records = self.list(session_id)
        to_delete = records[keep_last:]
        deleted = 0
        for rec in to_delete:
            ckpt_dir = self._checkpoint_dir(session_id, rec.checkpoint_id)
            ckpt_file = ckpt_dir / _STATE_FILE
            try:
                ckpt_file.unlink(missing_ok=True)
                ckpt_dir.rmdir()
                deleted += 1
            except OSError as exc:
                logger.warning("CheckpointManager: prune failed for %s: %s", ckpt_dir, exc)
        return deleted
