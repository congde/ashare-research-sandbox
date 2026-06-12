"""PR-D2 · Per-milestone LLM-driven plan-mode state.

The flag is set by :class:`agent.coder.tools.plan_mode_tools.EnterPlanModeTool`
and cleared by :class:`ExitPlanModeTool` (HITL-gated).  The driver in
``CoderAgent`` reads it between AgentLoop runs to decide whether the next
phase uses the read-only registry + plan-mode system prompt, or the full
exec-mode registry + exec prompt.

Per-milestone scope (different milestones independently enter/exit) so a
parallel DAG with two milestones can have one in plan, one in exec.
Mirrors :mod:`runtime.steering.queue` and :mod:`runtime.todo_list.registry`.

Why a mutable dataclass and not a tuple snapshot?
-------------------------------------------------
The two tools mutate the state imperatively (set active, set summary) — a
frozen snapshot would force allocate-on-every-write which buys nothing
because the registry already serialises by ``milestone_id``.  Tests use
``reset_registry()`` between cases for isolation.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum
from typing import Dict


class PlanModeRestriction(str, Enum):
    """Sprint 10 PR-6 (T2.3) — how strictly plan-mode hides mutating tools.

    The legacy plan-mode is binary: mutating tools are *hidden* from
    the LLM (filtered out of the registry).  The LLM has no way to
    "see write_file's schema and produce a coherent plan that
    references it" because write_file effectively doesn't exist
    during plan.  This causes plan ↔ exec discontinuity: the plan
    sometimes references tools that were absent at plan time and
    re-discovered at exec time, leading to plans that don't survive
    the transition.

    Two restrictions:

    * ``READ_ONLY`` (default) — legacy behaviour.  Mutating tools
      are filtered out of the registry; the LLM literally doesn't
      see them.  Conservative; preserves the prior contract.

    * ``READ_AND_VALIDATE`` — full registry exposed to the LLM, but
      the F7 enforcer denies any mutating call at runtime with
      ``plan_mode_blocked`` reason.  The LLM sees the schema, can
      plan around it, and gets a clear deny signal if it tries to
      execute.

    The ``coder_plan_mode_lattice`` toggle (default OFF) gates whether
    the new restriction is honoured.  With the toggle off all
    behaviour falls back to ``READ_ONLY``.
    """

    READ_ONLY = "read_only"
    READ_AND_VALIDATE = "read_and_validate"


@dataclass
class PlanModeState:
    """Per-milestone plan-mode flag + plan summary buffer."""

    active: bool = False
    # Captured by ExitPlanMode for the next exec-phase user-message injection
    # (``"Plan approved, proceed with: <summary>"``).  Cleared on each fresh
    # registry entry.
    summary: str = ""
    # PR-6 — gating restriction.  Default ``READ_ONLY`` preserves
    # legacy behaviour exactly so flipping the toggle without setting
    # this is byte-identical to pre-Sprint-10.  ``READ_AND_VALIDATE``
    # opts the milestone into the new lattice mode.
    restriction: PlanModeRestriction = PlanModeRestriction.READ_ONLY


# ── Per-milestone registry ──────────────────────────────────────────────────

_REGISTRY: Dict[str, PlanModeState] = {}
_REGISTRY_LOCK = threading.Lock()


def get_plan_mode(milestone_id: str) -> PlanModeState:
    """Return the :class:`PlanModeState` for *milestone_id*, creating one on first access."""
    if not milestone_id:
        raise ValueError("milestone_id is required")
    with _REGISTRY_LOCK:
        state = _REGISTRY.get(milestone_id)
        if state is None:
            state = PlanModeState()
            _REGISTRY[milestone_id] = state
        return state


def clear_plan_mode(milestone_id: str) -> None:
    """Drop the registry entry for *milestone_id* (used on milestone completion)."""
    with _REGISTRY_LOCK:
        _REGISTRY.pop(milestone_id, None)


def reset_registry() -> None:
    """Drop all registry entries — primarily for tests."""
    with _REGISTRY_LOCK:
        _REGISTRY.clear()


__all__ = [
    "PlanModeRestriction",
    "PlanModeState",
    "clear_plan_mode",
    "get_plan_mode",
    "reset_registry",
]
