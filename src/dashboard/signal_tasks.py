from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from paths import DATA_DIR

_TASK_ROOT = DATA_DIR / "llm_signal_tasks"
_TASKS_DIR = _TASK_ROOT / "tasks"
_INDEX_PATH = _TASK_ROOT / "index.json"
_lock = threading.Lock()


@dataclass
class SignalTaskRecord:
    taskId: str
    symbol: str
    model: str
    status: str
    result: dict[str, Any] | None = None
    error: str | None = None
    createdAt: float = 0.0
    updatedAt: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ensure_dirs() -> None:
    _TASKS_DIR.mkdir(parents=True, exist_ok=True)


def _task_path(task_id: str) -> Path:
    safe = "".join(ch for ch in str(task_id) if ch.isalnum())
    return _TASKS_DIR / f"{safe}.json"


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _load_index() -> dict[str, Any]:
    if not _INDEX_PATH.exists():
        return {"version": 1, "tasks": {}}
    try:
        data = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("tasks", {})
            return data
    except Exception:
        pass
    return {"version": 1, "tasks": {}}


def _save_index(index: dict[str, Any]) -> None:
    index["updatedAt"] = time.time()
    _atomic_write(_INDEX_PATH, index)


def _load_task(task_id: str) -> SignalTaskRecord | None:
    path = _task_path(task_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return SignalTaskRecord(**{k: data.get(k) for k in SignalTaskRecord.__dataclass_fields__})
    except Exception:
        return None
    return None


def _save_task(record: SignalTaskRecord) -> None:
    _atomic_write(_task_path(record.taskId), record.to_dict())
    index = _load_index()
    tasks = index.setdefault("tasks", {})
    tasks[record.taskId] = {
        "taskId": record.taskId,
        "symbol": record.symbol,
        "model": record.model,
        "status": record.status,
        "error": record.error,
        "createdAt": record.createdAt,
        "updatedAt": record.updatedAt,
    }
    _save_index(index)


def create_task(symbol: str, model: str) -> str:
    _ensure_dirs()
    task_id = uuid.uuid4().hex
    now = time.time()
    record = SignalTaskRecord(
        taskId=task_id,
        symbol=symbol.strip().upper(),
        model=model,
        status="pending",
        createdAt=now,
        updatedAt=now,
    )
    with _lock:
        _save_task(record)
    return task_id


def get_task(task_id: str) -> dict[str, Any] | None:
    with _lock:
        record = _load_task(task_id)
    return record.to_dict() if record else None


def update_task(task_id: str, **fields: Any) -> None:
    with _lock:
        record = _load_task(task_id)
        if not record:
            return
        for key, value in fields.items():
            if hasattr(record, key):
                setattr(record, key, value)
        record.updatedAt = time.time()
        _save_task(record)


def _run_task(task_id: str, symbol: str, model: str) -> None:
    from dashboard.llm_signal import run_llm_signal_analysis

    update_task(task_id, status="running")
    try:
        result = run_llm_signal_analysis(symbol, model=model)
        if result.get("ok"):
            update_task(task_id, status="done", result=result, error=None)
        else:
            update_task(task_id, status="failed", error=result.get("message") or "analysis failed")
    except Exception as exc:
        update_task(task_id, status="failed", error=str(exc))


def submit_task(symbol: str, model: str) -> dict[str, Any]:
    task_id = create_task(symbol, model)
    thread = threading.Thread(target=_run_task, args=(task_id, symbol, model), daemon=True)
    thread.start()
    return {"ok": True, "taskId": task_id, "status": "pending"}


def poll_task(task_id: str) -> dict[str, Any]:
    task = get_task(task_id)
    if not task:
        return {"ok": False, "message": "task not found"}
    status = task.get("status", "pending")
    if status == "done":
        return {"ok": True, "status": "done", "data": task.get("result") or {}}
    if status == "failed":
        return {"ok": False, "status": "failed", "message": task.get("error") or "unknown error"}
    return {"ok": True, "status": status}
