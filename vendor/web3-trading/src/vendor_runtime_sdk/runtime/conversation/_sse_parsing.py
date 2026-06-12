# -*- coding: utf-8 -*-
"""
SSEParsingMixin — SSE event parsing, token extraction, properties

Auto-extracted from runtime/conversation.py during refactoring.
Part of the ConversationRuntime mixin chain.
"""

from __future__ import annotations
from typing import AsyncGenerator, List, Optional
from vendor_runtime_sdk.runtime.session.fsm import IllegalTransitionError, SessionFSM, SessionState

class SSEParsingMixin:
    """SSEParsingMixin — SSE event parsing, token extraction, properties"""

    def _parse_sse_event(self, event) -> Optional[dict]:
        """
        Try to parse an agent stream event into a dict.

        Events yielded from `agent.run()` may be:
          - Pre-serialized SSE strings: `'data: {...}\\n\\n'`
          - Raw JSON strings: `'{"type":"...","content":"..."}'`
          - Already dict/object — returned as-is (dict) or None (object)

        Returns None on parse failure or for non-string events.
        """
        if not isinstance(event, str):
            return event if isinstance(event, dict) else None
        try:
            import json as _json
            s = event.strip()
            # Strip SSE "data: " prefix if present
            if s.startswith("data:"):
                s = s[5:].strip()
            if not s or s[0] not in ("{", "["):
                return None
            return _json.loads(s)
        except Exception:
            return None

    def _maybe_extract_tokens(self, event) -> None:
        """
        Best-effort extraction of token usage from an agent event object.

        Strategy, in order:
          1. event.usage.{input_tokens, output_tokens}
          2. event['usage']['input_tokens'] / ['output_tokens']
          3. event.input_tokens / event.output_tokens
          4. **Fallback**: estimate output tokens from `content` field on
             streaming chunks (ANSWER_RESPONSE, DEEP_THINK, etc.) using
             the heuristic from agent.context.token_budget.estimate_tokens.
        """
        try:
            usage = None
            if hasattr(event, "usage"):
                usage = event.usage
            elif isinstance(event, dict):
                usage = event.get("usage")

            if usage:
                it = 0
                ot = 0
                if hasattr(usage, "input_tokens"):
                    it = int(getattr(usage, "input_tokens", 0) or 0)
                    ot = int(getattr(usage, "output_tokens", 0) or 0)
                elif isinstance(usage, dict):
                    it = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
                    ot = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
                if it or ot:
                    self._record_tokens(input_tokens=it, output_tokens=ot)
                    # Save raw usage for cost tracking hooks (P4)
                    self._last_usage_raw = usage
                    return

            # Direct attributes / keys on the event itself
            it = 0
            ot = 0
            if hasattr(event, "input_tokens"):
                it = int(getattr(event, "input_tokens", 0) or 0)
            elif isinstance(event, dict):
                it = int(event.get("input_tokens") or 0)
            if hasattr(event, "output_tokens"):
                ot = int(getattr(event, "output_tokens", 0) or 0)
            elif isinstance(event, dict):
                ot = int(event.get("output_tokens") or 0)
            if it or ot:
                self._record_tokens(input_tokens=it, output_tokens=ot)
                return

            # Check content field — may be a token-usage dict emitted by
            # response_mixin when stream_llm reports OpenAI usage, or a
            # plain string for output estimation fallback.
            content = None
            if hasattr(event, "content"):
                content = getattr(event, "content", None)
            elif isinstance(event, dict):
                content = event.get("content")
            if isinstance(content, dict):
                it = int(content.get("input_tokens") or 0)
                ot = int(content.get("output_tokens") or 0)
                if it or ot:
                    # Authoritative usage from OpenAI — replace estimates.
                    # After this, ignore content-chunk estimates (follow-up
                    # questions / citations emit CONTENT events after the
                    # main response and would overwrite these values).
                    self._input_tokens_last = it
                    self._output_tokens_last = ot
                    self._tokens_total = it + ot
                    self._authoritative_usage_received = True
                    return
            if self._authoritative_usage_received:
                return
            if isinstance(content, str) and content:
                from vendor_runtime_sdk.agent.context.token_budget import estimate_tokens
                est = estimate_tokens(content)
                if est > 0:
                    self._record_tokens(output_tokens=est)
        except Exception:
            pass  # telemetry is best-effort, never raise

    # ── Diagnostics ────────────────────────────────────────────────────────────

    @property
    def activity_summary(self) -> dict:
        """Return a diagnostic snapshot of current activity."""
        snap = self._activity.get_summary()
        return {
            "last_activity": snap.last_activity_desc,
            "idle_seconds": round(snap.seconds_since_activity, 1),
            "current_tool": snap.current_tool,
            "api_calls": snap.api_call_count,
            "tool_calls": snap.tool_call_count,
            "session_id": snap.session_id,
            "fsm_state": self._fsm.state.value,
        }

    @property
    def fsm_state(self) -> SessionState:
        return self._fsm.state


# ── SSE dict helpers ───────────────────────────────────────────────────────────
