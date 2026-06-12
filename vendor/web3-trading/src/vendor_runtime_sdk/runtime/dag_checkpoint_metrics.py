# -*- coding: utf-8 -*-
"""
Prometheus + telemetry surface for the DAG checkpoint stateful-resume
mechanism (Sprint Option-3 PR 4).

Three things live here:
    * ``DAG_CHECKPOINT_RESUME_TOTAL`` — Counter partitioned by ``outcome``
      so dashboards can chart the hit / miss / fallback distribution.
    * ``record_dag_checkpoint_outcome(outcome=…)`` — Prometheus increment
      helper (no-op when prometheus_client is missing).
    * ``emit_dag_checkpoint_span(span_type, session_id, …)`` — convenience
      wrapper around ``TelemetryRecorder.record_span_event`` that fills in
      ``agent_label="dag_checkpoint"`` + scrubs PII (no tool args / outputs
      in metadata — structural facts only).

Why a dedicated module
~~~~~~~~~~~~~~~~~~~~~~
Keeps the call sites in ``runtime.checkpoint.dag_state`` /
``runtime.policy.decision_memory`` thin — they just call one helper
each, no prometheus_client try/except boilerplate inline. Matches the
pattern in ``runtime.coder_metrics`` and ``runtime.avatar_metrics``.

Outcomes (canonical strings)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The ``outcome`` label on ``DAG_CHECKPOINT_RESUME_TOTAL`` and the related
``DAG_CHECKPOINT_*`` span types use this fixed vocabulary so dashboards
written once stay valid across releases:

    ============================= ====================================
    Outcome                       Meaning
    ============================= ====================================
    save_persisted                Checkpoint write returned modified=1
    save_skipped_session_missing  modified_count=0 (race vs cleanup)
    save_skipped_toggle_off       ``dag_stateful_resume`` OFF
    save_failed_mongo             Mongo write raised (fail-soft)
    restore_loaded                Checkpoint loaded + handed to executor
    restore_missing               No checkpoint for this session
    restore_corrupt               Schema mismatch / critical fields nil
    restore_fallback              Resume crashed → legacy re-plan
    consumed_once_token           scope=once token matched + popped
    clear_done                    Both checkpoint + tokens unset
    clear_failed                  Mongo unset raised
    ============================= ====================================

Any change to this list MUST update:
    1. ``_VALID_OUTCOMES`` below (validation guard)
    2. The Grafana panel JSON shipped alongside PR 4 (see
       ``docs/rollback_dag_stateful_resume.md`` §Monitoring)
    3. The dashboard's alert rules if a new outcome is alert-worthy
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ── Outcome vocabulary ─────────────────────────────────────────────────────
_VALID_OUTCOMES = frozenset({
    "save_persisted",
    "save_skipped_session_missing",
    "save_skipped_toggle_off",
    "save_failed_mongo",
    "restore_loaded",
    "restore_missing",
    "restore_corrupt",
    "restore_fallback",
    "consumed_once_token",
    "clear_done",
    "clear_failed",
})


# ── Prometheus surface (no-op when prometheus_client missing) ──────────────
try:
    from prometheus_client import Counter
    _HAS_PROMETHEUS = True
except ImportError:  # pragma: no cover — offline fallback
    _HAS_PROMETHEUS = False


if _HAS_PROMETHEUS:
    DAG_CHECKPOINT_RESUME_TOTAL = Counter(
        "dag_checkpoint_resume_total",
        "DAG checkpoint resume outcomes (Option-3 stateful resume path)",
        ["outcome"],
    )


def record_dag_checkpoint_outcome(outcome: str) -> None:
    """
    Bump ``dag_checkpoint_resume_total{outcome=…}`` by 1.

    Unknown outcomes log a debug warning so dashboards spot new outcome
    strings instead of silently dropping them. NEVER raises — observability
    must not break the hot path.
    """
    if not _HAS_PROMETHEUS:
        return
    if outcome not in _VALID_OUTCOMES:
        logger.debug(
            "dag_checkpoint_metrics: unknown outcome=%r; recording anyway. "
            "If this is intentional, add to _VALID_OUTCOMES + Grafana panel.",
            outcome,
        )
    try:
        DAG_CHECKPOINT_RESUME_TOTAL.labels(outcome=outcome).inc()
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("DAG_CHECKPOINT_RESUME_TOTAL.inc failed: %s", exc)


# ── SpanEvent helper ────────────────────────────────────────────────────────


def emit_dag_checkpoint_span(
    *,
    span_type: str,
    session_id: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Record a ``SpanEvent`` for the checkpoint lifecycle.

    Wraps ``runtime.telemetry.get_recorder().record_span_event(…)`` with a
    consistent ``agent_id="dag_checkpoint"`` so dashboard filters can
    isolate this subsystem. ``metadata`` is passed through but callers MUST
    NOT include tool args, outputs, or user content — only structural
    facts (task_id, tool_name, outcome). Validated at the call site, not
    here, but the docstring sets the contract.

    Fail-soft: any error inside the recorder is caught and logged at
    DEBUG so this never blocks the calling code path.
    """
    if not session_id:
        # Without a session_id the SpanEvent index keys are empty and
        # dashboards can't group — skip rather than emit noise.
        return
    try:
        from vendor_runtime_sdk.runtime.telemetry import SpanEvent, get_recorder
    except Exception as exc:  # noqa: BLE001 — recorder import never blocks
        logger.debug("dag_checkpoint_metrics: telemetry import failed (%s)", exc)
        return
    try:
        recorder = get_recorder()
        if recorder is None:
            return
        recorder.record_span_event(SpanEvent(
            span_type=span_type,
            session_id=session_id,
            agent_id="dag_checkpoint",
            metadata=dict(metadata or {}),
        ))
    except Exception as exc:  # noqa: BLE001 — observability must not break
        logger.debug(
            "dag_checkpoint_metrics: emit_span failed (%s) span_type=%s",
            exc, span_type,
        )


__all__ = [
    "DAG_CHECKPOINT_RESUME_TOTAL",
    "record_dag_checkpoint_outcome",
    "emit_dag_checkpoint_span",
]
