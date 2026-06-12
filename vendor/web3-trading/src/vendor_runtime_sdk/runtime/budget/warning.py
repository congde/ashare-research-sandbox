"""
Budget Warning Stripping (§5.1)

Removes stale budget-pressure markers from previous turns at turn start,
preventing accumulated warnings from consuming context window or causing
the model to refuse tool calls based on outdated "budget exhausted" signals.

Called as part of ConversationRuntime._strip_budget_warnings() before
each new turn's ReAct loop begins.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Union

from vendor_runtime_sdk.runtime.budget.pressure import BUDGET_MARKER_KEY

logger = logging.getLogger(__name__)

# Regex to strip the string-append form:  "\n\n__budget_pressure__:..."
# Matches from the sentinel through end of line (or end of string)
_SUFFIX_PATTERN = re.compile(
    r"\n\n" + re.escape(BUDGET_MARKER_KEY) + r":[^\n]*(?:\n|$)",
    re.DOTALL,
)

# XML tag form used in the actual warning messages
_XML_TAG_PATTERN = re.compile(
    r"<budget_warning\b[^>]*>.*?</budget_warning>",
    re.DOTALL,
)


def strip_budget_warnings(messages: list[dict]) -> int:
    """
    Remove all budget pressure warnings embedded in *messages* (in-place).

    Handles both injection forms produced by ``inject_into_last_tool_result``:
      1. JSON-dict form: ``{..., "__budget_pressure__": "..."}``
      2. String-suffix form: ``"...\\n\\n__budget_pressure__:..."``

    Also strips any bare ``<budget_warning ...>...</budget_warning>`` XML tags
    found in assistant or system message content.

    Parameters
    ----------
    messages : list[dict]
        The conversation messages list (mutated in-place).

    Returns
    -------
    int
        Number of messages that were modified.
    """
    modified = 0

    for i, msg in enumerate(messages):
        content = msg.get("content")
        if not content:
            continue

        new_content = _strip_content(content)
        if new_content != content:
            messages[i] = dict(msg, content=new_content)
            modified += 1

    if modified:
        logger.debug("strip_budget_warnings: cleaned %d message(s)", modified)

    return modified


def _strip_content(content: Union[str, list, dict]) -> Union[str, list, dict]:
    """
    Strip budget markers from a single message content value.

    Content may be:
      • str — plain text or JSON-encoded string
      • list — OpenAI multi-part content (list of dicts with type/text)
      • dict — already a parsed object (non-standard, handled defensively)
    """
    if isinstance(content, str):
        return _strip_string(content)

    if isinstance(content, list):
        return [
            dict(part, text=_strip_string(part["text"]))
            if isinstance(part, dict) and isinstance(part.get("text"), str)
            else part
            for part in content
        ]

    return content  # pass through unknown shapes


def _strip_string(text: str) -> str:
    """Strip all budget warning forms from a plain string."""

    # ── Form 1: JSON dict with BUDGET_MARKER_KEY ─────────────────────────────
    stripped = _try_strip_json_dict(text)
    if stripped is not None:
        text = stripped
    else:
        # ── Form 2: string-suffix form ────────────────────────────────────────
        text = _SUFFIX_PATTERN.sub("", text)

    # ── Form 3: bare XML tags anywhere in the string ─────────────────────────
    text = _XML_TAG_PATTERN.sub("", text)

    return text


def _try_strip_json_dict(text: str) -> str | None:
    """
    If *text* is a JSON-encoded dict containing BUDGET_MARKER_KEY, remove
    the key and return the re-serialised string.

    Returns None if *text* is not a JSON dict or has no marker.
    """
    if BUDGET_MARKER_KEY not in text:
        return None  # fast path — avoid JSON parse overhead

    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(parsed, dict):
        return None

    if BUDGET_MARKER_KEY not in parsed:
        return None

    del parsed[BUDGET_MARKER_KEY]
    return json.dumps(parsed, ensure_ascii=False)


def has_budget_warning(content: str) -> bool:
    """Return True if *content* contains any budget warning marker."""
    return BUDGET_MARKER_KEY in content or bool(_XML_TAG_PATTERN.search(content))
