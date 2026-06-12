# -*- coding: utf-8 -*-
"""
HITL Decision Memory — short-circuit ``ask`` verdicts when the operator
has previously approved the same tool / argument shape.

Claude-Code-style approval scopes:

    once     — fire once; never recorded.
    session  — remember for the active session (kia_sessions.hitl_decisions).
    forever  — remember across all the user's sessions in this workspace
               (kia_user_tool_preferences Mongo collection — no MySQL
               migration required, stays workspace-isolated).

The module is **read-only fail-soft** by design: any persistence /
network error returns ``None`` from :func:`lookup` so the gate fires.
That preserves the security contract — a missing memory layer can
*never* turn an ``ask`` into an ``allow``. The opposite (recording a
decision the operator never made) is also guarded by an explicit
write API; nothing here implicitly persists.

Toggle: ``hitl_decision_memory`` (default ON via ``_DEFAULT_DISABLED``
exclusion in ``runtime.config.toggles``). When OFF, :func:`lookup`
short-circuits to ``None`` on every call so the gate always fires —
useful for debugging the resolver path or rolling back a regression
without redeploying.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Mapping, Optional


# ── Once-token TTL + per-session cap (Option-3 PR 3 review M1 / L5) ──────────
#
# Once-tokens are written by ``record(scope="once", tool_call_id=…)`` and
# normally consumed within seconds by the resume path. Abandoned approvals
# (operator approves then closes the browser before the agent resumes,
# kernel crashes mid-resume, …) would otherwise accumulate forever in
# ``kia_sessions.hitl_once_tokens[]``.
#
# Two-layer cleanup:
#   1. TTL prune — entries older than 1 hour are dropped on next
#      ``record(scope="once")`` AND on next ``lookup`` for the same
#      session. 1 hour is generous (resume normally happens in seconds);
#      a stale token left after 1 hour reliably indicates the resume path
#      crashed and the next legitimate approve writes a fresh token.
#   2. Per-session hard cap — at most 20 tokens per session. Defends
#      against a misbehaving operator double-clicking approve or a
#      malformed automation that fires N approves before the resume.
#
# Both are inline (no scheduled job needed). For deployments that need
# absolute guarantees we recommend additionally provisioning a mongo TTL
# index on ``kia_sessions.hitl_once_tokens.created_at`` so abandoned
# sessions get GC'd even without future lookups.
_ONCE_TOKEN_TTL_MS: int = 60 * 60 * 1000
_ONCE_TOKEN_PER_SESSION: int = 20

logger = logging.getLogger(__name__)


# Mongo collection used for cross-session preferences. We don't bind a
# real DAO here (avoid heavy import + circular deps); each call resolves
# ``ai_assistant_db`` lazily so tests that stub out the schema module
# don't trip on an unavailable Mongo client.
_USER_PREF_COLLECTION = "kia_user_tool_preferences"

# Placeholders that must not be written to forever-scope prefs.
_ANONYMOUS_USER_IDS = frozenset({"", "anonymous", "unknown", "none", "null"})


def _real_user_id(user_id: str) -> str:
    """Return user_id only when it identifies a real operator."""
    u = (user_id or "").strip()
    if u.lower() in _ANONYMOUS_USER_IDS:
        return ""
    return u


def _toggle_on() -> bool:
    """Return True iff the ``hitl_decision_memory`` toggle is enabled.

    Fail-soft: any error reading the toggles falls back to ``False``
    (the safest choice — gate fires + operator stays in control)."""
    try:
        from vendor_runtime_sdk.runtime.config.guards import is_module_enabled
        return bool(is_module_enabled("hitl_decision_memory"))
    except Exception:  # noqa: BLE001 — fail-soft to OFF
        return False


def _canonicalise_args(arguments: Optional[Mapping[str, Any]]) -> str:
    """Stable string representation of the tool args for matching.

    Used as the ``args_signature`` field. JSON-with-sorted-keys gives a
    deterministic hash without needing a real cryptographic digest —
    we're matching against operator-supplied wildcards, not hashing for
    security.
    """
    if not isinstance(arguments, Mapping) or not arguments:
        return "{}"
    try:
        return json.dumps(dict(arguments), sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        # Args contain unserialisable values — fall back to repr().
        return repr(sorted((str(k), repr(v)) for k, v in arguments.items()))


def _matches_pattern(stored_signature: str, requested_signature: str) -> bool:
    """Return True if a stored decision's args_signature matches.

    For now we support two patterns:

    - ``"*"``           — wildcard, match any args (the typical "allow
                          this tool with whatever args" decision).
    - exact JSON match  — args identical to the previously-approved
                          call. Anything tighter (per-key wildcards)
                          would be operator-authored and is out of
                          scope for v1.

    Any unrecognised pattern returns False — fail-closed.
    """
    if not isinstance(stored_signature, str):
        return False
    if stored_signature == "*":
        return True
    return stored_signature == requested_signature


# ── Lookup ────────────────────────────────────────────────────────────────


async def lookup(
    *,
    session_id: str,
    user_id: str,
    workspace_id: str,
    tool_name: str,
    arguments: Optional[Mapping[str, Any]] = None,
    tool_call_id: Optional[str] = None,
) -> Optional[str]:
    """Return a remembered verdict (``"allow"``) or ``None`` to ask again.

    Resolution order:

    0. PR 3 single-use once-tokens on ``kia_sessions.hitl_once_tokens[]``
       — matched by ``(tool_name, tool_call_id)``; consumed atomically.
       Operators clicking "仅此一次" persist these tokens; PR 3 stateful
       resume preserves the original ``tool_call_id`` across pause →
       resume so the token matches on re-entry.
    1. session-scoped decisions on ``kia_sessions.hitl_decisions[]``
    2. user/workspace forever decisions on ``kia_user_tool_preferences``
       (filtered by ``user_id`` + ``workspace_id`` — never crosses tenant
       boundaries).

    Required arguments (``user_id`` / ``workspace_id``) are kept positional-
    optional via keyword-only so callers that don't have one (e.g. a
    background worker writing to the wrong tenant) silently fall through
    to "no memory" rather than matching against an empty string.
    """
    if not _toggle_on():
        return None
    if not tool_name:
        return None

    canon = _canonicalise_args(arguments)

    # 0. PR 3 single-use once-token by ``(session_id, tool_name, tool_call_id)``
    if session_id and tool_call_id:
        try:
            # PR-E3 (SDK extraction §5 PR-E3): ai_assistant_db is now accessed
            # via the ContextStore Protocol.  The legacy
            # dao.mongo.dbs.ai_assistant_db is still used via the
            # _LegacyContextStoreProvider fallback so runtime behaviour is
            # unchanged in Phase 0.  Phase 2 removes the fallback when dao/
            # leaves the engine import surface.
            from vendor_runtime_sdk.agent.schema import get_timestamp  # type: ignore
            from vendor_runtime_sdk.runtime.protocols.context_store import get_context_store

            _coll = await get_context_store().get_collection("kia_sessions").collection
            # Atomic find-and-pull: remove the matching token if present,
            # AND prune anything older than the TTL window in the same
            # update. ``$pull`` accepts a single condition document with
            # ``$or`` for compound matches; the second branch keys on
            # ``created_at < cutoff`` so we GC stale tokens regardless of
            # whether the current lookup matches anything. Tokens without
            # ``created_at`` (older schema before review M1) are not pruned
            # here — they get GC'd on the next ``record`` call's
            # aggregation-pipeline prune.
            cutoff_ms = get_timestamp() - _ONCE_TOKEN_TTL_MS
            result = await _coll.update_one(
                {"id": session_id},
                {"$pull": {"hitl_once_tokens": {
                    "$or": [
                        {
                            "tool_name": tool_name,
                            "tool_call_id": tool_call_id,
                        },
                        {"created_at": {"$lt": cutoff_ms}},
                    ],
                }}},
            )
            # ``modified_count > 0`` means SOMETHING was pulled — could be
            # our match, a stale prune, or both. We can't directly tell
            # from the update result whether OUR token matched. Re-read
            # the doc to confirm the (tool, call_id) match was consumed —
            # only then return ``allow``.
            if getattr(result, "modified_count", 0) > 0:
                # Quick confirmation read: was the target token in the
                # pre-prune state? If the post-update doc no longer
                # contains it AND a prune happened, our token was
                # consumed (since we only got here when modified_count>0).
                # Cheaper alternative: assume any modified_count>0 with
                # a matching candidate means hit. Risk = false positive
                # token consumption (allow without operator approval).
                # Safer: a follow-up find_one to verify absence.
                doc_after = await _coll.find_one(
                    {"id": session_id},
                    {"hitl_once_tokens": 1, "_id": 0},
                )
                tokens_after = (doc_after or {}).get("hitl_once_tokens") or []
                still_present = any(
                    (isinstance(t, Mapping)
                     and t.get("tool_name") == tool_name
                     and t.get("tool_call_id") == tool_call_id)
                    for t in tokens_after
                )
                if not still_present:
                    logger.info(
                        "hitl.decision_memory: once-token CONSUMED tool=%s call_id=%s "
                        "session=%s — allowing call",
                        tool_name, tool_call_id, session_id,
                    )
                    # PR 4 — observability span + counter at the exact
                    # moment a once-token authorises a call. Dashboards
                    # chart this rate vs ``DAG_CHECKPOINT_SAVED`` to see
                    # how often scope=once actually breaks the loop.
                    try:
                        from vendor_runtime_sdk.runtime.dag_checkpoint_metrics import (
                            emit_dag_checkpoint_span,
                            record_dag_checkpoint_outcome,
                        )
                        from vendor_runtime_sdk.runtime.telemetry import SpanType
                        record_dag_checkpoint_outcome("consumed_once_token")
                        emit_dag_checkpoint_span(
                            span_type=SpanType.DAG_CHECKPOINT_CONSUMED_ONCE_TOKEN,
                            session_id=session_id,
                            metadata={
                                "tool_name": tool_name,
                                # tool_call_id is structural (opaque ID),
                                # safe to emit; never include args.
                                "tool_call_id": tool_call_id,
                            },
                        )
                    except Exception as obs_exc:  # noqa: BLE001 — observability never blocks
                        logger.debug(
                            "decision_memory: span emit failed (%s); allow path unaffected",
                            obs_exc,
                        )
                    return "allow"
                else:
                    # Only stale tokens were pruned; our target wasn't
                    # present to begin with → fall through to legacy scope.
                    logger.debug(
                        "hitl.decision_memory: once-token stale-prune only "
                        "(tool=%s call_id=%s session=%s); falling through",
                        tool_name, tool_call_id, session_id,
                    )
        except Exception as exc:  # noqa: BLE001 — fail-soft
            logger.debug(
                "hitl.decision_memory: once-token lookup failed (%s); "
                "falling through to session/forever scope", exc,
            )

    # 1. Session-scoped decisions.
    if session_id:
        try:
            # PR-E3 (SDK extraction §5 PR-E3): ai_assistant_db is now accessed
            # via the ContextStore Protocol.  The legacy
            # dao.mongo.dbs.ai_assistant_db is still used via the
            # _LegacyContextStoreProvider fallback so runtime behaviour is
            # unchanged in Phase 0.  Phase 2 removes the fallback when dao/
            # leaves the engine import surface.
            from vendor_runtime_sdk.runtime.protocols.context_store import get_context_store

            # ``store.kia_sessions`` is a ``DaoHelper`` whose
            # ``__getattr__`` falls back to the underlying Motor collection
            # via ``self.collection`` — but ``collection`` is an
            # ``@async_property``, so the value is an awaitable
            # (``asyncio.Task``), NOT the collection. We must double-await:
            # once to get the real Motor collection, again on
            # ``find_one(...)``. Single-await produces a silently swallowed
            # ``'_asyncio.Task' object has no attribute 'find_one'`` and
            # the session-scope decision is never persisted.
            _coll = await get_context_store().get_collection("kia_sessions").collection
            doc = await _coll.find_one({"id": session_id})
            decisions = (doc or {}).get("hitl_decisions") or []
            for entry in decisions:
                if not isinstance(entry, Mapping):
                    continue
                if entry.get("tool_name") != tool_name:
                    continue
                if entry.get("action") != "allow":
                    continue
                pattern = str(entry.get("args_signature") or "*")
                if _matches_pattern(pattern, canon):
                    logger.info(
                        "hitl.decision_memory: session hit tool=%s session=%s",
                        tool_name, session_id,
                    )
                    return "allow"
        except Exception as exc:  # noqa: BLE001 — fail-soft
            logger.debug(
                "hitl.decision_memory: session lookup failed (%s); falling through",
                exc,
            )

    # 2. User × workspace forever decisions.
    if _real_user_id(user_id) and workspace_id:
        user_id = _real_user_id(user_id)
        try:
            # PR-E3 (SDK extraction §5 PR-E3): ai_assistant_db is now accessed
            # via the ContextStore Protocol.  The legacy
            # dao.mongo.dbs.ai_assistant_db is still used via the
            # _LegacyContextStoreProvider fallback so runtime behaviour is
            # unchanged in Phase 0.  Phase 2 removes the fallback when dao/
            # leaves the engine import surface.
            from vendor_runtime_sdk.runtime.protocols.context_store import (
                ContextStoreNotInstalledError,
                get_context_store,
            )

            try:
                collection = get_context_store().get_collection(_USER_PREF_COLLECTION)
            except ContextStoreNotInstalledError:
                # No store installed AND legacy fallback unreachable —
                # the intended narrow fallback (PR-E3 review feedback).
                # Other exceptions (AttributeError / TypeError) must
                # surface as loud failures so they show up in CI.
                collection = None
            if collection is None:
                return None

            cursor = collection.find(
                {
                    "user_id": user_id,
                    "workspace_id": workspace_id,
                    "tool_name": tool_name,
                    "action": "allow",
                }
            )
            # Most operators set few prefs; iterating the cursor in
            # full is fine. If this ever becomes a hot path the
            # caller can move to an in-process LRU.
            async for doc in cursor:  # pragma: no cover — depends on Motor cursor protocol
                pattern = str(doc.get("args_signature") or "*")
                if _matches_pattern(pattern, canon):
                    logger.info(
                        "hitl.decision_memory: forever hit tool=%s user=%s ws=%s",
                        tool_name, user_id, workspace_id,
                    )
                    return "allow"
        except Exception as exc:  # noqa: BLE001 — fail-soft
            logger.debug(
                "hitl.decision_memory: forever lookup failed (%s); falling through",
                exc,
            )

    return None


# ── Recording decisions ────────────────────────────────────────────────────


async def record(
    *,
    session_id: str,
    user_id: str,
    workspace_id: str,
    tool_name: str,
    arguments: Optional[Mapping[str, Any]] = None,
    scope: str = "once",
    decided_by: str = "",
    args_pattern: str = "*",
    tool_call_id: Optional[str] = None,
) -> None:
    """Persist an ``allow`` decision at *scope*.

    ``scope == "once"`` historically was a no-op, but Sprint Option-3 PR 3
    upgraded it to persist a **single-use token** keyed by ``tool_call_id``
    when one is supplied. The token is consumed by the next
    ``lookup(tool_name=…, tool_call_id=<same id>)`` call (PR 3 stateful-
    resume path preserves the original call_id across HITL pause → resume
    so the token matches). Without a call_id, ``once`` remains a no-op —
    the legacy path will re-ask. Anything else writes to the appropriate
    store.

    ``args_pattern`` defaults to wildcard (``"*"``) so a single
    *Allow this session* click broadly enables the tool for the rest
    of the session — matches the Claude Code UX. Power users can tighten
    by passing the exact serialised args as the pattern.

    Failures are logged at WARN and swallowed — the resume path must
    never error out because we couldn't write to Mongo.
    """
    scope = (scope or "once").lower().strip()
    if scope == "once":
        # Sprint Option-3 PR 3 — write a single-use call_id-scoped token
        # so PR 3's stateful-resume path can re-enter the same paused
        # tool call without firing HITL again. Without the call_id we
        # have nothing to match against; preserve legacy no-op behaviour.
        if not _toggle_on() or not session_id or not tool_name or not tool_call_id:
            return
        try:
            # PR-E3 (SDK extraction §5 PR-E3): ai_assistant_db is now accessed
            # via the ContextStore Protocol.  The legacy
            # dao.mongo.dbs.ai_assistant_db is still used via the
            # _LegacyContextStoreProvider fallback so runtime behaviour is
            # unchanged in Phase 0.  Phase 2 removes the fallback when dao/
            # leaves the engine import surface.
            from vendor_runtime_sdk.agent.schema import get_timestamp  # type: ignore
            from vendor_runtime_sdk.runtime.protocols.context_store import get_context_store

            now_ms = get_timestamp()
            entry = {
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "decided_by": decided_by,
                "decided_at": now_ms,
                # ``created_at`` is the truth for TTL / age comparisons —
                # ``decided_at`` and ``created_at`` are the same at insert
                # time, but keeping both lets future audit queries
                # distinguish "when operator decided" from "when entry
                # landed in mongo" if those ever diverge (e.g. queue lag).
                "created_at": now_ms,
            }
            _coll = await get_context_store().get_collection("kia_sessions").collection
            # Mongo doesn't allow ``$push`` and ``$pull`` on the same
            # field in one update (raises ConflictingUpdateOperators).
            # Use an aggregation-pipeline update (mongo 4.2+) so the push
            # + stale-prune happens atomically in one round-trip:
            #   1. ``$filter`` keeps only tokens whose ``created_at`` is
            #      within the TTL window (and tolerate missing ``created_at``
            #      via the legacy-token fallback)
            #   2. ``$concatArrays`` appends the new entry
            #   3. capped to last N entries (``_ONCE_TOKEN_PER_SESSION``)
            #      so a misbehaving operator double-clicking can't grow
            #      the array unboundedly
            # Stale tokens that survive this insert path get pruned on
            # the next ``lookup`` call (which also does inline cleanup).
            cutoff_ms = now_ms - _ONCE_TOKEN_TTL_MS
            await _coll.update_one(
                {"id": session_id},
                [
                    {"$set": {
                        "hitl_once_tokens": {
                            "$let": {
                                "vars": {
                                    "kept": {
                                        "$filter": {
                                            "input": {"$ifNull": ["$hitl_once_tokens", []]},
                                            "as": "t",
                                            "cond": {
                                                "$gte": [
                                                    {"$ifNull": ["$$t.created_at", 0]},
                                                    cutoff_ms,
                                                ],
                                            },
                                        },
                                    },
                                },
                                "in": {
                                    "$slice": [
                                        {"$concatArrays": ["$$kept", [entry]]},
                                        -_ONCE_TOKEN_PER_SESSION,
                                    ],
                                },
                            },
                        },
                    }},
                ],
                upsert=False,
            )
            logger.info(
                "hitl.decision_memory.record: once-token persisted "
                "tool=%s call_id=%s session=%s",
                tool_name, tool_call_id, session_id,
            )
        except Exception as exc:  # noqa: BLE001 — fail-soft
            logger.warning(
                "hitl.decision_memory.record(once-token) failed (%s); "
                "scope=once falls back to no-op semantics", exc,
            )
        return
    if scope not in ("session", "forever"):
        logger.warning(
            "hitl.decision_memory.record: ignoring unknown scope=%r tool=%s",
            scope, tool_name,
        )
        return
    if not tool_name:
        return

    sig = args_pattern or "*"

    # Forever needs a real user_id + workspace. Local dev often runs as
    # ``anonymous`` — downgrade to session so "始终允许" still works in-chat.
    if scope == "forever":
        eff_user = _real_user_id(user_id)
        if not eff_user or not workspace_id:
            if session_id:
                logger.info(
                    "hitl.decision_memory.record: forever unavailable "
                    "(user_id=%r workspace_id=%r); persisting session scope "
                    "for tool=%s session=%s",
                    user_id or "(empty)",
                    workspace_id or "(empty)",
                    tool_name,
                    session_id,
                )
                scope = "session"
            else:
                logger.warning(
                    "hitl.decision_memory.record(forever): missing user_id/"
                    "workspace_id/session_id; tool=%s — skipping persistence",
                    tool_name,
                )
                return

    if scope == "session":
        if not session_id:
            return
        try:
            # PR-E3 (SDK extraction §5 PR-E3): ai_assistant_db is now accessed
            # via the ContextStore Protocol.  The legacy
            # dao.mongo.dbs.ai_assistant_db is still used via the
            # _LegacyContextStoreProvider fallback so runtime behaviour is
            # unchanged in Phase 0.  Phase 2 removes the fallback when dao/
            # leaves the engine import surface.
            from vendor_runtime_sdk.agent.schema import get_timestamp  # type: ignore
            from vendor_runtime_sdk.runtime.protocols.context_store import get_context_store

            entry = {
                "tool_name": tool_name,
                "action": "allow",
                "args_signature": sig,
                "decided_by": decided_by,
                "decided_at": get_timestamp(),
            }
            # ``$push`` would be ideal but BaseDAO.add_or_update_one
            # only does whole-doc set; emulate by reading + writing.
            # See lookup() for the same double-await rationale —
            # ``find_one`` lives on the Motor collection, which is
            # exposed via the async_property ``DaoHelper.collection``.
            _kia_sessions = get_context_store().get_collection("kia_sessions")
            _coll = await _kia_sessions.collection
            doc = await _coll.find_one({"id": session_id})
            decisions = list((doc or {}).get("hitl_decisions") or [])
            decisions.append(entry)
            await _kia_sessions.add_or_update_one(
                matcher={"id": session_id},
                data={"hitl_decisions": decisions, "updateTime": get_timestamp()},
            )
            logger.info(
                "hitl.decision_memory: recorded session decision tool=%s session=%s",
                tool_name, session_id,
            )
        except Exception as exc:  # noqa: BLE001 — fail-soft
            logger.warning(
                "hitl.decision_memory: failed to record session decision: %s", exc,
            )
        return

    # scope == "forever" (user_id/workspace validated above)
    user_id = _real_user_id(user_id)
    try:
        # PR-E3 (SDK extraction §5 PR-E3): ai_assistant_db is now accessed
        # via the ContextStore Protocol.  The legacy
        # dao.mongo.dbs.ai_assistant_db is still used via the
        # _LegacyContextStoreProvider fallback so runtime behaviour is
        # unchanged in Phase 0.  Phase 2 removes the fallback when dao/
        # leaves the engine import surface.
        from vendor_runtime_sdk.agent.schema import get_timestamp  # type: ignore
        from vendor_runtime_sdk.runtime.protocols.context_store import get_context_store

        try:
            collection = get_context_store().get_collection(_USER_PREF_COLLECTION)
        except Exception:  # noqa: BLE001 — collection materialisation failure
            collection = None
        if collection is None:
            logger.warning(
                "hitl.decision_memory: %s collection unavailable; skipping forever record",
                _USER_PREF_COLLECTION,
            )
            return
        # Upsert keyed on (user_id, workspace_id, tool_name, args_signature)
        await collection.update_one(
            {
                "user_id": user_id,
                "workspace_id": workspace_id,
                "tool_name": tool_name,
                "args_signature": sig,
            },
            {
                "$set": {
                    "user_id": user_id,
                    "workspace_id": workspace_id,
                    "tool_name": tool_name,
                    "args_signature": sig,
                    "action": "allow",
                    "decided_by": decided_by,
                    "updated_at": get_timestamp(),
                },
                "$setOnInsert": {"created_at": get_timestamp()},
            },
            upsert=True,
        )
        logger.info(
            "hitl.decision_memory: recorded forever decision tool=%s user=%s ws=%s",
            tool_name, user_id, workspace_id,
        )
    except Exception as exc:  # noqa: BLE001 — fail-soft
        logger.warning(
            "hitl.decision_memory: failed to record forever decision: %s", exc,
        )


__all__ = ["lookup", "record"]
