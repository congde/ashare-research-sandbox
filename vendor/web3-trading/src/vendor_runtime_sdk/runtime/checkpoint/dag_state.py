# -*- coding: utf-8 -*-
"""
DAG execution checkpoint — persisted state for HITL pause + resume (Sprint Option 3, PR 1).

Background
----------
Today's HITL resume path (`runtime.conversation._resume.continue_after_hitl_approval`)
dispatches a **brand-new agent** with a synthesised continuation_query when the
operator clicks "approve". That new agent re-runs Phase 1 + Phase 2 + Plan from
scratch — producing a fresh ``tool_call_id`` for the same tool. The previous
``scope=once`` approval was bound to the OLD call_id, so the NEW call fires HITL
again. With each "approve once" the user just creates another HITL gate, and
the chain loops indefinitely (observed: 26 cycles before the user gave up).

PR 1 (this file) — pure infrastructure, no callers
---------------------------------------------------
Persist enough state at HITL pause to let a later "resume" path skip Phase 1 /
Phase 2 entirely and re-enter `DAGExecutor` at the paused task with the SAME
``tool_call_id``. With the call_id preserved across pause → approve → resume,
``scope=once`` works naturally (single-shot approval matches the single call it
authorised) and no re-planning occurs.

This module ships:
    * ``DagCheckpoint`` dataclass — schema of what gets persisted
    * ``save_dag_checkpoint`` / ``load_dag_checkpoint`` / ``clear_dag_checkpoint``
      async helpers backed by ``kia_sessions.dag_checkpoint`` field
    * ``DagCheckpointSize.cap_outputs`` — size-cap helper (single output > 64
      KiB → truncated; total > 1 MiB → drop oldest outputs until under cap)

PR 1 deliberately does NOT:
    * Wire any caller into HITL pause or resume (PR 3 handles wiring)
    * Add a `DAGExecutor.execute_from_checkpoint` method (PR 2)
    * Touch the existing re-plan path (PR 3 adds the toggle-gated switch)

Toggle: ``dag_stateful_resume`` (default OFF, see
``runtime.config.toggles``). When OFF every helper here is unreachable — this
module just sits idle until PR 2 + PR 3 land.

Pitfalls
~~~~~~~~
- Mongo BSON documents are capped at 16 MiB. Single sessions can in theory
  accumulate hundreds of large tool outputs (kline data, search results).
  ``cap_outputs`` truncates aggressively to stay well below that ceiling.
- ``kia_sessions.dag_checkpoint`` is a single nested document, NOT a list, so
  we always overwrite (sessions can only be paused at ONE HITL gate at a time —
  the agent loop is single-threaded for a given session).
- All persistence is fail-soft: a Mongo write error logs WARN and returns;
  callers (PR 3) must treat checkpoint absence as "fall back to re-plan
  path" instead of failing the resume.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Size caps ─────────────────────────────────────────────────────────────────
#
# Per-output: 64 KiB is large enough for most data_middleware / valueScan_api
# JSON payloads (collection list ~ 33 entries ≈ 2 KiB, OHLCV 1000 candles ≈
# 60 KiB) but small enough that pathological outputs (Top-100 holders × 20
# decimals = 100 KiB+) get truncated rather than wedge Mongo.
#
# Per-checkpoint: 1 MiB stays well below the 16 MiB BSON limit even with
# metadata + plan JSON + 15 maxed-out outputs (15 × 64 = 960 KiB). When the
# total exceeds 1 MiB ``cap_outputs`` drops the OLDEST outputs first (by
# insertion order in the dict) — the most recent tool calls are usually what
# the resumed task most needs as context.
_OUTPUT_BYTES_CAP: int = 64 * 1024
_CHECKPOINT_BYTES_CAP: int = 1024 * 1024
_TRUNCATION_SUFFIX: str = "\n…[truncated by dag_checkpoint cap]"


_MAX_BASIC_JSON_DEPTH: int = 32


def _is_basic_json(value: Any, _depth: int = 0) -> bool:
    """
    True iff *value* is built from basic JSON types only.

    Used by ``cap_outputs`` to decide whether to keep the value as-is or
    coerce to ``str()``. ``json.dumps(default=str)`` lets the size
    measurement succeed for anything (default=str silently turns custom
    objects into "<MyClass instance>"), but the resulting stored value
    must still BSON-encode for the mongo write to succeed. Walks dicts /
    lists recursively up to ``_MAX_BASIC_JSON_DEPTH`` — past that we
    return ``False`` so the caller coerces via ``str()`` rather than
    risking a Python recursion-limit crash on pathological nesting
    (defense in depth — real tool outputs are bounded but a misbehaving
    upstream could in theory deliver a self-referential graph).
    """
    if _depth >= _MAX_BASIC_JSON_DEPTH:
        return False
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, list):
        return all(_is_basic_json(v, _depth + 1) for v in value)
    if isinstance(value, dict):
        return all(
            isinstance(k, str) and _is_basic_json(v, _depth + 1)
            for k, v in value.items()
        )
    return False


# ── Schema ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PausedTaskInfo:
    """
    Snapshot of the task that was about to execute when HITL fired.

    PR 2's ``DAGExecutor.execute_from_checkpoint`` reads this to know which
    task to re-enter, with what arguments, and (critically) which
    ``tool_call_id`` to preserve so the previously-granted ``scope=once``
    approval matches.

    ``tool_call_id`` MUST be the same id the original ``execute_tool_call``
    used when it raised ``HITLRequiredError``. Generating a fresh id here
    would defeat the entire PR-series purpose.
    """

    task_id: str
    tool_name: str
    tool_call_id: str
    arguments: Dict[str, Any]


@dataclass(frozen=True)
class DagCheckpoint:
    """
    Single point-in-time snapshot of a paused DAG run.

    One session can hold at most ONE checkpoint at a time (overwrite on save).
    ``plan_json`` is the ``DAGPlan.model_dump_json()`` of the live plan so the
    resume path can rebuild the exact same task graph without re-planning.

    ``completed_outputs`` maps ``task_id → output value`` for tasks that
    already finished before the pause. PR 2 pre-populates ``DAGExecutor``'s
    output context with these so downstream tasks see their dependencies
    satisfied without re-execution.
    """

    session_id: str
    qa_id: str
    plan_json: str
    completed_outputs: Dict[str, Any]
    paused_task: PausedTaskInfo
    created_at: float = field(default_factory=time.time)
    # Schema version — bump when we add fields that the loader needs to
    # detect. PR 1 ships v1; if PR 2 needs to add fields the load helper
    # decides whether to accept the older shape or drop the checkpoint.
    schema_version: int = 1

    def to_dict(self) -> Dict[str, Any]:
        """Serialise for Mongo persistence. Plain JSON-compatible types only."""
        return {
            "session_id": self.session_id,
            "qa_id": self.qa_id,
            "plan_json": self.plan_json,
            "completed_outputs": self.completed_outputs,
            "paused_task": asdict(self.paused_task),
            "created_at": self.created_at,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Optional["DagCheckpoint"]:
        """Rebuild from a Mongo document. Returns None on schema mismatch / bad data."""
        try:
            version = int(raw.get("schema_version") or 0)
            if version != 1:
                logger.info(
                    "DagCheckpoint.from_dict: schema_version=%s (expected 1) "
                    "— treating as missing checkpoint",
                    version,
                )
                return None
            paused_raw = raw.get("paused_task") or {}
            if not isinstance(paused_raw, Mapping):
                return None
            paused = PausedTaskInfo(
                task_id=str(paused_raw.get("task_id") or ""),
                tool_name=str(paused_raw.get("tool_name") or ""),
                tool_call_id=str(paused_raw.get("tool_call_id") or ""),
                arguments=dict(paused_raw.get("arguments") or {}),
            )
            if not paused.task_id or not paused.tool_name or not paused.tool_call_id:
                # A checkpoint with missing critical identifiers is unusable
                # for resume (we'd lose the call_id continuity that makes
                # scope=once work). Treat as no-checkpoint.
                logger.warning(
                    "DagCheckpoint.from_dict: paused_task missing critical "
                    "fields (task_id=%r tool_name=%r tool_call_id=%r); "
                    "rejecting checkpoint",
                    paused.task_id, paused.tool_name, paused.tool_call_id,
                )
                return None
            outputs = raw.get("completed_outputs")
            if not isinstance(outputs, Mapping):
                outputs = {}
            return cls(
                session_id=str(raw.get("session_id") or ""),
                qa_id=str(raw.get("qa_id") or ""),
                plan_json=str(raw.get("plan_json") or ""),
                completed_outputs=dict(outputs),
                paused_task=paused,
                created_at=float(raw.get("created_at") or 0.0),
                schema_version=version,
            )
        except Exception as exc:  # noqa: BLE001 — never crash the resume path
            logger.warning(
                "DagCheckpoint.from_dict: unexpected error %s — rejecting checkpoint",
                exc,
            )
            return None


# ── Size cap helper ──────────────────────────────────────────────────────────


def cap_outputs(
    outputs: Mapping[str, Any],
    *,
    per_output_cap: int = _OUTPUT_BYTES_CAP,
    total_cap: int = _CHECKPOINT_BYTES_CAP,
) -> Tuple[Dict[str, Any], List[str]]:
    """
    Cap output sizes so the checkpoint stays well below Mongo's 16 MiB limit.

    Two-pass algorithm:
      1. Per-output: any value whose JSON encoding exceeds ``per_output_cap``
         is replaced by ``<truncated to N bytes> + suffix`` (string).
      2. Per-checkpoint: if the dict's combined JSON size still exceeds
         ``total_cap``, drop the OLDEST outputs (by insertion order) until
         under cap. Insertion order in Python 3.7+ dicts == task completion
         order, so we drop the earliest tasks first — the resume path most
         likely needs the LATEST outputs as immediate context.

    Returns ``(capped_outputs, dropped_keys)`` so the caller can log a
    structured warning listing exactly which task outputs were sacrificed.
    Pure function (no mongo, no IO) — easy to unit test.
    """
    capped: Dict[str, Any] = {}
    for key, value in outputs.items():
        # Two responsibilities, both required for mongo-safe output:
        #   1. Cap oversized values (truncated string + suffix).
        #   2. Coerce non-basic-JSON values to ``str()`` so BSON write
        #      doesn't choke on custom class instances / bytes / datetime
        #      / etc. ``json.dumps(default=str)`` makes virtually anything
        #      "size-measurable", but the resulting object inside ``capped``
        #      must itself be mongo-encodable. Detect basic JSON-compatible
        #      types separately from the size measurement.
        #
        # ``_is_basic_json`` walks one level deep for dict/list to catch
        # the common case of a dict whose values are basic; pathological
        # nested cases (dict-of-class-instances) will still fail BSON but
        # the outer try/except in ``save_dag_checkpoint`` catches that.
        is_basic = _is_basic_json(value)
        try:
            encoded = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001 — un-serialisable even with default=str
            encoded = json.dumps(str(value), ensure_ascii=False)
            is_basic = False
        if len(encoded) > per_output_cap:
            head = encoded[: per_output_cap - len(_TRUNCATION_SUFFIX)]
            capped[key] = head + _TRUNCATION_SUFFIX
        elif not is_basic:
            capped[key] = str(value)
        else:
            capped[key] = value

    dropped: List[str] = []
    while True:
        total = len(json.dumps(capped, ensure_ascii=False, default=str))
        if total <= total_cap or not capped:
            break
        # Drop oldest (first inserted) — see docstring rationale.
        oldest_key = next(iter(capped))
        capped.pop(oldest_key, None)
        dropped.append(oldest_key)

    return capped, dropped


# ── Mongo persistence ────────────────────────────────────────────────────────
#
# All three helpers follow the established pattern from
# ``runtime.policy.decision_memory``:
#   _coll = await ai_assistant_db.kia_sessions.collection   # double-await
#   await _coll.update_one(...)
#
# ``kia_sessions.collection`` is an @async_property that resolves to the real
# Motor collection only after a second await. A single await yields an
# ``asyncio.Task`` whose ``update_one`` attribute raises silently.


async def save_dag_checkpoint(checkpoint: DagCheckpoint) -> bool:
    """
    Overwrite ``kia_sessions[session_id].dag_checkpoint`` with this snapshot.

    Returns True on persisted write, False on any failure (mongo down, missing
    session doc, serialisation error). Failure NEVER raises — callers (PR 3)
    should treat False as "checkpoint not available; resume will fall back to
    the legacy re-plan path".

    Applies ``cap_outputs`` to ``completed_outputs`` before persisting and
    logs a WARN listing any dropped task_ids so operators can spot patterns
    of oversized outputs (which may indicate a tool returning unbounded data
    that should be paginated).

    Emits ``DAG_CHECKPOINT_SAVED`` span + Prometheus counter for every
    terminal outcome (persisted / session missing / mongo failure) so
    Grafana can chart save success rate (PR 4).
    """
    # Lazy import — keeps the legacy import-graph (which doesn't go
    # through runtime.dag_checkpoint_metrics) byte-identical and lets
    # tests that stub out telemetry fail-soft.
    from vendor_runtime_sdk.runtime.dag_checkpoint_metrics import (
        emit_dag_checkpoint_span,
        record_dag_checkpoint_outcome,
    )
    from vendor_runtime_sdk.runtime.telemetry import SpanType

    if not checkpoint.session_id:
        logger.warning("save_dag_checkpoint: empty session_id — skipped")
        return False
    capped_outputs, dropped = cap_outputs(checkpoint.completed_outputs)
    if dropped:
        logger.warning(
            "save_dag_checkpoint: dropped %d output(s) to fit cap (oldest first) "
            "session=%s dropped_task_ids=%s",
            len(dropped), checkpoint.session_id, dropped,
        )
    doc = checkpoint.to_dict()
    doc["completed_outputs"] = capped_outputs
    try:
        # PR-E3 (SDK extraction §5 PR-E3): ai_assistant_db is now accessed
        # via the ContextStore Protocol.  The legacy
        # dao.mongo.dbs.ai_assistant_db is still used via the
        # _LegacyContextStoreProvider fallback so runtime behaviour is
        # unchanged in Phase 0.  Phase 2 removes the fallback when dao/
        # leaves the engine import surface.
        from vendor_runtime_sdk.runtime.protocols.context_store import get_context_store

        _coll = await get_context_store().get_collection("kia_sessions").collection
        result = await _coll.update_one(
            {"id": checkpoint.session_id},
            {"$set": {"dag_checkpoint": doc}},
            upsert=False,  # session doc should exist; we don't create new sessions here
        )
        # Distinguish "wrote the checkpoint" from "session doc missing
        # so the write silently did nothing". The latter happens in a
        # narrow race window (cleanup deleted the session doc between the
        # agent picking it up and HITL firing). Operators looking at
        # ``persisted`` log lines were previously fooled into thinking
        # checkpoint was on-disk — return False so the caller knows the
        # resume will need to fall back to legacy re-plan.
        if getattr(result, "modified_count", 1) == 0:
            logger.warning(
                "save_dag_checkpoint: session=%s doc not found (race vs cleanup?) "
                "— checkpoint NOT persisted, resume will fall back",
                checkpoint.session_id,
            )
            record_dag_checkpoint_outcome("save_skipped_session_missing")
            emit_dag_checkpoint_span(
                span_type=SpanType.DAG_CHECKPOINT_SAVED,
                session_id=checkpoint.session_id,
                metadata={
                    "outcome": "save_skipped_session_missing",
                    "task_id": checkpoint.paused_task.task_id,
                    "tool_name": checkpoint.paused_task.tool_name,
                },
            )
            return False
        logger.info(
            "save_dag_checkpoint: persisted session=%s qa=%s task=%s tool=%s "
            "outputs=%d (%d dropped)",
            checkpoint.session_id, checkpoint.qa_id,
            checkpoint.paused_task.task_id, checkpoint.paused_task.tool_name,
            len(capped_outputs), len(dropped),
        )
        record_dag_checkpoint_outcome("save_persisted")
        emit_dag_checkpoint_span(
            span_type=SpanType.DAG_CHECKPOINT_SAVED,
            session_id=checkpoint.session_id,
            metadata={
                "outcome": "save_persisted",
                "task_id": checkpoint.paused_task.task_id,
                "tool_name": checkpoint.paused_task.tool_name,
                "prior_outputs": len(capped_outputs),
                "dropped_outputs": len(dropped),
            },
        )
        return True
    except Exception as exc:  # noqa: BLE001 — fail-soft
        logger.warning(
            "save_dag_checkpoint: persistence failed (%s) — resume will fall "
            "back to legacy re-plan path. session=%s",
            exc, checkpoint.session_id,
        )
        record_dag_checkpoint_outcome("save_failed_mongo")
        return False


async def load_dag_checkpoint(session_id: str) -> Optional[DagCheckpoint]:
    """
    Fetch the checkpoint persisted for *session_id*, or None if absent / corrupt.

    None is the correct signal for "fall back to legacy re-plan" in the
    caller. We deliberately don't distinguish "no checkpoint" from "corrupt
    checkpoint" — both mean "stateful resume is not available; degrade
    gracefully". Detailed reason is logged at INFO/WARN for diagnosis.

    Emits ``DAG_CHECKPOINT_RESTORED`` span + Prometheus counter with the
    specific ``outcome`` so dashboards can distinguish missing-checkpoint
    sessions (expected resume traffic) from corrupt-checkpoint sessions
    (real bug surface). Outcomes: ``restore_loaded`` / ``restore_missing``
    / ``restore_corrupt``.
    """
    if not session_id:
        return None
    from vendor_runtime_sdk.runtime.dag_checkpoint_metrics import (
        emit_dag_checkpoint_span,
        record_dag_checkpoint_outcome,
    )
    from vendor_runtime_sdk.runtime.telemetry import SpanType
    try:
        # PR-E3 (SDK extraction §5 PR-E3): ai_assistant_db is now accessed
        # via the ContextStore Protocol.  The legacy
        # dao.mongo.dbs.ai_assistant_db is still used via the
        # _LegacyContextStoreProvider fallback so runtime behaviour is
        # unchanged in Phase 0.  Phase 2 removes the fallback when dao/
        # leaves the engine import surface.
        from vendor_runtime_sdk.runtime.protocols.context_store import get_context_store

        _coll = await get_context_store().get_collection("kia_sessions").collection
        doc = await _coll.find_one(
            {"id": session_id},
            {"dag_checkpoint": 1, "_id": 0},
        )
    except Exception as exc:  # noqa: BLE001 — fail-soft
        logger.warning(
            "load_dag_checkpoint: mongo read failed (%s) session=%s", exc, session_id,
        )
        record_dag_checkpoint_outcome("restore_missing")
        return None
    if not doc or not isinstance(doc.get("dag_checkpoint"), Mapping):
        record_dag_checkpoint_outcome("restore_missing")
        return None
    raw = doc["dag_checkpoint"]
    cp = DagCheckpoint.from_dict(raw)
    if cp is None:
        # ``from_dict`` returned None → schema mismatch / missing critical
        # fields. This is a real bug surface (vs "session never had a
        # checkpoint") so dashboards count it separately.
        record_dag_checkpoint_outcome("restore_corrupt")
        emit_dag_checkpoint_span(
            span_type=SpanType.DAG_CHECKPOINT_RESTORED,
            session_id=session_id,
            metadata={"outcome": "restore_corrupt"},
        )
        return None
    record_dag_checkpoint_outcome("restore_loaded")
    emit_dag_checkpoint_span(
        span_type=SpanType.DAG_CHECKPOINT_RESTORED,
        session_id=session_id,
        metadata={
            "outcome": "restore_loaded",
            "task_id": cp.paused_task.task_id,
            "tool_name": cp.paused_task.tool_name,
            "prior_outputs": len(cp.completed_outputs),
        },
    )
    return cp


async def clear_dag_checkpoint(session_id: str) -> bool:
    """
    Remove the checkpoint AND any leftover once-tokens for *session_id*.

    Called after a successful (or terminally-failed) resume completes —
    the once-tokens were single-use by design but if a token was created
    by ``decision_memory.record`` and the resume never reached
    ``lookup`` (crash mid-resume, agent path bypassed lookup, …), the
    token survives. Clearing both atoms here on resume completion is the
    natural cleanup point (the alternative — orphan tokens lingering until
    TTL — is also handled by ``decision_memory.lookup``'s inline prune,
    but explicit cleanup here keeps the data-store tidy and avoids
    spurious "stale token consumed" log noise on the next turn).

    Returns True if the document was modified (best-effort signal — Mongo
    returns ``modified_count=0`` when there was no checkpoint to clear,
    which is also success from the caller's perspective). False signals a
    real failure (mongo unreachable, etc.); callers don't usually need to
    react to that because checkpoint absence is the desired state and any
    stale checkpoint will be overwritten by the next HITL pause anyway.
    """
    if not session_id:
        return False
    from vendor_runtime_sdk.runtime.dag_checkpoint_metrics import (
        emit_dag_checkpoint_span,
        record_dag_checkpoint_outcome,
    )
    from vendor_runtime_sdk.runtime.telemetry import SpanType
    try:
        # PR-E3 (SDK extraction §5 PR-E3): ai_assistant_db is now accessed
        # via the ContextStore Protocol.  The legacy
        # dao.mongo.dbs.ai_assistant_db is still used via the
        # _LegacyContextStoreProvider fallback so runtime behaviour is
        # unchanged in Phase 0.  Phase 2 removes the fallback when dao/
        # leaves the engine import surface.
        from vendor_runtime_sdk.runtime.protocols.context_store import get_context_store

        _coll = await get_context_store().get_collection("kia_sessions").collection
        await _coll.update_one(
            {"id": session_id},
            {"$unset": {
                "dag_checkpoint": "",
                "hitl_once_tokens": "",
            }},
            upsert=False,
        )
        logger.debug(
            "clear_dag_checkpoint: cleared session=%s (incl. once-tokens)",
            session_id,
        )
        record_dag_checkpoint_outcome("clear_done")
        emit_dag_checkpoint_span(
            span_type=SpanType.DAG_CHECKPOINT_CLEARED,
            session_id=session_id,
            metadata={"outcome": "clear_done"},
        )
        return True
    except Exception as exc:  # noqa: BLE001 — fail-soft
        logger.warning(
            "clear_dag_checkpoint: mongo write failed (%s) session=%s",
            exc, session_id,
        )
        record_dag_checkpoint_outcome("clear_failed")
        return False


__all__ = [
    "DagCheckpoint",
    "PausedTaskInfo",
    "cap_outputs",
    "save_dag_checkpoint",
    "load_dag_checkpoint",
    "clear_dag_checkpoint",
]
