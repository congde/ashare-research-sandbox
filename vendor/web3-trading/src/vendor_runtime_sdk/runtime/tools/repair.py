"""
Tool Name Self-Repair (§5.1)

Uses difflib fuzzy matching to correct misspelled tool names returned by
the LLM before execution, preventing hard "tool not found" failures from
minor hallucinations like "search_web" → "web_search".

Repair strategy:
  1. Exact match → no repair needed
  2. Case-insensitive match → normalise case
  3. difflib SequenceMatcher best match with similarity ≥ threshold → repair
  4. No match above threshold → leave as-is (will fail at execution; caller decides)

The default similarity threshold (0.75) is conservative: repairs obvious
typos while avoiding false-positive corrections that change semantics.
"""

from __future__ import annotations

import difflib
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Minimum similarity ratio to accept a repair (0.0–1.0)
DEFAULT_THRESHOLD: float = 0.75


def repair_tool_name(
    name: str,
    known_names: list[str],
    threshold: float = DEFAULT_THRESHOLD,
) -> str:
    """
    Attempt to correct *name* to the closest known tool name.

    Parameters
    ----------
    name : str
        The tool name as returned by the LLM (may be misspelled).
    known_names : list[str]
        All registered tool names from the ToolRegistry.
    threshold : float
        Minimum SequenceMatcher similarity to accept a repair (0–1).

    Returns
    -------
    str
        The repaired name, or the original *name* if no confident match found.
    """
    if not name or not known_names:
        return name

    # ── Fast path: exact match ────────────────────────────────────────────────
    if name in known_names:
        return name

    # ── Case-insensitive match ────────────────────────────────────────────────
    name_lower = name.lower()
    for known in known_names:
        if known.lower() == name_lower:
            logger.info("repair_tool_name: '%s' → '%s' (case normalised)", name, known)
            return known

    # ── Fuzzy match via difflib ───────────────────────────────────────────────
    best_match, best_score = _best_fuzzy_match(name, known_names)

    if best_match is not None and best_score >= threshold:
        logger.warning(
            "repair_tool_name: '%s' → '%s' (fuzzy, score=%.2f)",
            name,
            best_match,
            best_score,
        )
        return best_match

    # ── No confident repair ───────────────────────────────────────────────────
    logger.debug(
        "repair_tool_name: '%s' unmatched (best=%.2f < threshold=%.2f)",
        name,
        best_score,
        threshold,
    )
    return name


def repair_tool_calls(
    tool_calls: list,
    known_names: list[str],
    threshold: float = DEFAULT_THRESHOLD,
) -> tuple[list, int]:
    """
    Apply name repair to every tool call in *tool_calls*.

    Works with both OpenAI SDK objects (``tc.function.name``) and raw dicts
    (``{"name": ..., "function": {"name": ...}}``).

    Returns
    -------
    tuple[list, int]
        (repaired_tool_calls, number_of_repairs_made)
    """
    repaired_calls = []
    repair_count = 0

    for tc in tool_calls:
        original_name = _get_name(tc)
        new_name = repair_tool_name(original_name, known_names, threshold)

        if new_name != original_name:
            tc = _set_name(tc, new_name)
            repair_count += 1

        repaired_calls.append(tc)

    return repaired_calls, repair_count


def find_closest(
    name: str,
    known_names: list[str],
    threshold: float = DEFAULT_THRESHOLD,
) -> Optional[str]:
    """
    Return the closest known tool name, or None if below threshold.

    Convenience wrapper used in error messages and diagnostics.
    """
    if name in known_names:
        return name
    best, score = _best_fuzzy_match(name, known_names)
    return best if (best is not None and score >= threshold) else None


# ── Internal helpers ───────────────────────────────────────────────────────────


def _best_fuzzy_match(name: str, candidates: list[str]) -> tuple[Optional[str], float]:
    """Return the (best_candidate, highest_score) from difflib."""
    best_name: Optional[str] = None
    best_score: float = 0.0

    for candidate in candidates:
        score = difflib.SequenceMatcher(None, name, candidate).ratio()
        if score > best_score:
            best_score = score
            best_name = candidate

    return best_name, best_score


def _get_name(tc) -> str:
    """Extract tool name from an SDK object or dict."""
    if isinstance(tc, dict):
        # Direct dict: {"name": "foo"} or {"function": {"name": "foo"}}
        return tc.get("name") or (tc.get("function") or {}).get("name") or ""
    # OpenAI SDK object: tc.function.name
    fn = getattr(tc, "function", None)
    if fn is not None:
        return getattr(fn, "name", "") or ""
    return getattr(tc, "name", "") or ""


def _set_name(tc, new_name: str):
    """Return a copy of *tc* with the tool name replaced by *new_name*."""
    if isinstance(tc, dict):
        if "function" in tc:
            fn = dict(tc["function"], name=new_name)
            return dict(tc, function=fn)
        return dict(tc, name=new_name)

    # OpenAI SDK objects are typically frozen dataclasses/attrs — we clone via
    # the object's own copy mechanism or fall back to a simple wrapper.
    try:
        import copy

        tc_copy = copy.copy(tc)
        fn = getattr(tc_copy, "function", None)
        if fn is not None:
            fn_copy = copy.copy(fn)
            fn_copy.name = new_name
            tc_copy.function = fn_copy
        else:
            tc_copy.name = new_name
        return tc_copy
    except Exception:
        # Last resort: return original unchanged (repair was best-effort)
        logger.debug("_set_name: could not mutate tool call object, returning original")
        return tc
