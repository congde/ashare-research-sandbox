"""
Activity Tracking (§5.11)

Records runtime activity events for audit and replay.

ActivityTracker.touch() is called for every meaningful operation:
  - LLM API call initiated / completed
  - Tool execution started / finished
  - SSE chunk emitted

When the K8s gateway kills the pod due to timeout, it can call
get_summary() first to log what the agent was doing — enabling
production operators to distinguish between:
  • "Agent is waiting for LLM response" (LLM latency issue)
  • "Agent is executing a slow tool" (tool timeout issue)
  • "Agent has been idle" (logic bug / deadlock)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class ActivitySnapshot:
    """A point-in-time snapshot of agent activity, used in diagnostic logs."""

    last_activity_desc: str
    seconds_since_activity: float
    current_tool: Optional[str]
    api_call_count: int
    tool_call_count: int
    session_id: str


class ActivityTracker:
    """
    Lightweight in-process activity tracker.

    Thread-safe for read operations; write operations (touch/set_tool/clear_tool)
    are idempotent and safe to call from async contexts without locking since
    CPython GIL guarantees atomic attribute assignment.

    Usage::

        tracker = ActivityTracker(session_id="sess-123")

        tracker.touch("LLM call initiated")
        tracker.set_current_tool("web_search")
        # ... tool executes ...
        tracker.clear_current_tool()
        tracker.touch("LLM call completed")

        summary = tracker.get_summary()
        logger.info("Agent status: %s", summary)
    """

    def __init__(self, session_id: str = ""):
        self._session_id = session_id
        self._last_ts: float = time.time()
        self._last_desc: str = "initialised"
        self._current_tool: Optional[str] = None
        self._api_call_count: int = 0
        self._tool_call_count: int = 0

    # ── Write ──────────────────────────────────────────────────────────────────

    def touch(self, desc: str) -> None:
        """
        Record that meaningful work is happening right now.

        Call this for every significant event: API call, tool execution,
        SSE stream chunk, compaction trigger, etc.

        Parameters
        ----------
        desc : str
            Human-readable description of the current activity
            (shown in diagnostic logs when the process is killed by timeout).
        """
        self._last_ts = time.time()
        self._last_desc = desc

    def set_current_tool(self, tool_name: str) -> None:
        """Mark that a tool is currently executing."""
        self._current_tool = tool_name
        self._tool_call_count += 1
        self.touch(f"executing tool: {tool_name}")

    def clear_current_tool(self) -> None:
        """Clear the current-tool marker after execution completes."""
        self._current_tool = None

    def record_api_call(self) -> None:
        """Increment the LLM API call counter."""
        self._api_call_count += 1
        self.touch(f"LLM API call #{self._api_call_count}")

    # ── Read ───────────────────────────────────────────────────────────────────

    def get_summary(self) -> ActivitySnapshot:
        """
        Return a snapshot of current activity state.

        Called by timeout handlers and health-check endpoints to produce
        structured diagnostics without requiring access to internal state.
        """
        return ActivitySnapshot(
            last_activity_desc=self._last_desc,
            seconds_since_activity=time.time() - self._last_ts,
            current_tool=self._current_tool,
            api_call_count=self._api_call_count,
            tool_call_count=self._tool_call_count,
            session_id=self._session_id,
        )

    def is_stale(self, timeout_seconds: float) -> bool:
        """
        Return True if no activity has been recorded for *timeout_seconds*.

        Used by stale-stream detection in the ConversationRuntime.
        """
        return (time.time() - self._last_ts) > timeout_seconds

    @property
    def seconds_since_last_activity(self) -> float:
        return time.time() - self._last_ts

    @property
    def api_call_count(self) -> int:
        return self._api_call_count

    @property
    def tool_call_count(self) -> int:
        return self._tool_call_count

    @property
    def current_tool(self) -> Optional[str]:
        return self._current_tool

    def __repr__(self) -> str:
        idle = self.seconds_since_last_activity
        return (
            f"ActivityTracker(session={self._session_id!r}, "
            f"idle={idle:.1f}s, "
            f"api_calls={self._api_call_count}, "
            f"tool_calls={self._tool_call_count})"
        )
