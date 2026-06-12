# -*- coding: utf-8 -*-
"""Arena paper 信号存储。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable


def _daily_path(log_dir: str, prefix: str) -> Path:
    directory = Path(log_dir)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"


def _append_jsonl(path: Path, payloads: Iterable[Dict[str, Any]]) -> Path:
    with path.open("a", encoding="utf-8") as file:
        for payload in payloads:
            file.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    return path


def append_arena_log(payload: Dict[str, Any], log_dir: str = "data/agent_arena") -> Path:
    return _append_jsonl(_daily_path(log_dir, "signals"), [payload])


def append_arena_trace_log(payload: Dict[str, Any], log_dir: str = "data/agent_arena") -> Path:
    return _append_jsonl(_daily_path(log_dir, "traces"), [payload])


def append_arena_performance_records(records: Iterable[Dict[str, Any]], log_dir: str = "data/agent_arena") -> Path:
    return _append_jsonl(_daily_path(log_dir, "performance"), records)