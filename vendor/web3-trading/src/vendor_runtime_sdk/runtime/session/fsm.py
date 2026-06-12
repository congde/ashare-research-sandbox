"""
Session FSM — 6-state finite state machine (§5.4)

States: idle, running, requires_approval, compacted, forked, failed, timeout, terminated
Transitions enforce valid paths; invalid transitions raise IllegalTransitionError.
"""

from __future__ import annotations

from enum import Enum
from typing import FrozenSet


class SessionState(str, Enum):
    """All valid session states."""

    IDLE = "idle"
    RUNNING = "running"
    REQUIRES_APPROVAL = "requires_approval"
    COMPACTED = "compacted"
    FORKED = "forked"
    FAILED = "failed"
    TIMEOUT = "timeout"
    TERMINATED = "terminated"


class IllegalTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""

    def __init__(self, from_state: SessionState, to_state: SessionState):
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"Illegal session state transition: {from_state.value!r} → {to_state.value!r}")


# ── Terminal states — no further transitions allowed ──────────────────────────
TERMINAL_STATES: FrozenSet[SessionState] = frozenset(
    {
        SessionState.TERMINATED,
    }
)

# ── Valid transitions (from_state → set of allowed to_states) ─────────────────
# Design rules (§5.4):
#   • Any non-terminal state may transition to TERMINATED (user cancel / error)
#   • FAILED / TIMEOUT are non-terminal holding states — human confirmation needed
#     before archiving; they do NOT auto-transition to TERMINATED here
#   • COMPACTED / FORKED represent structural states; they can resume to RUNNING
_TRANSITIONS: dict[SessionState, FrozenSet[SessionState]] = {
    SessionState.IDLE: frozenset(
        {
            SessionState.RUNNING,
            SessionState.TERMINATED,
        }
    ),
    SessionState.RUNNING: frozenset(
        {
            SessionState.REQUIRES_APPROVAL,
            SessionState.COMPACTED,
            SessionState.FORKED,
            SessionState.FAILED,
            SessionState.TIMEOUT,
            SessionState.TERMINATED,
        }
    ),
    SessionState.REQUIRES_APPROVAL: frozenset(
        {
            SessionState.RUNNING,  # approved
            SessionState.TERMINATED,  # rejected or expired
        }
    ),
    SessionState.COMPACTED: frozenset(
        {
            SessionState.RUNNING,
            SessionState.TERMINATED,
        }
    ),
    SessionState.FORKED: frozenset(
        {
            SessionState.RUNNING,
            SessionState.TERMINATED,
        }
    ),
    SessionState.FAILED: frozenset(
        {
            SessionState.TERMINATED,
        }
    ),
    SessionState.TIMEOUT: frozenset(
        {
            SessionState.TERMINATED,
        }
    ),
    SessionState.TERMINATED: frozenset(),  # terminal — no outbound transitions
}


class SessionFSM:
    """
    Finite state machine governing a single Session's lifecycle.

    Usage::

        fsm = SessionFSM()                  # starts in IDLE
        fsm.transition(SessionState.RUNNING)
        fsm.transition(SessionState.TERMINATED)

    Raises ``IllegalTransitionError`` on invalid paths so callers never
    silently corrupt session state.
    """

    def __init__(self, initial: SessionState = SessionState.IDLE):
        self._state = initial

    # ── Properties ─────────────────────────────────────────────────────────────

    @property
    def state(self) -> SessionState:
        return self._state

    @property
    def is_terminal(self) -> bool:
        return self._state in TERMINAL_STATES

    @property
    def is_running(self) -> bool:
        return self._state == SessionState.RUNNING

    @property
    def requires_approval(self) -> bool:
        return self._state == SessionState.REQUIRES_APPROVAL

    # ── Transitions ────────────────────────────────────────────────────────────

    def transition(self, to: SessionState) -> None:
        """
        Advance the FSM to *to*.

        Raises
        ------
        IllegalTransitionError
            If the transition is not allowed from the current state.
        """
        allowed = _TRANSITIONS.get(self._state, frozenset())
        if to not in allowed:
            raise IllegalTransitionError(self._state, to)
        self._state = to

    def can_transition(self, to: SessionState) -> bool:
        """Return True if the transition to *to* is currently legal."""
        return to in _TRANSITIONS.get(self._state, frozenset())

    # ── Convenience helpers ────────────────────────────────────────────────────

    def mark_running(self) -> None:
        self.transition(SessionState.RUNNING)

    def mark_requires_approval(self) -> None:
        self.transition(SessionState.REQUIRES_APPROVAL)

    def mark_approved(self) -> None:
        """Resume from requires_approval after human approves."""
        self.transition(SessionState.RUNNING)

    def mark_rejected(self) -> None:
        """Terminate from requires_approval after human rejects."""
        self.transition(SessionState.TERMINATED)

    def mark_compacted(self) -> None:
        self.transition(SessionState.COMPACTED)

    def mark_forked(self) -> None:
        self.transition(SessionState.FORKED)

    def mark_failed(self) -> None:
        if self.can_transition(SessionState.FAILED):
            self.transition(SessionState.FAILED)
        else:
            # Already in a terminal or approval state; force-terminate instead
            self.transition(SessionState.TERMINATED)

    def mark_timeout(self) -> None:
        if self.can_transition(SessionState.TIMEOUT):
            self.transition(SessionState.TIMEOUT)
        else:
            self.transition(SessionState.TERMINATED)

    def mark_terminated(self) -> None:
        if not self.is_terminal:
            self.transition(SessionState.TERMINATED)

    def __repr__(self) -> str:
        return f"SessionFSM(state={self._state.value!r})"


# ── Multi-child aggregation (§5.4 State Lattice) ──────────────────────────────

# Priority order for fail-closed aggregation (higher index = higher priority)
_PRIORITY: dict[SessionState, int] = {
    SessionState.TERMINATED: 0,  # mapped from "success" for aggregation
    SessionState.IDLE: 1,
    SessionState.RUNNING: 2,
    SessionState.COMPACTED: 2,
    SessionState.FORKED: 2,
    SessionState.TIMEOUT: 3,
    SessionState.REQUIRES_APPROVAL: 4,
    SessionState.FAILED: 5,
}


def aggregate_child_states(child_states: list[SessionState]) -> SessionState:
    """
    Aggregate multiple child Session states into a single parent state.

    Implements the fail-closed priority lattice from §5.4:
    ``failed > requires_approval > timeout > running > idle > success``

    A child that completed successfully is represented as TERMINATED here
    (which maps to the lowest priority "success" in aggregation context).

    Returns
    -------
    SessionState
        The aggregated parent state.  Callers should map ``TERMINATED`` back
        to ``terminated + stop_reason="end_turn"`` if *all* children succeeded.
    """
    if not child_states:
        return SessionState.TERMINATED

    return max(child_states, key=lambda s: _PRIORITY.get(s, 0))
