# -*- coding: utf-8 -*-
"""
Activity Distiller — §6.3 Memory System Wiring (Phase 6.3)

Background pipeline that condenses L2 (workspace) Activity records into L3
(user preference) and L4 (agent_instance learned-pattern) MemoryStore entries.

Why this exists
---------------
Without distillation, the L2 activity log grows unbounded and the LLM never
sees a summarised view.  The distiller produces compact, deterministic
entries (no LLM calls — pure aggregation) that the agent can read on the
next turn via ``memory_*`` tools or via system-prompt injection.

Design rules
------------
- **Deterministic**: no LLM calls, no randomness; same input → same output.
- **Idempotent**: writing the same distillation twice produces identical
  content_sha256 (no version churn beyond the first write).
- **Bounded cost**: O(N) over a small window of recent activity per turn.
- **Fail-soft**: any DAO error logs at WARNING and returns silently.
- **Toggle-gated**: ``activity_distillation`` must be enabled.
- **Post-turn only**: never blocks the live request path.

Output format
-------------
Two entries per turn (when there is meaningful activity):

  L3 user store:
      path  = "preferences/recent_topics"
      content = JSON list of {topic, last_seen, freq}

  L4 agent_instance store:
      path  = "patterns/tool_usage"
      content = JSON dict of {tool_name: {count, last_seen, success_rate}}

These paths are *stable* — successive turns update the same entry rather
than creating new paths, so the LLM has a single canonical place to look.
"""

from __future__ import annotations

import json
import logging
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# Imported at module level so tests can patch "runtime.activity.distiller.is_module_enabled".
try:
    from vendor_runtime_sdk.runtime.config.guards import is_module_enabled
except Exception:  # pragma: no cover — defensive: toggles unavailable in some test envs
    def is_module_enabled(_name: str) -> bool:  # type: ignore[no-redef]
        return True

logger = logging.getLogger(__name__)


# ── Telemetry data points the distiller consumes ──────────────────────────────


@dataclass(frozen=True)
class TurnDigest:
    """One turn's worth of input data for distillation.

    Built from ConversationRuntime telemetry + agent context. Only contains
    primitive types so it survives JSON serialisation across async boundaries.
    """

    session_id: str
    user_id: str
    workspace_id: str
    query: str
    timestamp: float
    tool_calls: List[Dict[str, Any]]   # [{name, success}]
    api_call_count: int
    final_status: str                  # "success" / "failed" / "timeout"


# ── Aggregator: pure functions ────────────────────────────────────────────────


_RECENT_TOPICS_LIMIT = 20    # keep last N topics in L3 preferences
_TOOL_PATTERNS_LIMIT = 30    # keep last N tools in L4 patterns
_PREFS_PATH = "preferences/recent_topics"
_PATTERNS_PATH = "patterns/tool_usage"


def _extract_topic(query: str) -> str:
    """Heuristic topic extraction — first 50 chars, normalised whitespace.

    For production we deliberately avoid an LLM call here. The topic is a
    rough surface form, intended for fuzzy matching by the next turn's
    memory_search call (which is also substring-based).
    """
    if not query:
        return ""
    cleaned = " ".join(query.split())
    return cleaned[:50]


def _merge_recent_topics(prior_json: Optional[str], digest: TurnDigest) -> str:
    """Merge new topic into the existing list, deduping by topic string.

    Returns canonical JSON (sort_keys, separators) so identical state always
    produces an identical content_sha256 — essential for idempotency.
    """
    items: List[Dict[str, Any]] = []
    if prior_json:
        try:
            parsed = json.loads(prior_json)
            if isinstance(parsed, list):
                items = [x for x in parsed if isinstance(x, dict)]
        except (json.JSONDecodeError, TypeError):
            items = []

    topic = _extract_topic(digest.query)
    if not topic:
        return prior_json or ""

    # Bump frequency / last_seen if topic exists; else prepend.
    found = False
    for entry in items:
        if entry.get("topic") == topic:
            entry["freq"] = int(entry.get("freq", 0)) + 1
            entry["last_seen"] = digest.timestamp
            found = True
            break
    if not found:
        items.insert(0, {
            "topic": topic,
            "freq": 1,
            "last_seen": digest.timestamp,
        })

    # Bound size by removing the least-recently-seen entries.
    items.sort(key=lambda x: x.get("last_seen", 0), reverse=True)
    items = items[:_RECENT_TOPICS_LIMIT]

    return json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _merge_tool_patterns(prior_json: Optional[str], digest: TurnDigest) -> str:
    """Merge tool usage stats into the existing pattern dict."""
    patterns: Dict[str, Dict[str, Any]] = {}
    if prior_json:
        try:
            parsed = json.loads(prior_json)
            if isinstance(parsed, dict):
                patterns = {k: v for k, v in parsed.items() if isinstance(v, dict)}
        except (json.JSONDecodeError, TypeError):
            patterns = {}

    if not digest.tool_calls:
        # Nothing to update; preserve prior content as-is (no rewrite needed).
        return prior_json or ""

    for call in digest.tool_calls:
        name = str(call.get("name", "")).strip()
        if not name:
            continue
        bucket = patterns.setdefault(name, {"count": 0, "success": 0, "failure": 0, "last_seen": 0})
        bucket["count"] = int(bucket.get("count", 0)) + 1
        if call.get("success", True):
            bucket["success"] = int(bucket.get("success", 0)) + 1
        else:
            bucket["failure"] = int(bucket.get("failure", 0)) + 1
        bucket["last_seen"] = digest.timestamp

    # Compute success_rate for each entry; bound dict size by last_seen recency.
    for name, bucket in patterns.items():
        total = bucket.get("count", 0) or 1
        bucket["success_rate"] = round(bucket.get("success", 0) / total, 3)

    if len(patterns) > _TOOL_PATTERNS_LIMIT:
        # Drop the least-recently-seen tools.
        kept = sorted(
            patterns.items(),
            key=lambda kv: kv[1].get("last_seen", 0),
            reverse=True,
        )[:_TOOL_PATTERNS_LIMIT]
        patterns = dict(kept)

    return json.dumps(patterns, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


# ── Public entry point ────────────────────────────────────────────────────────


async def distill_turn(
    digest: TurnDigest,
    *,
    user_store: Optional[Any] = None,
    agent_instance_store: Optional[Any] = None,
) -> Dict[str, bool]:
    """Distill a single turn into L3/L4 store updates.

    Args:
        digest: TurnDigest built from ConversationRuntime telemetry.
        user_store: L3 MemoryStore (user scope) — receives recent_topics.
        agent_instance_store: L4 MemoryStore — receives tool_usage patterns.

    Returns:
        {"prefs_updated": bool, "patterns_updated": bool}

    Behaviour:
        Toggle-gated by ``activity_distillation``. If disabled, returns
        {"prefs_updated": False, "patterns_updated": False} without touching
        any store.

        Read-modify-write is the simplest correct strategy here because
        distillation runs strictly post-turn; the store is not concurrently
        mutated by any other path.
    """
    result = {"prefs_updated": False, "patterns_updated": False}

    try:
        if not is_module_enabled("activity_distillation"):
            return result
    except Exception:
        return result

    # ── L3: user preferences (recent topics) ───────────────────────────────
    if user_store is not None:
        try:
            existing = await user_store.read(_PREFS_PATH)
            prior = existing.content if existing else None
            new_content = _merge_recent_topics(prior, digest)
            if new_content and new_content != (prior or ""):
                await user_store.write(
                    _PREFS_PATH,
                    new_content,
                    actor_type="distiller",
                    actor_id="activity_distiller",
                )
                result["prefs_updated"] = True
        except Exception as exc:
            logger.warning("distill_turn(L3) failed: %s", exc)

    # ── L4: agent_instance patterns (tool usage) ───────────────────────────
    if agent_instance_store is not None and digest.tool_calls:
        try:
            existing = await agent_instance_store.read(_PATTERNS_PATH)
            prior = existing.content if existing else None
            new_content = _merge_tool_patterns(prior, digest)
            if new_content and new_content != (prior or ""):
                await agent_instance_store.write(
                    _PATTERNS_PATH,
                    new_content,
                    actor_type="distiller",
                    actor_id="activity_distiller",
                )
                result["patterns_updated"] = True
        except Exception as exc:
            logger.warning("distill_turn(L4) failed: %s", exc)

    if result["prefs_updated"] or result["patterns_updated"]:
        logger.info(
            "distill_turn: session=%s, prefs_updated=%s, patterns_updated=%s, tools=%d",
            digest.session_id[:8] if digest.session_id else "?",
            result["prefs_updated"], result["patterns_updated"],
            len(digest.tool_calls),
        )
    return result
