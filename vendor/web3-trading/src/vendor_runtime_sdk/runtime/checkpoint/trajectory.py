# -*- coding: utf-8 -*-
"""
TrajectoryRecorder — append-only JSONL turn log for fine-tuning data collection.

Each record is one conversation turn in a ShareGPT-compatible format:

  {
    "id":            "<turn_id>",
    "session_id":    "<session_id>",
    "ts":            <unix float>,
    "outcome":       "success" | "failure",
    "conversations": [
      {"from": "system", "value": "..."},
      {"from": "human",  "value": "..."},
      {"from": "gpt",    "value": "..."}
    ],
    "metadata": {...}
  }

File layout:

  Successful turns → {base_dir}/{year}{month:02d}/{session_id[:8]}.jsonl
  Failed turns     → {base_dir}/failed/{session_id[:8]}.jsonl

The yearly/monthly sub-directory buckets keep file sizes manageable.
Failed trajectories are segregated for separate analysis and replay.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _resolve_default_base() -> Path:
    """Plan §3.3 — trajectories fall back to the shared PVC when the Mongo
    primary is unavailable. Lazy import keeps the module importable from
    tests/scripts that don't have the runtime stack on sys.path."""
    try:
        from vendor_runtime_sdk.runtime.config.shared_storage import trajectory_base
        return trajectory_base()
    except Exception:
        return Path("data/trajectories")


class TrajectoryRecorder:
    """
    Thread-safe, append-only JSONL trajectory recorder.

    File handles are opened-and-closed per write (no long-lived fd) to prevent
    descriptor leaks in long-running services.
    """

    def __init__(self, base_dir: Optional[str] = None) -> None:
        if base_dir is None:
            self._base = _resolve_default_base()
        else:
            self._base = Path(base_dir)
        self._lock = threading.Lock()

    # ── Public API ─────────────────────────────────────────────────────────────

    def record_turn(
        self,
        session_id: str,
        turn_id: str,
        messages: List[Dict[str, str]],
        outcome: str = "success",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Append a turn record to the success file for *session_id*.

        *messages* is a list of ShareGPT-style dicts:
          [{"from": "human"|"gpt"|"system", "value": "..."}]

        Plan §3.3 — when ``trajectory_mongo`` is on the primary sink is the
        Mongo ``trajectories`` collection; the JSONL on the shared PVC is a
        fallback that kicks in automatically when Mongo is unreachable.
        """
        record = self._build_record(session_id, turn_id, messages, outcome, metadata)
        if self._try_mongo_write(session_id, outcome, record, metadata):
            return
        self._append(self._success_path(session_id), record)

    def record_failure(
        self,
        session_id: str,
        turn_id: str,
        messages: List[Dict[str, str]],
        error: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Append a failed turn record to the failure file for *session_id*.

        *error* is stored in metadata["error"].
        """
        meta = dict(metadata or {})
        meta["error"] = error
        record = self._build_record(session_id, turn_id, messages, "failure", meta)
        if self._try_mongo_write(session_id, "failure", record, meta):
            return
        self._append(self._failure_path(session_id), record)

    # ── Mongo primary sink ────────────────────────────────────────────────

    def _try_mongo_write(
        self,
        session_id: str,
        outcome: str,
        record: Dict[str, Any],
        metadata: Optional[Dict[str, Any]],
    ) -> bool:
        """Attempt to persist *record* to the Mongo ``trajectories`` collection.

        Returns True when the Mongo write succeeded; the caller then skips
        the shared-PVC fallback. Fail-soft on any error — shared-PVC JSONL
        is always a safety net.
        """
        try:
            from vendor_runtime_sdk.runtime.config.toggles import get_toggles
            if not get_toggles().is_enabled("trajectory_mongo"):
                return False
        except Exception:
            return False

        workspace_id = (metadata or {}).get("workspace_id") or ""
        if not workspace_id:
            # Without workspace_id we cannot satisfy the compound index.
            # Degrade to the PVC fallback which is workspace-agnostic.
            return False

        turn_idx = int((metadata or {}).get("turn_idx", 0) or 0)

        # ``record_turn`` is a sync method typically invoked from
        # ``asyncio.to_thread(...)`` — so we are in a worker thread with no
        # running loop and can safely spin ``asyncio.run(...)`` to block
        # until the Mongo insert completes and we know whether to skip the
        # PVC fallback. When a caller *is* on the event loop thread, fall
        # back to the PVC (better than double-writing and better than
        # blocking the loop).
        try:
            asyncio.get_running_loop()
            return False
        except RuntimeError:
            pass

        try:
            from dao.mongo.trajectory import get_trajectory_dao
            dao = get_trajectory_dao()
            return bool(
                asyncio.run(
                    dao.append(
                        session_id=session_id,
                        workspace_id=workspace_id,
                        turn_idx=turn_idx,
                        event_type=outcome,
                        payload=record,
                    )
                )
            )
        except Exception as exc:
            logger.debug(
                "TrajectoryRecorder: mongo sink skipped session=%s: %s",
                session_id,
                exc,
            )
            return False

    def read(self, *, session_id: str) -> List[Dict[str, Any]]:
        """Read all trajectory turns for *session_id*.

        Tries Mongo first (when ``trajectory_mongo`` toggle is on), then
        falls back to scanning JSONL files on the shared PVC.
        """
        mongo_result = self._try_mongo_read(session_id)
        if mongo_result is not None:
            return mongo_result
        return self._read_jsonl(session_id)

    def _try_mongo_read(self, session_id: str) -> Optional[List[Dict[str, Any]]]:
        try:
            from vendor_runtime_sdk.runtime.config.toggles import get_toggles
            if not get_toggles().is_enabled("trajectory_mongo"):
                return None
        except Exception:
            return None

        try:
            asyncio.get_running_loop()
            return None
        except RuntimeError:
            pass

        try:
            from dao.mongo.trajectory import get_trajectory_dao
            dao = get_trajectory_dao()
            docs = asyncio.run(dao.list_for_session(session_id=session_id))
            return [
                doc.get("payload", doc)
                for doc in docs
                if isinstance(doc, dict)
            ]
        except Exception as exc:
            logger.debug("TrajectoryRecorder: mongo read skipped session=%s: %s", session_id, exc)
            return None

    def _read_jsonl(self, session_id: str) -> List[Dict[str, Any]]:
        prefix = session_id[:8]
        turns: List[Dict[str, Any]] = []

        # Scan success directories (all month buckets)
        for jsonl in sorted(self._base.glob(f"*/{prefix}.jsonl")):
            turns.extend(self._parse_jsonl(jsonl, session_id))

        # Scan failure directory
        fail_file = self._base / "failed" / f"{prefix}.jsonl"
        if fail_file.is_file():
            turns.extend(self._parse_jsonl(fail_file, session_id))

        turns.sort(key=lambda r: r.get("ts", 0))
        return turns

    @staticmethod
    def _parse_jsonl(path: Path, session_id: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        try:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        if record.get("session_id") == session_id:
                            results.append(record)
                    except json.JSONDecodeError:
                        continue
        except OSError as exc:
            logger.debug("TrajectoryRecorder: failed to read %s: %s", path, exc)
        return results

    # ── Path helpers ───────────────────────────────────────────────────────────

    def _success_path(self, session_id: str) -> Path:
        now = datetime.now(tz=timezone.utc)
        return self._base / f"{now.year}{now.month:02d}" / f"{session_id[:8]}.jsonl"

    def _failure_path(self, session_id: str) -> Path:
        return self._base / "failed" / f"{session_id[:8]}.jsonl"

    # ── Internals ─────────────────────────────────────────────────────────────

    def _build_record(
        self,
        session_id: str,
        turn_id: str,
        messages: List[Dict[str, str]],
        outcome: str,
        metadata: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return {
            "id": turn_id,
            "session_id": session_id,
            "ts": time.time(),
            "outcome": outcome,
            "conversations": messages,
            "metadata": metadata or {},
        }

    def _append(self, path: Path, record: Dict[str, Any]) -> None:
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(record, ensure_ascii=False)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        logger.debug("TrajectoryRecorder: appended to %s", path)
