"""PR-D3 · Per-task remaining-budget tracker (动态Plan化迁移方案 decision #7).

Purpose
-------
Dynamic task mode (PR-D3) lets the LLM expand the DAG via
``spawn_sibling_milestone``. Without a budget gate, an over-eager LLM
could fan out indefinitely — burning all remaining USD before the
ROOT acceptance fires. This module tracks ``consumed`` vs ``total`` for
each task and lets the spawn tool reject requests that would exceed
the cap (decision #7 — "real-time tracking" not "lump sum to ROOT").

The LLM also sees a snapshot in its system prompt's dynamic suffix so
it can plan its remaining scope — Claude Code parity for "tell the LLM
its budget so it self-regulates".

Design choices
--------------
- Mutable dataclass + per-task registry (mirrors steering / todo_list /
  plan_mode patterns). Thread-safe via locks; concurrent agent.run()
  calls within the same task converge on one TaskBudget instance.
- ``consume`` clamps remaining ≥ 0 so callers can call from a hot path
  without checking — over-consumption logs but doesn't break the run.
- Negative cost / negative estimate are defensive guards: upstream bugs
  shouldn't be able to grant infinite budget by passing -1.0.
- Fail-closed default: ``get_budget`` for an unseen task returns
  ``total=0`` so any spawn attempt denies — explicit ``get_budget(task_id,
  total_usd=...)`` initialisation is required for the registry to allow
  spending.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class TaskBudget:
    """Per-task budget envelope tracking consumed vs total USD."""

    total_usd: float
    consumed_usd: float = 0.0
    _lock: threading.Lock = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.total_usd < 0:
            raise ValueError("total_usd must be >= 0")
        # Defensive: caller may pass consumed=0 default; clamp upper bound
        if self.consumed_usd < 0:
            self.consumed_usd = 0.0
        if self.consumed_usd > self.total_usd:
            self.consumed_usd = self.total_usd
        # Per-instance lock (replaces the dataclass field default)
        object.__setattr__(self, "_lock", threading.Lock())

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.total_usd - self.consumed_usd)

    def can_spawn(self, estimated_cost: float) -> bool:
        """True iff there's room for ``estimated_cost`` AND remaining > 0.

        Defensive: rejects negative estimates (would otherwise pass any
        check trivially) and zero-remaining tasks (no further spawns
        even for free items — defends against pathological loops).
        """
        try:
            est = float(estimated_cost)
        except (TypeError, ValueError):
            return False
        if est < 0:
            return False
        with self._lock:
            remaining = max(0.0, self.total_usd - self.consumed_usd)
        if remaining <= 0:
            return False
        return remaining >= est

    def consume(self, cost: float) -> None:
        """Add ``cost`` to consumed (clamped to [0, total]).

        Negative costs are clamped to 0 — they would only happen via an
        upstream bug; refunding "spent" budget mid-task would let a
        compromised LLM gain unbounded spend by passing -X.
        """
        try:
            c = float(cost)
        except (TypeError, ValueError):
            return
        if c <= 0:
            return
        with self._lock:
            self.consumed_usd = min(self.total_usd, self.consumed_usd + c)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "total_usd": self.total_usd,
                "consumed_usd": self.consumed_usd,
                "remaining_usd": max(0.0, self.total_usd - self.consumed_usd),
            }


# ── Per-task registry ───────────────────────────────────────────────────────

_REGISTRY: Dict[str, TaskBudget] = {}
_REGISTRY_LOCK = threading.Lock()


def get_budget(task_id: str, total_usd: Optional[float] = None) -> TaskBudget:
    """Return the :class:`TaskBudget` for *task_id*.

    First-call ``total_usd`` initialises the cap; subsequent calls
    ignore the parameter and return the existing instance (so the
    spawn tool can read the budget without needing the original total
    handy).

    Fail-closed: if the task hasn't been initialised and no
    ``total_usd`` is supplied, returns a fresh ``TaskBudget(total=0)``
    so all spawn attempts deny.
    """
    if not task_id:
        raise ValueError("task_id is required")
    with _REGISTRY_LOCK:
        existing = _REGISTRY.get(task_id)
        if existing is not None:
            return existing
        budget = TaskBudget(total_usd=float(total_usd) if total_usd is not None else 0.0)
        _REGISTRY[task_id] = budget
        return budget


def clear_budget(task_id: str) -> None:
    """Drop the registry entry for *task_id* (used on task completion)."""
    with _REGISTRY_LOCK:
        _REGISTRY.pop(task_id, None)


def reset_registry() -> None:
    """Drop all registry entries — primarily for tests."""
    with _REGISTRY_LOCK:
        _REGISTRY.clear()


# ── System-prompt rendering ─────────────────────────────────────────────────


def render_budget_state(budget: Optional[TaskBudget]) -> Optional[str]:
    """Render a one-section markdown block for the system prompt.

    Returns ``None`` when ``budget`` is None or its total is 0 (no
    budget configured). The LLM sees remaining USD so it can self-
    regulate spawn calls.
    """
    if budget is None or budget.total_usd <= 0:
        return None
    snap = budget.snapshot()
    return (
        "## Task Budget\n"
        f"  - total: ${snap['total_usd']:.4f}\n"
        f"  - consumed: ${snap['consumed_usd']:.4f}\n"
        f"  - remaining: ${snap['remaining_usd']:.4f}\n"
        "  Spawn new milestones only when their estimated cost fits "
        "in remaining."
    )


__all__ = [
    "TaskBudget",
    "clear_budget",
    "get_budget",
    "render_budget_state",
    "reset_registry",
]
