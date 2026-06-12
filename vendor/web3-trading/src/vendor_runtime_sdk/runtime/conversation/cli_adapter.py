# -*- coding: utf-8 -*-
"""
runtime.conversation.cli_adapter — translate ConversationRuntime's
SSE-JSON event stream into the dict shape ``LocalRuntime`` /
``cli.tui.runtime_bridge`` already speak.

Sprint 2 PR-O3 delivery (docs/LocalRuntime-迁移方案与PR规划.md
Sprint 3 第 3 步).

Why this exists
---------------
``ConversationRuntime`` yields ``StreamResponse(...).model_dump_json(...)``
strings — the Web SSE wire format. The TUI bridge (``cli.tui.runtime_bridge``)
expects per-event dicts with ``type`` discriminator that follows the
LocalRuntime convention:

* ``{"type": "text_delta", "content": str}``
* ``{"type": "tool_call", "name": str, "arguments": dict}``
* ``{"type": "tool_result", "name": str, "content": str}``
* ``{"type": "final", "content": str, "stop_reason": str}``
* ``{"type": "error", "message": str}``
* ``{"type": "requires_approval", "tool_name": str, "arguments": dict,
   "reason": str, "tool_call_id": str}``
* ``{"type": "iteration", "n": int}`` (optional progress marker)

Migrating the TUI bridge to consume ConversationRuntime directly
(Sprint 3+ PR-O5) requires a translator from SSE JSON ↔ CLI dict.
This module is that translator + an async-gen wrapper that drives
the conversion lazily.

Design notes
------------
* The translator is **lossy by design** — SSE has more granular
  step types than the CLI bridge needs to render. Unknown step types
  return ``None`` so the consumer can ``continue`` past them.
* Translation is **per-event** with no cross-event state. This keeps
  the translator pure and trivially testable.
* The translator is **runtime-agnostic** — it never touches
  ``ConversationRuntime`` or ``LocalRuntime`` directly. Either side
  can be swapped without changing the translator.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Dict, Optional, Union

logger = logging.getLogger(__name__)


def sse_event_to_cli_dict(
    event: Union[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Translate one SSE event (JSON string or pre-parsed dict) to the
    CLI bridge's dict shape.

    Returns ``None`` for events with no CLI equivalent — caller should
    ``continue`` past them. Never raises (malformed JSON / unknown
    enum values → return ``None`` and log at DEBUG).

    The function is total over the canonical SSE ``StreamResponse``
    schema (``sessionId`` / ``qaId`` / ``type`` ``StepType`` enum /
    ``status`` ``StreamStatusType`` enum / ``content`` / ``log`` /
    ``extraInfo``). Anything outside that schema returns ``None``.
    """
    parsed = _parse_event(event)
    if parsed is None:
        return None

    step_type = str(parsed.get("type") or "").upper()
    status = str(parsed.get("status") or "").upper()
    content = parsed.get("content")
    log = parsed.get("log") or ""
    extra = parsed.get("extraInfo") or parsed.get("extra_info") or {}
    if not isinstance(extra, dict):
        extra = {}

    # ── HITL gate — status takes precedence over step type ────────────
    if status == "REQUIRES_APPROVAL":
        return {
            "type": "requires_approval",
            "tool_name": str(extra.get("tool_name") or ""),
            "arguments": dict(
                extra.get("arguments") or extra.get("tool_args") or {}
            ),
            "reason": str(
                extra.get("policy_message") or extra.get("reason") or log
            ),
            "tool_call_id": str(extra.get("tool_call_id") or ""),
        }

    # ── Terminal status → final or error ──────────────────────────────
    if status == "COMPLETED":
        return {
            "type": "final",
            "content": _content_to_str(content),
            "stop_reason": "end_turn",
        }
    if status == "FAILED":
        return {
            "type": "error",
            "message": log or _content_to_str(content) or "stream failed",
        }
    if status in ("BLOCKED_QUERY", "BLOCKED_ANSWER"):
        return {
            "type": "error",
            "message": f"{status.lower()}: {log or 'content blocked by safety filter'}",
        }

    # ── Step-type-specific translations ───────────────────────────────
    if step_type == "ANSWER_RESPONSE":
        # Streaming response chunks → text_delta.
        text = _content_to_str(content)
        if not text:
            return None
        return {"type": "text_delta", "content": text}

    if step_type == "TOOL_CALL":
        # extraInfo carries the structured tool call metadata.
        tool_name = str(extra.get("tool_name") or extra.get("name") or "")
        arguments = (
            extra.get("arguments")
            or extra.get("tool_args")
            or {}
        )
        if not tool_name:
            return None
        return {
            "type": "tool_call",
            "name": tool_name,
            "arguments": dict(arguments) if isinstance(arguments, dict) else {},
        }

    if step_type == "TOOL_RESULT":
        tool_name = str(extra.get("tool_name") or extra.get("name") or "")
        result_text = _content_to_str(content) or str(extra.get("result") or "")
        return {
            "type": "tool_result",
            "name": tool_name,
            "content": result_text,
        }

    # ── Unknown / un-rendered step types → return None ────────────────
    # The CLI bridge will skip these via ``continue``. Common ones:
    # QUERY_ANALYSIS / DEEP_THINK / CITATIONS / TITLE etc. — these
    # carry intermediate state the CLI doesn't render today.
    logger.debug(
        "cli_adapter: no CLI translation for step_type=%s status=%s; "
        "consumer should skip",
        step_type, status,
    )
    return None


def _parse_event(
    event: Union[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Decode an SSE event to a dict. Handles JSON string + already-
    parsed dict. Returns ``None`` on malformed input."""
    if isinstance(event, dict):
        return event
    if not isinstance(event, str):
        return None
    s = event.strip()
    if not s:
        return None
    try:
        parsed = json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _content_to_str(content: Any) -> str:
    """Coerce StreamResponse.content (str / dict / list / None) to a
    string suitable for CLI rendering. Returns ``""`` for None /
    coercion failure rather than ``"None"``."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (dict, list)):
        try:
            return json.dumps(content, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(content)
    return str(content)


async def stream_as_cli_dicts(
    sse_stream: AsyncIterator[Union[str, Dict[str, Any]]],
) -> AsyncIterator[Dict[str, Any]]:
    """Wrap a ``ConversationRuntime`` SSE async-gen into a CLI dict
    async-gen — drop events with no CLI translation.

    Drop-in adapter for the TUI bridge:

        async for event in stream_as_cli_dicts(rt.run_turn(...)):
            post_event(event)

    Mirrors the dict shape ``LocalRuntime.chat_turn`` yields, so
    ``cli.tui.runtime_bridge.drive_chat_turn`` keeps working unchanged
    when Sprint 3+ PR-O5/O6 wire the bridge to use this adapter.
    """
    async for raw_event in sse_stream:
        translated = sse_event_to_cli_dict(raw_event)
        if translated is None:
            continue
        yield translated


__all__ = [
    "sse_event_to_cli_dict",
    "stream_as_cli_dicts",
]
