"""
Hook Protocol — base contract for lifecycle hooks (§5.13)

Built-in hooks: PreLLMCallHook, PostLLMCallHook, PostToolUseFailureHook
Custom hooks register via ConversationRuntime constructor.

Injection semantics (§5.13):
  • on_pre_llm_call returning {"context": "..."} appends the string to the
    current turn's user message — NOT to the system prompt — preserving
    prompt cache hit rates.
  • on_post_llm_call is fire-and-forget; errors are swallowed with WARN.
  • on_tool_use_failure can return a ToolResult to substitute the error result.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ── Context objects passed to hooks ────────────────────────────────────────────


@dataclass
class HookContext:
    """Immutable snapshot of runtime state passed to every hook invocation."""

    session_id: str
    workspace_id: str
    iteration: int  # 1-based, current ReAct iteration
    model: str  # model name currently in use
    is_fallback: bool  # True if a fallback model is active
    metadata: dict = field(default_factory=dict)


@dataclass
class ToolFailureContext(HookContext):
    """Extended context for on_tool_use_failure hooks."""

    tool_name: str = ""
    tool_args: dict = field(default_factory=dict)
    error_message: str = ""


# ── Hook Protocol ───────────────────────────────────────────────────────────────


@runtime_checkable
class PluginHook(Protocol):
    """
    Protocol for ConversationRuntime lifecycle hooks.

    Implement any subset of these methods — only implemented methods are called.
    All hook methods are *synchronous* to keep the runtime simple; for I/O work
    use asyncio.create_task() inside the hook body.
    """

    def on_pre_llm_call(self, context: HookContext) -> Optional[dict]:
        """
        Called immediately before each LLM API call.

        Returns
        -------
        dict | None
            If a dict with key ``"context"`` is returned, the value is
            appended to the current turn's last user message.  This is the
            *only* injection point to avoid breaking prompt cache.
            Return None to inject nothing.
        """
        ...

    def on_post_llm_call(self, context: HookContext, response_text: str) -> None:
        """
        Called after each LLM response is received.

        Suitable for logging, cost metering, and analytics.
        Errors raised here are caught and logged as WARN — they never
        abort the agent loop.
        """
        ...

    def on_session_start(self, session_id: str, workspace_id: str) -> None:
        """Called when a session begins (before the first turn)."""
        ...

    def on_session_end(self, session_id: str, workspace_id: str, stop_reason: str) -> None:
        """Called when a session ends (after the final turn)."""
        ...

    def on_tool_use_failure(
        self,
        context: ToolFailureContext,
    ) -> Optional[dict]:
        """
        Called when a tool execution raises an unhandled exception.

        Returns
        -------
        dict | None
            If a dict with ``"content"`` is returned, it replaces the error
            ToolResult injected into the conversation.
            Return None to use the default error result.
        """
        ...


# ── Hook registry / dispatcher ─────────────────────────────────────────────────


class HookDispatcher:
    """
    Runs registered hooks in registration order.

    Each hook invocation is wrapped in a try/except so a buggy hook never
    crashes the agent loop.  Only ``on_pre_llm_call`` return values are used;
    all other hooks are fire-and-forget.
    """

    def __init__(self, hooks: Optional[list] = None):
        self._hooks: list = list(hooks or [])
        self.last_hook_latency_ms: float = 0.0

    def register(self, hook) -> None:
        """Add a hook to the end of the chain."""
        self._hooks.append(hook)

    def unregister(self, hook) -> None:
        """Remove a hook (by identity)."""
        try:
            self._hooks.remove(hook)
        except ValueError:
            pass

    # ── Dispatch methods ───────────────────────────────────────────────────────

    def fire_pre_llm_call(self, context: HookContext) -> Optional[str]:
        """
        Run all on_pre_llm_call hooks and aggregate injected context strings.

        Returns the concatenated context string to append to the user message,
        or None if no hook injected anything.
        Elapsed time is recorded in ``self.last_hook_latency_ms``.
        """
        import time as _t
        _start = _t.monotonic()
        injections: list[str] = []

        for hook in self._hooks:
            method = getattr(hook, "on_pre_llm_call", None)
            if method is None:
                continue
            try:
                result = method(context)
                if isinstance(result, dict) and isinstance(result.get("context"), str):
                    injections.append(result["context"])
            except Exception as exc:
                logger.warning("on_pre_llm_call hook %r raised: %s", hook, exc)

        self.last_hook_latency_ms = (_t.monotonic() - _start) * 1000
        return "\n\n".join(injections) if injections else None

    def fire_post_llm_call(self, context: HookContext, response_text: str) -> None:
        """Fire all on_post_llm_call hooks (fire-and-forget).
        Elapsed time is recorded in ``self.last_hook_latency_ms``.
        """
        import time as _t
        _start = _t.monotonic()
        for hook in self._hooks:
            method = getattr(hook, "on_post_llm_call", None)
            if method is None:
                continue
            try:
                method(context, response_text)
            except Exception as exc:
                logger.warning("on_post_llm_call hook %r raised: %s", hook, exc)
        self.last_hook_latency_ms = (_t.monotonic() - _start) * 1000

    def fire_session_start(self, session_id: str, workspace_id: str) -> None:
        for hook in self._hooks:
            method = getattr(hook, "on_session_start", None)
            if method is None:
                continue
            try:
                method(session_id, workspace_id)
            except Exception as exc:
                logger.warning("on_session_start hook %r raised: %s", hook, exc)

    def fire_session_end(self, session_id: str, workspace_id: str, stop_reason: str) -> None:
        for hook in self._hooks:
            method = getattr(hook, "on_session_end", None)
            if method is None:
                continue
            try:
                method(session_id, workspace_id, stop_reason)
            except Exception as exc:
                logger.warning("on_session_end hook %r raised: %s", hook, exc)

    def fire_tool_use_failure(self, context: ToolFailureContext) -> Optional[str]:
        """
        Run on_tool_use_failure hooks; return the first non-None content string.
        """
        for hook in self._hooks:
            method = getattr(hook, "on_tool_use_failure", None)
            if method is None:
                continue
            try:
                result = method(context)
                if isinstance(result, dict) and isinstance(result.get("content"), str):
                    return result["content"]
            except Exception as exc:
                logger.warning("on_tool_use_failure hook %r raised: %s", hook, exc)
        return None

    def __len__(self) -> int:
        return len(self._hooks)

    def __repr__(self) -> str:
        return f"HookDispatcher(hooks={len(self._hooks)})"
