"""
Tool Call Deduplication (§5.1)

Removes duplicate tool calls (same name + same args) within a single
ReAct iteration to prevent redundant — and potentially destructive —
re-execution.

Deduplication key: (tool_name, canonical_json(arguments))
First occurrence wins; subsequent duplicates are dropped with a WARN log.

This is a per-iteration guard, not a global session-level idempotency
check. For idempotency across sessions see correctness_keys (§14.0.3).
"""

from __future__ import annotations

import json
import logging
from typing import TypeVar

logger = logging.getLogger(__name__)


def _canonical_args(arguments) -> str:
    """
    Produce a stable string key for a tool-call argument set.

    Handles both dict and pre-serialised JSON string forms.
    Falls back gracefully on any parse error.
    """
    if isinstance(arguments, dict):
        return json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
            if isinstance(parsed, dict):
                return json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        except (json.JSONDecodeError, ValueError):
            pass
        return arguments
    return str(arguments)


# ── Generic dedup for any list of objects that have .name and .arguments ───────

_T = TypeVar("_T")


def deduplicate_tool_calls(tool_calls: list[_T]) -> list[_T]:
    """
    Return a new list with duplicate tool calls removed (first occurrence wins).

    Works with any objects that expose ``.name`` and ``.arguments`` attributes,
    or with raw dicts that have ``"name"`` and ``"arguments"`` keys.

    Parameters
    ----------
    tool_calls : list
        The raw tool-call objects produced by an LLM response.

    Returns
    -------
    list
        Deduplicated list in original order.
    """
    seen: set[tuple[str, str]] = set()
    result: list[_T] = []
    dropped = 0

    for tc in tool_calls:
        # Support both object-style and dict-style tool calls
        if isinstance(tc, dict):
            name = tc.get("name") or (tc.get("function") or {}).get("name") or ""
            args = tc.get("arguments") or (tc.get("function") or {}).get("arguments") or {}
        else:
            name = getattr(tc, "name", "") or ""
            # OpenAI SDK: tc.function.name / tc.function.arguments
            fn = getattr(tc, "function", None)
            if fn is not None:
                name = getattr(fn, "name", name) or name
                args = getattr(fn, "arguments", {})
            else:
                args = getattr(tc, "arguments", {})

        key = (name, _canonical_args(args))

        if key in seen:
            logger.warning(
                "deduplicate_tool_calls: dropping duplicate call to '%s' (args=%s…)",
                name,
                _canonical_args(args)[:80],
            )
            dropped += 1
        else:
            seen.add(key)
            result.append(tc)

    if dropped:
        logger.info(
            "deduplicate_tool_calls: removed %d duplicate(s) from %d total calls",
            dropped,
            len(tool_calls),
        )

    return result


def has_duplicates(tool_calls: list) -> bool:
    """Return True if *tool_calls* contains any duplicates."""
    seen: set[tuple[str, str]] = set()
    for tc in tool_calls:
        if isinstance(tc, dict):
            name = tc.get("name") or (tc.get("function") or {}).get("name") or ""
            args = tc.get("arguments") or (tc.get("function") or {}).get("arguments") or {}
        else:
            name = getattr(tc, "name", "")
            fn = getattr(tc, "function", None)
            if fn:
                name = getattr(fn, "name", name)
                args = getattr(fn, "arguments", {})
            else:
                args = getattr(tc, "arguments", {})
        key = (name, _canonical_args(args))
        if key in seen:
            return True
        seen.add(key)
    return False
