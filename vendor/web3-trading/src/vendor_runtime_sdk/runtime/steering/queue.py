"""D1 · Mid-turn steering queue (docs/Coder-Agent长程自主化技术方案.md §5.4.D1).

Purpose
-------
Let a human observer inject a follow-up directive into a running milestone
without aborting the current tool call.  The queue collects messages; the
driver drains them at the next LLM call boundary and splices them into the
system note for that turn.

The queue is per-task (keyed by ``task_id``) so multiple concurrent tasks
do not share steering state.  In-memory only — cross-pod coordination is
out of scope for V1 (single-pod or best-effort across pods is acceptable
because steering is an *advisory* directive, not correctness-critical).

Boundaries enforced here (plan §5.4.D1):
* Max :data:`MAX_MESSAGES_PER_MILESTONE` messages per milestone (drain resets the cap).
* Max :data:`MAX_MESSAGE_CHARS` per message.
* Steering can't change ``touched_paths_glob`` / ``budget_usd`` — those remain
  TaskGoal constraints; the queue only carries free-form text.
* Emergency stop is still Ctrl+C / ``/cancel`` — steering never cancels.

Telemetry hook: ``TelemetryRecorder.record_turn(TurnMetrics(steering_messages_consumed=N))``
bumps the §8 counter once the driver drains and consumes.  Span:
``SpanType.STEERING_INJECTED``.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

logger = logging.getLogger(__name__)


# ── Boundary constants (§5.4.D1) ─────────────────────────────────────────────

MAX_MESSAGES_PER_MILESTONE: int = 10
MAX_MESSAGE_CHARS: int = 512


Priority = Literal["normal", "high"]


@dataclass
class SteeringMessage:
    """One steering directive pushed by a human operator."""

    text: str
    priority: Priority = "normal"
    timestamp: float = field(default_factory=time.time)


class SteeringQueue:
    """Per-task FIFO of steering messages with push caps.

    The class is intentionally tiny — it does NOT decide what to do with
    drained messages; that's the driver's responsibility.  Thread-safe.
    """

    def __init__(self) -> None:
        self._buf: List[SteeringMessage] = []
        self._lock = threading.Lock()

    def push(self, text: str, *, priority: Priority = "normal") -> SteeringMessage:
        """Append a directive; raise on cap violations.

        Raises:
            ValueError:  empty text or text longer than :data:`MAX_MESSAGE_CHARS`.
            OverflowError:  more than :data:`MAX_MESSAGES_PER_MILESTONE` undrained messages.
        """
        if not text or not text.strip():
            raise ValueError("steering message text must be non-empty")
        if len(text) > MAX_MESSAGE_CHARS:
            raise ValueError(
                f"steering message exceeds {MAX_MESSAGE_CHARS} char limit (got {len(text)})"
            )
        msg = SteeringMessage(text=text, priority=priority)
        with self._lock:
            if len(self._buf) >= MAX_MESSAGES_PER_MILESTONE:
                raise OverflowError(
                    f"steering queue at milestone cap ({MAX_MESSAGES_PER_MILESTONE}); "
                    "wait for the agent to drain before injecting more"
                )
            self._buf.append(msg)
        return msg

    def drain(self) -> List[SteeringMessage]:
        """Return and clear all buffered messages (FIFO)."""
        with self._lock:
            out = self._buf
            self._buf = []
        return out

    def peek_count(self) -> int:
        with self._lock:
            return len(self._buf)


# ── Per-task registry ────────────────────────────────────────────────────────

_REGISTRY: Dict[str, SteeringQueue] = {}
_REGISTRY_LOCK = threading.Lock()


def get_queue(task_id: str) -> SteeringQueue:
    """Return the :class:`SteeringQueue` for *task_id*, creating one on first access."""
    if not task_id:
        raise ValueError("task_id is required")
    with _REGISTRY_LOCK:
        q = _REGISTRY.get(task_id)
        if q is None:
            q = SteeringQueue()
            _REGISTRY[task_id] = q
        return q


def clear_queue(task_id: str) -> None:
    """Drop the registry entry for *task_id* (used on milestone / task completion)."""
    with _REGISTRY_LOCK:
        _REGISTRY.pop(task_id, None)


def reset_registry() -> None:
    """Drop all registry entries — primarily for tests."""
    with _REGISTRY_LOCK:
        _REGISTRY.clear()


# ── System-note rendering ────────────────────────────────────────────────────


def render_steering_system_note(
    messages: Optional[List[SteeringMessage]],
) -> Optional[str]:
    """Render drained messages as a system-note addendum for the next LLM call.

    Returns ``None`` when there is nothing to render (no steering this turn).
    The format is a numbered list so the LLM can resolve references like
    "apply directive 2 first" that human operators sometimes use.
    """
    if not messages:
        return None
    lines: List[str] = [
        "User steering directives (injected during this milestone; take them "
        "into account on this turn):"
    ]
    for idx, m in enumerate(messages, 1):
        prio_tag = f" [{m.priority}]" if m.priority != "normal" else ""
        lines.append(f"  {idx}.{prio_tag} {m.text}")
    return "\n".join(lines)
