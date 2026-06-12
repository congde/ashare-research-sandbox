# -*- coding: utf-8 -*-
"""
DAO for LLM signal analysis async tasks.

Persisted locally under data/llm_signal_tasks/ (see dao.local.signal_task_store).
"""

from dao.local.signal_task_store import (
    SignalTaskMeta,
    SignalTaskRecord,
    SignalTaskStatus,
    create_task,
    get_task,
    list_recent_tasks,
    update_task_done,
    update_task_failed,
    update_task_running,
)

__all__ = [
    "SignalTaskMeta",
    "SignalTaskRecord",
    "SignalTaskStatus",
    "create_task",
    "get_task",
    "list_recent_tasks",
    "update_task_done",
    "update_task_failed",
    "update_task_running",
]
