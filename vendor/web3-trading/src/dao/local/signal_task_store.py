# -*- coding: utf-8 -*-
"""
Local file store for LLM signal analysis async tasks.

Layout (under data/llm_signal_tasks/):
  index.json           — lightweight registry keyed by taskId (no result payload)
  tasks/{taskId}.json  — full task record including result when done
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_STORE_ROOT = Path(os.getenv("LLM_SIGNAL_TASK_DIR") or "data/llm_signal_tasks")
_INDEX_PATH = _STORE_ROOT / "index.json"
_TASKS_DIR = _STORE_ROOT / "tasks"
_INDEX_VERSION = 1
_lock = threading.Lock()


class SignalTaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class SignalTaskMeta:
    """Lightweight entry kept in index.json (no result blob)."""

    taskId: str
    symbol: str
    model: str
    status: str
    error: Optional[str] = None
    createdAt: float = 0.0
    updatedAt: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SignalTaskRecord:
    """Full persisted task document (API / poll response source)."""

    taskId: str
    symbol: str
    model: str
    status: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    createdAt: float = 0.0
    updatedAt: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SignalTaskRecord":
        return cls(
            taskId=str(data.get("taskId") or ""),
            symbol=str(data.get("symbol") or ""),
            model=str(data.get("model") or ""),
            status=str(data.get("status") or SignalTaskStatus.PENDING.value),
            result=data.get("result") if isinstance(data.get("result"), dict) else None,
            error=data.get("error"),
            createdAt=float(data.get("createdAt") or 0),
            updatedAt=float(data.get("updatedAt") or 0),
        )

    def to_meta(self) -> SignalTaskMeta:
        return SignalTaskMeta(
            taskId=self.taskId,
            symbol=self.symbol,
            model=self.model,
            status=self.status,
            error=self.error,
            createdAt=self.createdAt,
            updatedAt=self.updatedAt,
        )


def _ensure_dirs() -> None:
    _TASKS_DIR.mkdir(parents=True, exist_ok=True)


def _task_path(task_id: str) -> Path:
    safe = "".join(ch for ch in str(task_id) if ch.isalnum())
    return _TASKS_DIR / f"{safe}.json"


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _load_index_unlocked() -> Dict[str, Any]:
    if not _INDEX_PATH.exists():
        return {"version": _INDEX_VERSION, "tasks": {}}
    try:
        with _INDEX_PATH.open(encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, dict):
            return {"version": _INDEX_VERSION, "tasks": {}}
        tasks = data.get("tasks")
        if not isinstance(tasks, dict):
            data["tasks"] = {}
        data.setdefault("version", _INDEX_VERSION)
        return data
    except Exception as exc:
        logger.warning("signal task index load failed: %s", exc)
        return {"version": _INDEX_VERSION, "tasks": {}}


def _save_index_unlocked(index: Dict[str, Any]) -> None:
    index["version"] = _INDEX_VERSION
    index["updatedAt"] = time.time()
    _atomic_write_json(_INDEX_PATH, index)


def _load_task_unlocked(task_id: str) -> Optional[SignalTaskRecord]:
    path = _task_path(task_id)
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, dict):
            return None
        return SignalTaskRecord.from_dict(data)
    except Exception as exc:
        logger.warning("signal task load failed (%s): %s", task_id, exc)
        return None


def _save_task_unlocked(record: SignalTaskRecord) -> None:
    _atomic_write_json(_task_path(record.taskId), record.to_dict())
    index = _load_index_unlocked()
    tasks = index.setdefault("tasks", {})
    tasks[record.taskId] = record.to_meta().to_dict()
    _save_index_unlocked(index)


def _create_task_sync(symbol: str, model: str) -> str:
    _ensure_dirs()
    task_id = uuid.uuid4().hex
    now = time.time()
    record = SignalTaskRecord(
        taskId=task_id,
        symbol=symbol,
        model=model,
        status=SignalTaskStatus.PENDING.value,
        createdAt=now,
        updatedAt=now,
    )
    with _lock:
        _save_task_unlocked(record)
    return task_id


def _get_task_sync(task_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        record = _load_task_unlocked(task_id)
    return record.to_dict() if record else None


def _update_task_sync(task_id: str, **fields: Any) -> None:
    with _lock:
        record = _load_task_unlocked(task_id)
        if not record:
            logger.warning("signal task update skipped, not found: %s", task_id)
            return
        for key, value in fields.items():
            if hasattr(record, key):
                setattr(record, key, value)
        record.updatedAt = time.time()
        _save_task_unlocked(record)


def _list_recent_sync(limit: int = 50, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    with _lock:
        index = _load_index_unlocked()
        tasks = index.get("tasks") or {}
        rows = list(tasks.values()) if isinstance(tasks, dict) else []
    rows.sort(key=lambda item: float(item.get("updatedAt") or 0), reverse=True)
    if symbol:
        sym = symbol.strip().upper()
        rows = [row for row in rows if str(row.get("symbol") or "").upper() == sym]
    return rows[: max(1, limit)]


async def create_task(symbol: str, model: str) -> str:
    return await asyncio.to_thread(_create_task_sync, symbol, model)


async def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    return await asyncio.to_thread(_get_task_sync, task_id)


async def update_task_running(task_id: str) -> None:
    await asyncio.to_thread(
        _update_task_sync,
        task_id,
        status=SignalTaskStatus.RUNNING.value,
    )


async def update_task_done(task_id: str, result: Dict[str, Any]) -> None:
    await asyncio.to_thread(
        _update_task_sync,
        task_id,
        status=SignalTaskStatus.DONE.value,
        result=result,
        error=None,
    )


async def update_task_failed(task_id: str, error: str) -> None:
    await asyncio.to_thread(
        _update_task_sync,
        task_id,
        status=SignalTaskStatus.FAILED.value,
        error=error,
    )


async def list_recent_tasks(limit: int = 50, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    """List recent task metadata from index.json (no result payloads)."""
    return await asyncio.to_thread(_list_recent_sync, limit, symbol)
