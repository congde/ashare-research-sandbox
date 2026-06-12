"""PR-D1 · Per-task LLM-managed task list (Claude Code TodoWrite parity).

Mirrors :mod:`runtime.steering.queue` design: per-``task_id`` registry, in-memory,
thread-safe.  Different from steering in that ``set()`` is *replace* semantics
(LLM submits the full list each turn), not append.

Why per-task and not per-milestone?
-----------------------------------
Decision #8 in ``docs/Coder-Agent动态Plan化迁移方案.md``: cross-milestone
visibility — the LLM sees its task-level scratchpad continuously, matching
Claude Code's session-scoped semantics.  Items left ``in_progress`` when
a milestone ends remain visible to the next milestone so the LLM can resume
or mark them done.

Boundaries enforced here:
* ``MAX_ITEMS_PER_TASK`` items per task  (50 — matches Claude Code's soft cap)
* ``MAX_CONTENT_CHARS`` chars per item content (200 — short enough for
  the system prompt to render the full list without bloating cache)
* ``status`` ∈ {pending, in_progress, completed} (claw-code schema)
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from typing import Dict, List, Literal, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Boundary constants ──────────────────────────────────────────────────────
#
# Sprint 10 PR-3 (T1.3) — ``MAX_ITEMS_PER_TASK`` is operator-tunable via
# env.  Default 50 preserves prior behaviour; ceiling 1000 prevents an
# operator from accidentally enabling unbounded LLM list growth.

_MAX_ITEMS_CEILING: int = 1000


def _resolve_max_items_per_task() -> int:
    raw = os.environ.get("RUNTIME_TODO_MAX_ITEMS_PER_TASK", "").strip()
    if not raw:
        return 50
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "RUNTIME_TODO_MAX_ITEMS_PER_TASK=%r not int; using default 50",
            raw,
        )
        return 50
    if value <= 0:
        logger.warning(
            "RUNTIME_TODO_MAX_ITEMS_PER_TASK=%d must be > 0; using default 50",
            value,
        )
        return 50
    if value > _MAX_ITEMS_CEILING:
        logger.warning(
            "RUNTIME_TODO_MAX_ITEMS_PER_TASK=%d exceeds ceiling %d; clamping",
            value, _MAX_ITEMS_CEILING,
        )
        return _MAX_ITEMS_CEILING
    return value


MAX_ITEMS_PER_TASK: int = _resolve_max_items_per_task()
MAX_CONTENT_CHARS: int = 200

TodoStatus = Literal["pending", "in_progress", "completed"]
_VALID_STATUSES: Tuple[str, ...] = ("pending", "in_progress", "completed")


# ── TodoItem ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TodoItem:
    """One row in the LLM's task list.

    The schema matches Claude Code's TodoWrite tool exactly:
    ``content`` is the imperative form ("Wire up DAO"); ``active_form`` is
    the present-continuous form shown while in_progress ("Wiring up DAO").
    Frozen because the registry is shared across threads and we want
    accidental in-place mutation to fail loudly.
    """

    content: str
    active_form: str
    status: TodoStatus

    def __post_init__(self) -> None:
        if not self.content or not self.content.strip():
            raise ValueError("todo content must be non-empty")
        if len(self.content) > MAX_CONTENT_CHARS:
            raise ValueError(
                f"todo content exceeds {MAX_CONTENT_CHARS} chars (got {len(self.content)})"
            )
        if not self.active_form or not self.active_form.strip():
            raise ValueError("todo active_form must be non-empty")
        if self.status not in _VALID_STATUSES:
            raise ValueError(
                f"todo status must be one of {_VALID_STATUSES} (got {self.status!r})"
            )


# ── TaskTodoList ────────────────────────────────────────────────────────────


class TaskTodoList:
    """Per-task ordered list with replace semantics.

    ``set(items)`` overwrites previous state — the LLM submits the *full*
    list every TodoWrite call (claw-code parity).  ``get()`` returns an
    immutable tuple snapshot for safe rendering.
    """

    def __init__(self) -> None:
        self._items: Tuple[TodoItem, ...] = ()
        self._lock = threading.Lock()

    def set(self, items: List[TodoItem]) -> None:
        # Sprint 10 PR-3 — resolve live so an operator raising the
        # cap mid-process applies on the next set() call.
        max_items = _resolve_max_items_per_task()
        if len(items) > max_items:
            raise ValueError(
                f"todo list exceeds cap (got {len(items)}, max {max_items})"
            )
        # Defensive copy so caller-side mutation can't sneak in via the
        # backing tuple after we've stored it.
        snapshot = tuple(items)
        with self._lock:
            self._items = snapshot

    def get(self) -> Tuple[TodoItem, ...]:
        with self._lock:
            return self._items

    def pending_count(self) -> int:
        return sum(1 for i in self.get() if i.status == "pending")

    def in_progress_count(self) -> int:
        return sum(1 for i in self.get() if i.status == "in_progress")

    def completed_count(self) -> int:
        return sum(1 for i in self.get() if i.status == "completed")


# ── Per-task registry ───────────────────────────────────────────────────────

_REGISTRY: Dict[str, TaskTodoList] = {}
_REGISTRY_LOCK = threading.Lock()


def get_todo_list(task_id: str) -> TaskTodoList:
    """Return the :class:`TaskTodoList` for *task_id*, creating one on first access."""
    if not task_id:
        raise ValueError("task_id is required")
    with _REGISTRY_LOCK:
        lst = _REGISTRY.get(task_id)
        if lst is None:
            lst = TaskTodoList()
            _REGISTRY[task_id] = lst
        return lst


def clear_todo_list(task_id: str) -> None:
    """Drop the registry entry for *task_id* (used on task completion)."""
    with _REGISTRY_LOCK:
        _REGISTRY.pop(task_id, None)


def reset_registry() -> None:
    """Drop all registry entries — primarily for tests."""
    with _REGISTRY_LOCK:
        _REGISTRY.clear()


# ── System-prompt rendering ─────────────────────────────────────────────────


def render_todo_state(todo: TaskTodoList) -> Optional[str]:
    """Render the task list as a system-prompt addendum.

    Returns ``None`` when the list is empty (zero-cost fast path — no
    section is added to the prompt).  Otherwise renders a markdown
    bullet list with status markers the LLM can scan quickly.
    """
    items = todo.get()
    if not items:
        return None

    lines: List[str] = ["## Current Task List"]
    for item in items:
        if item.status == "completed":
            lines.append(f"  - [✓] {item.content} (completed)")
        elif item.status == "in_progress":
            # Show both forms — content for stable identity, active_form for
            # the verb a reader would say out loud.
            lines.append(
                f"  - [→] {item.content} — {item.active_form} (in_progress)"
            )
        else:
            lines.append(f"  - [ ] {item.content} (pending)")
    return "\n".join(lines)


__all__ = [
    "MAX_CONTENT_CHARS",
    "MAX_ITEMS_PER_TASK",
    "TaskTodoList",
    "TodoItem",
    "TodoStatus",
    "clear_todo_list",
    "get_todo_list",
    "render_todo_state",
    "reset_registry",
]
