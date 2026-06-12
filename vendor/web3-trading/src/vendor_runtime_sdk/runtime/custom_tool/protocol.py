# -*- coding: utf-8 -*-
"""
Custom Tool Protocol — §6.5 (Phase 4 P1)

Event pass-through model for tools that execute on the **client** (frontend/App),
not inside the Runtime.

Flow:
  Agent Runtime  ─── agent.custom_tool_use  ──▶  Client (frontend)
  Agent Runtime  ◀── user.custom_tool_result ───  Client (frontend)

Design principles:
  - Custom Tools bypass Permission Policy (execution is client-controlled)
  - Runtime only passes `tool_use` events and receives `tool_result` events
  - The protocol is async: the Runtime suspends the agent loop until the
    client responds (or timeout fires)
  - CustomToolHandler validates event structure, manages pending state,
    and emits SSE events for the transport layer

SSE event types:
  agent.custom_tool_use     — sent to client, requesting tool execution
  user.custom_tool_result   — received from client with tool output
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# Default timeout for client to respond with a tool result
DEFAULT_TOOL_TIMEOUT = 120.0  # seconds


class CustomToolState(str, Enum):
    """State machine for a single custom tool invocation."""
    PENDING = "pending"       # awaiting client response
    COMPLETED = "completed"   # client returned a result
    TIMEOUT = "timeout"       # client did not respond in time
    ERROR = "error"           # client returned an error


@dataclass
class CustomToolUse:
    """
    Event sent from Runtime → Client requesting tool execution.

    SSE event type: agent.custom_tool_use
    """

    tool_use_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    tool_name: str = ""
    tool_input: Dict[str, Any] = field(default_factory=dict)
    session_id: str = ""
    created_at: float = field(default_factory=time.time)

    def validate(self) -> None:
        if not self.tool_name:
            raise ValueError("tool_name is required")
        if not self.session_id:
            raise ValueError("session_id is required")

    def to_sse_dict(self) -> Dict[str, Any]:
        """Format for SSE transport."""
        return {
            "type": "agent.custom_tool_use",
            "tool_use_id": self.tool_use_id,
            "tool_name": self.tool_name,
            "tool_input": self.tool_input,
            "session_id": self.session_id,
        }


@dataclass
class CustomToolResult:
    """
    Event sent from Client → Runtime with tool execution output.

    SSE event type: user.custom_tool_result
    """

    tool_use_id: str = ""
    content: str = ""
    is_error: bool = False
    received_at: float = field(default_factory=time.time)

    def validate(self) -> None:
        if not self.tool_use_id:
            raise ValueError("tool_use_id is required")

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> CustomToolResult:
        return cls(
            tool_use_id=d.get("tool_use_id", ""),
            content=d.get("content", ""),
            is_error=d.get("is_error", False),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_use_id": self.tool_use_id,
            "content": self.content,
            "is_error": self.is_error,
            "received_at": self.received_at,
        }


@dataclass
class _PendingTool:
    """Internal tracker for a pending custom tool invocation."""
    tool_use: CustomToolUse
    state: CustomToolState = CustomToolState.PENDING
    result: Optional[CustomToolResult] = None
    future: Optional[asyncio.Future] = None


class CustomToolHandler:
    """
    Manages the lifecycle of custom tool invocations.

    The handler:
      1. Creates a CustomToolUse event and emits it via the SSE callback
      2. Suspends via an asyncio.Future until the client responds
      3. Validates the incoming CustomToolResult
      4. Returns the result to the caller (agent loop)

    Usage::

        handler = CustomToolHandler(
            session_id="sess-123",
            on_emit=sse_callback,
            timeout=120.0,
        )
        # Agent decides to call a custom tool:
        result = await handler.invoke("browser_screenshot", {"url": "..."})
        # Later, client sends back the result via HTTP/WS:
        handler.receive_result(CustomToolResult(tool_use_id="abc", content="<base64>"))
    """

    def __init__(
        self,
        session_id: str,
        on_emit: Optional[Callable[[Dict[str, Any]], None]] = None,
        timeout: float = DEFAULT_TOOL_TIMEOUT,
    ) -> None:
        self._session_id = session_id
        self._on_emit = on_emit
        self._timeout = timeout
        self._pending: Dict[str, _PendingTool] = {}
        self._max_pending: int = 1000  # cap to prevent unbounded growth

    @property
    def pending_count(self) -> int:
        return sum(1 for p in self._pending.values() if p.state == CustomToolState.PENDING)

    def _cleanup_completed(self) -> None:
        """Remove completed/timed-out/error entries to prevent unbounded growth."""
        to_remove = [
            tid for tid, p in self._pending.items()
            if p.state in (CustomToolState.COMPLETED, CustomToolState.TIMEOUT, CustomToolState.ERROR)
        ]
        for tid in to_remove:
            del self._pending[tid]

    async def invoke(
        self, tool_name: str, tool_input: Dict[str, Any]
    ) -> CustomToolResult:
        """
        Send a custom tool invocation to the client and await the result.

        Returns CustomToolResult on success; on timeout returns a synthetic
        error result with is_error=True.
        """
        # Evict completed entries to prevent unbounded growth
        if len(self._pending) >= self._max_pending:
            self._cleanup_completed()

        tool_use = CustomToolUse(
            tool_name=tool_name,
            tool_input=tool_input,
            session_id=self._session_id,
        )
        tool_use.validate()

        loop = asyncio.get_running_loop()
        future: asyncio.Future[CustomToolResult] = loop.create_future()

        pending = _PendingTool(tool_use=tool_use, future=future)
        self._pending[tool_use.tool_use_id] = pending

        # Emit SSE event to client
        if self._on_emit:
            self._on_emit(tool_use.to_sse_dict())
        logger.debug(
            "CustomToolHandler[%s]: emitted tool_use id=%s name=%s",
            self._session_id, tool_use.tool_use_id, tool_name,
        )

        try:
            result = await asyncio.wait_for(future, timeout=self._timeout)
            # Don't override state if receive_result already set it (e.g., ERROR)
            if pending.state == CustomToolState.PENDING:
                pending.state = CustomToolState.COMPLETED
            pending.result = result
            return result
        except asyncio.TimeoutError:
            pending.state = CustomToolState.TIMEOUT
            logger.warning(
                "CustomToolHandler[%s]: tool_use %s timed out after %.1fs",
                self._session_id, tool_use.tool_use_id, self._timeout,
            )
            return CustomToolResult(
                tool_use_id=tool_use.tool_use_id,
                content=f"Custom tool '{tool_name}' timed out after {self._timeout}s",
                is_error=True,
            )

    def receive_result(self, result: CustomToolResult) -> bool:
        """
        Process an incoming tool result from the client.

        Returns True if matched to a pending invocation; False if
        the tool_use_id is unknown or already completed.
        """
        result.validate()
        pending = self._pending.get(result.tool_use_id)
        if pending is None:
            logger.warning(
                "CustomToolHandler[%s]: received result for unknown tool_use_id=%s",
                self._session_id, result.tool_use_id,
            )
            return False

        if pending.state != CustomToolState.PENDING:
            logger.warning(
                "CustomToolHandler[%s]: received result for non-pending tool_use_id=%s (state=%s)",
                self._session_id, result.tool_use_id, pending.state.value,
            )
            return False

        if result.is_error:
            pending.state = CustomToolState.ERROR
        else:
            pending.state = CustomToolState.COMPLETED
        pending.result = result

        if pending.future and not pending.future.done():
            pending.future.set_result(result)
        return True

    def get_state(self, tool_use_id: str) -> Optional[CustomToolState]:
        """Return the state of a pending tool invocation."""
        pending = self._pending.get(tool_use_id)
        return pending.state if pending else None
