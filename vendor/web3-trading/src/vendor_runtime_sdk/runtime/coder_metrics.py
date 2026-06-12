# -*- coding: utf-8 -*-
"""Coder Agent Prometheus metrics — PR-D1/D3 follow-up.

Domain-specific metrics for the Coder Agent's dynamic-mode hot path.
Complements ``runtime.avatar_metrics`` (Digital Avatar) and the generic
``libs.agent_metrics`` series.

What lives here vs elsewhere
----------------------------
* ``runtime.telemetry.TurnMetrics`` collects in-process per-turn counters
  and exposes aggregate snapshots via ``coder_autonomy_stats()`` (used by
  the runtime dashboard / API). That layer is for in-process / API
  callers — it does NOT push to Prometheus.
* This module IS the Prometheus surface — Counter / Gauge primitives the
  ops layer scrapes for Grafana + alerting. Hooks live in:
  - ``agent.coder.tools.spawn_sibling_milestone`` (PR-D1)
  - ``agent.coder.agent`` task-end path (PR-D3)
* No-op when ``prometheus_client`` is missing, so CLI / offline runs
  remain import-safe (matches the avatar_metrics pattern).
* Recorders never raise — observability must never break the hot path.

Metrics emitted
---------------
* ``coder_spawn_sibling_invocations_total{workspace_id, outcome}`` —
  Counter, every ``spawn_sibling_milestone`` call. ``outcome`` ∈
  {success, denied_cap, denied_budget, denied_validation}.
* ``coder_task_budget_consumed_ratio{workspace_id, mode}`` — Gauge,
  set at task-end with ``consumed_usd / total_usd``. ``mode`` ∈
  {static, dynamic}. Last-write-wins (acceptable for a slow-moving
  signal; the dashboard plots ``avg_over_time`` to smooth).
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from prometheus_client import Counter, Gauge, Histogram
    _HAS_PROMETHEUS = True
except ImportError:  # pragma: no cover — offline fallback
    _HAS_PROMETHEUS = False


# ── Metric definitions ──────────────────────────────────────────────────────

if _HAS_PROMETHEUS:
    CODER_SPAWN_SIBLING_INVOCATIONS = Counter(
        "coder_spawn_sibling_invocations_total",
        "spawn_sibling_milestone tool invocations partitioned by outcome",
        ["workspace_id", "outcome"],
        # outcome:
        #   success            — request enqueued for DAG executor drain
        #   denied_cap         — per-task lifetime spawn-count cap reached (PR-D1 #1)
        #   denied_budget      — TaskRemainingBudget exhausted (PR-D3 #7)
        #   denied_validation  — schema / payload validation failed
    )

    CODER_TASK_BUDGET_CONSUMED_RATIO = Gauge(
        "coder_task_budget_consumed_ratio",
        "Last-completed task's consumed_usd / total_usd ratio (0.0-1.0+)",
        ["workspace_id", "mode"],
        # mode: static (planner-driven DAG) | dynamic (PR-D3 single-ROOT)
    )

    # S3.2 — milestone wall-time histogram.  Buckets chosen from
    # observed V5 baseline distribution: most successful milestones
    # land in 30-300s; the 600s + 1200s buckets catch the long-tail
    # static milestones that still complete.  Anything beyond 1200s
    # rolls into +Inf and the alerting rule fires.
    CODER_MILESTONE_WALL_TIME_SECONDS = Histogram(
        "coder_milestone_wall_time_seconds",
        "Per-milestone wall time partitioned by mode + terminal status",
        ["workspace_id", "mode", "status"],
        buckets=(10.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1200.0),
        # status:
        #   success    — acceptance criteria all passed
        #   failed     — acceptance failed (driver gave up)
        #   aborted    — BoundaryGuard / RecoveryPolicy ABORT
        #   degraded   — RecoveryPolicy DEGRADE (partial result accepted)
    )

    # S3.2 — replan + DAG abort counters for the alerting rules
    # ``replan_success_rate < 50%`` (24h window) and the DAG abort
    # reason pie chart on the Grafana dashboard.
    CODER_REPLAN_ATTEMPTS = Counter(
        "coder_replan_attempts_total",
        "Mid-flight replan attempts partitioned by success",
        ["workspace_id", "success"],
        # success: "true" / "false" (Prometheus labels are strings)
    )

    # Sprint 11 PR-A4 — acceptance failure root-cause counter.  Lets
    # operators chart per-LLM failure mode distribution (e.g.
    # "GLM emits 5x more pipeline-not-supported failures than Claude")
    # and decide where to invest planner-prompt tuning.  Always-on:
    # observability is free at the failure site and the metadata
    # never includes raw command bytes.
    CODER_ACCEPTANCE_FAILURES = Counter(
        "coder_acceptance_failure_total",
        "Acceptance command failures partitioned by structural cause",
        ["workspace_id", "cause", "llm_model"],
        # cause:
        #   parse_failed    — bashlex AST rejected the chain (pipeline,
        #                     subshell, redirect, command substitution,
        #                     malformed bash, oversize, null byte)
        #   denied          — bash allowlist rejected a segment (or the
        #                     PR-A3 state-mutation guard fired)
        #   nonzero_exit    — bash returned non-zero exit code
        #   timeout         — segment / cumulative wall-time exhausted
        #   shell_error     — persistent shell session crashed
        #                     (bash spawn / pipe failure)
        #   cwd_rejected    — schema-v2 cwd resolved outside workspace
        # llm_model: model that emitted the acceptance command ("" if
        #   unknown — e.g. CLI manual entry)
    )

    CODER_DAG_ABORTS = Counter(
        "coder_dag_aborts_total",
        "Task-level DAG aborts partitioned by reason class",
        ["workspace_id", "reason_class"],
        # reason_class:
        #   acceptance     — milestone acceptance criteria failed past retry cap
        #   budget         — task budget exhausted before DAG completion
        #   wall           — task wall-time cap reached
        #   llm_endpoint   — LLM provider returned unrecoverable error
        #   hitl_reject    — human reviewer rejected mid-flight
        #   other          — fallback for unrecognised codes (alert if non-zero)
    )

    # S3.2-bridge — three more surfaces wired so the §7 acceptance row
    # ``Prometheus coder_* metric ≥ 8`` is met.  All three already
    # exist as TurnMetrics aggregates in TelemetryRecorder; this just
    # exposes them at the scrape endpoint for Grafana panels.
    CODER_PROMPT_CACHE_TOKENS = Counter(
        "coder_prompt_cache_tokens_total",
        "Provider prompt-cache token activity (B1)",
        ["workspace_id", "kind"],
        # kind: read (cache hit) | write (cache fill)
    )

    # Sprint 5 PR-3 — hit-ratio Gauge for Grafana cache-degradation alert.
    # Set per-turn from TelemetryRecorder.record_turn when cache activity > 0.
    # Last-write-wins semantics; dashboard plots avg_over_time to smooth.
    CODER_PROMPT_CACHE_HIT_RATIO = Gauge(
        "coder_prompt_cache_hit_ratio",
        "Per-workspace prompt cache hit ratio (read / (read + write))",
        ["workspace_id"],
    )

    CODER_COMPACTION_TRIGGERS = Counter(
        "coder_compaction_triggers_total",
        "Tiered context compaction triggers (B3 + D2)",
        ["workspace_id", "severity"],
        # severity: soft (≥80% util) | hard (≥92% util) — alerting
        # rule fires when hard ≫ soft, signalling oversized contexts.
    )

    CODER_WORKTREE_MERGES = Counter(
        "coder_worktree_merges_total",
        "Per-milestone git worktree merge outcomes (D3)",
        ["workspace_id", "outcome"],
        # outcome: success | conflict — conflict triggers HITL escalation.
    )

    # Sprint 8 PR-3 — get_worker_summary call counter for polling-degradation
    # alerting (P99 > 10/milestone signals LLM prompt regressed into a
    # polling loop; oncall investigates the persona's system prompt).
    CODER_WORKER_SUMMARY_CALLS = Counter(
        "coder_worker_summary_calls_total",
        "get_worker_summary tool invocations (per workspace + outcome)",
        ["workspace_id", "outcome"],
        # outcome: ok | rate_limited | backend_unavailable | backend_error.
    )


# ── Recorder helpers ────────────────────────────────────────────────────────


def record_spawn_sibling_invocation(
    *,
    workspace_id: str,
    outcome: str,
) -> None:
    """Bump ``coder_spawn_sibling_invocations_total`` for this outcome.

    ``outcome`` should be one of: success, denied_cap, denied_budget,
    denied_validation. Unknown values are accepted but log a debug
    line so dashboards don't silently miss new outcomes.
    """
    if not _HAS_PROMETHEUS:
        return
    valid = {"success", "denied_cap", "denied_budget", "denied_validation"}
    if outcome not in valid:
        logger.debug("unknown spawn_sibling outcome: %s", outcome)
    try:
        CODER_SPAWN_SIBLING_INVOCATIONS.labels(
            workspace_id=workspace_id or "",
            outcome=outcome,
        ).inc()
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("CODER_SPAWN_SIBLING_INVOCATIONS.inc failed: %s", exc)


def record_task_budget_consumed_ratio(
    *,
    workspace_id: str,
    mode: str,
    consumed_usd: float,
    total_usd: float,
) -> None:
    """Set ``coder_task_budget_consumed_ratio`` from the task-end snapshot.

    Skipped when ``total_usd <= 0`` (uninitialised tracker) — emitting a
    NaN / inf would corrupt the Grafana ``avg_over_time`` query.
    """
    if not _HAS_PROMETHEUS:
        return
    if total_usd <= 0:
        return
    try:
        ratio = max(0.0, float(consumed_usd) / float(total_usd))
        CODER_TASK_BUDGET_CONSUMED_RATIO.labels(
            workspace_id=workspace_id or "",
            mode=mode or "static",
        ).set(ratio)
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("CODER_TASK_BUDGET_CONSUMED_RATIO.set failed: %s", exc)


# ── Test helpers ────────────────────────────────────────────────────────────


def _read_counter_value(workspace_id: str, outcome: str) -> Optional[float]:
    """Test-only: read the current value of the spawn counter.

    Returns ``None`` when prometheus_client isn't installed; otherwise a
    float (typically int-valued for a Counter).
    """
    if not _HAS_PROMETHEUS:
        return None
    try:
        return CODER_SPAWN_SIBLING_INVOCATIONS.labels(
            workspace_id=workspace_id, outcome=outcome
        )._value.get()  # type: ignore[attr-defined]
    except (AttributeError, KeyError) as exc:
        logger.debug("_read_*_counter helper failed: %s", exc)
        return None


def _read_gauge_value(workspace_id: str, mode: str) -> Optional[float]:
    """Test-only: read the current Gauge value."""
    if not _HAS_PROMETHEUS:
        return None
    try:
        return CODER_TASK_BUDGET_CONSUMED_RATIO.labels(
            workspace_id=workspace_id, mode=mode
        )._value.get()  # type: ignore[attr-defined]
    except (AttributeError, KeyError) as exc:
        logger.debug("_read_*_counter helper failed: %s", exc)
        return None


# ── S3.2 recorders ──────────────────────────────────────────────────────────

_VALID_MILESTONE_STATUSES = frozenset({
    "success", "failed", "aborted", "degraded",
})

_VALID_DAG_ABORT_REASONS = frozenset({
    "acceptance", "budget", "wall",
    "llm_endpoint", "hitl_reject", "other",
})

_VALID_CACHE_KINDS = frozenset({"read", "write"})
_VALID_COMPACTION_SEVERITIES = frozenset({"soft", "hard"})
_VALID_WORKTREE_OUTCOMES = frozenset({"success", "conflict"})


def record_milestone_wall_time(
    *,
    workspace_id: str,
    mode: str,
    status: str,
    seconds: float,
) -> None:
    """Observe a milestone wall-time sample on the histogram.

    Skipped when:
      * prometheus_client is missing (offline / CLI runs)
      * ``seconds`` is non-positive (uninitialised timer)

    Unknown ``status`` values are still recorded (log debug) so a
    new code added by a future PR doesn't disappear from the
    dashboard before metric labels are updated.
    """
    if not _HAS_PROMETHEUS:
        return
    if not isinstance(seconds, (int, float)) or seconds <= 0:
        return
    if status not in _VALID_MILESTONE_STATUSES:
        logger.debug("unknown milestone status: %s", status)
    try:
        CODER_MILESTONE_WALL_TIME_SECONDS.labels(
            workspace_id=workspace_id or "",
            mode=mode or "static",
            status=status,
        ).observe(float(seconds))
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("CODER_MILESTONE_WALL_TIME_SECONDS.observe failed: %s", exc)


def record_replan_attempt(
    *,
    workspace_id: str,
    success: bool,
) -> None:
    """Bump the replan counter.  ``success`` becomes a "true" /
    "false" label (Prometheus labels are strings)."""
    if not _HAS_PROMETHEUS:
        return
    try:
        CODER_REPLAN_ATTEMPTS.labels(
            workspace_id=workspace_id or "",
            success="true" if success else "false",
        ).inc()
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("CODER_REPLAN_ATTEMPTS.inc failed: %s", exc)


def record_dag_abort(
    *,
    workspace_id: str,
    reason_class: str,
) -> None:
    """Bump the DAG abort counter.  Unknown ``reason_class`` values
    are normalised to ``"other"`` so the dashboard never has a
    permanent gap when the runtime emits a new code."""
    if not _HAS_PROMETHEUS:
        return
    if reason_class not in _VALID_DAG_ABORT_REASONS:
        logger.debug(
            "unknown dag abort reason %r — recording as 'other'",
            reason_class,
        )
        reason_class = "other"
    try:
        CODER_DAG_ABORTS.labels(
            workspace_id=workspace_id or "",
            reason_class=reason_class,
        ).inc()
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("CODER_DAG_ABORTS.inc failed: %s", exc)


_VALID_WORKER_SUMMARY_OUTCOMES = frozenset({
    "ok", "rate_limited", "backend_unavailable", "backend_error",
    # ``unknown`` is the catch-all bucket for any outcome string the
    # tool layer emits that isn't in the documented set above; the
    # recorder logs a WARNING (so ops still notices) AND emits to
    # this label so Grafana queries that include `unknown` won't have
    # a permanent gap.
    "unknown",
})


def record_worker_summary_call(
    *,
    workspace_id: str,
    outcome: str,
) -> None:
    """Bump ``coder_worker_summary_calls_total`` for this outcome.

    Unknown outcomes are normalised to ``"unknown"`` and a WARNING
    log line is emitted so ops sees the regression even when the
    Grafana panel filter doesn't include the new value.  Sprint 8 PR-3.
    """
    if not _HAS_PROMETHEUS:
        return
    if outcome not in _VALID_WORKER_SUMMARY_OUTCOMES:
        logger.warning(
            "unknown worker_summary outcome %r — emitting as 'unknown' "
            "(add to _VALID_WORKER_SUMMARY_OUTCOMES if intended)",
            outcome,
        )
        outcome = "unknown"
    try:
        CODER_WORKER_SUMMARY_CALLS.labels(
            workspace_id=workspace_id or "",
            outcome=outcome,
        ).inc()
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("CODER_WORKER_SUMMARY_CALLS.inc failed: %s", exc)


# ── Test helpers (S3.2) ─────────────────────────────────────────────────────


def _read_histogram_count(
    workspace_id: str, mode: str, status: str,
) -> Optional[float]:
    """Test-only: count of observations (NOT the sum) for the
    ``coder_milestone_wall_time_seconds`` histogram at the given
    label set.  Returns ``None`` when prometheus_client is missing.

    Reads via ``collect()`` because ``_buckets`` only stores the
    finite-bound bucket counters — the +Inf bucket (== total count) is
    derived at scrape time and not exposed as a Counter object."""
    if not _HAS_PROMETHEUS:
        return None
    target = {
        "workspace_id": workspace_id,
        "mode": mode,
        "status": status,
    }
    try:
        for metric in CODER_MILESTONE_WALL_TIME_SECONDS.collect():
            for sample in metric.samples:
                if not sample.name.endswith("_count"):
                    continue
                if sample.labels == target:
                    return float(sample.value)
    except (AttributeError, ValueError) as exc:
        # AttributeError — prometheus_client internals shifted between
        # versions; ValueError — sample.value not float-coercible.
        # Either way the test-helper degrades gracefully.
        logger.debug("_read_histogram_count failed: %s", exc)
        return None
    return None


def _read_replan_counter(
    workspace_id: str, success: str,
) -> Optional[float]:
    if not _HAS_PROMETHEUS:
        return None
    try:
        return CODER_REPLAN_ATTEMPTS.labels(
            workspace_id=workspace_id, success=success,
        )._value.get()  # type: ignore[attr-defined]
    except (AttributeError, KeyError) as exc:
        logger.debug("_read_*_counter helper failed: %s", exc)
        return None


def _read_dag_abort_counter(
    workspace_id: str, reason_class: str,
) -> Optional[float]:
    if not _HAS_PROMETHEUS:
        return None
    try:
        return CODER_DAG_ABORTS.labels(
            workspace_id=workspace_id, reason_class=reason_class,
        )._value.get()  # type: ignore[attr-defined]
    except (AttributeError, KeyError) as exc:
        logger.debug("_read_*_counter helper failed: %s", exc)
        return None


def record_prompt_cache_tokens(
    *,
    workspace_id: str,
    kind: str,
    tokens: int,
) -> None:
    """Bump ``coder_prompt_cache_tokens_total`` by *tokens*.

    Skipped when ``tokens <= 0`` — Anthropic returns 0 when no
    breakpoint matched and bumping by 0 wastes a Prometheus write.
    Unknown ``kind`` is normalised to ``read`` (better to misattribute
    than lose the count entirely; alerting rules tolerate the merge).
    """
    if not _HAS_PROMETHEUS:
        return
    if not isinstance(tokens, int) or tokens <= 0:
        return
    if kind not in _VALID_CACHE_KINDS:
        logger.debug("unknown cache kind %r — recording as 'read'", kind)
        kind = "read"
    try:
        CODER_PROMPT_CACHE_TOKENS.labels(
            workspace_id=workspace_id or "",
            kind=kind,
        ).inc(tokens)
    except (AttributeError, ValueError) as exc:  # pragma: no cover
        logger.debug("CODER_PROMPT_CACHE_TOKENS.inc failed: %s", exc)


def record_compaction_trigger(
    *,
    workspace_id: str,
    severity: str,
) -> None:
    """Bump ``coder_compaction_triggers_total{severity}``.

    Unknown ``severity`` is dropped (logged debug) — soft/hard mean
    very different things to the alerting rule and silently merging
    them would corrupt the dashboard.
    """
    if not _HAS_PROMETHEUS:
        return
    if severity not in _VALID_COMPACTION_SEVERITIES:
        logger.debug("unknown compaction severity %r — dropped", severity)
        return
    try:
        CODER_COMPACTION_TRIGGERS.labels(
            workspace_id=workspace_id or "",
            severity=severity,
        ).inc()
    except (AttributeError, ValueError) as exc:  # pragma: no cover
        logger.debug("CODER_COMPACTION_TRIGGERS.inc failed: %s", exc)


def record_worktree_merge(
    *,
    workspace_id: str,
    outcome: str,
) -> None:
    """Bump ``coder_worktree_merges_total{outcome}``.

    Unknown ``outcome`` is dropped — success and conflict map to
    different alerting rules and merging them would mask conflict
    spikes.
    """
    if not _HAS_PROMETHEUS:
        return
    if outcome not in _VALID_WORKTREE_OUTCOMES:
        logger.debug("unknown worktree outcome %r — dropped", outcome)
        return
    try:
        CODER_WORKTREE_MERGES.labels(
            workspace_id=workspace_id or "",
            outcome=outcome,
        ).inc()
    except (AttributeError, ValueError) as exc:  # pragma: no cover
        logger.debug("CODER_WORKTREE_MERGES.inc failed: %s", exc)


def record_prompt_cache_hit_ratio(
    *,
    workspace_id: str,
    ratio: float,
) -> None:
    """Set ``coder_prompt_cache_hit_ratio`` for *workspace_id*.

    Sprint 5 PR-3 — Grafana cache-degradation alert source.
    ``ratio = cache_read / (cache_read + cache_write)``; valid range
    [0.0, 1.0].  Out-of-range / NaN values are silently dropped so a
    bad caller never corrupts the dashboard.
    """
    if not _HAS_PROMETHEUS:
        return
    if not isinstance(ratio, (int, float)):
        return
    if ratio != ratio:  # NaN check (NaN != NaN)
        return
    if ratio < 0.0 or ratio > 1.0:
        return
    try:
        CODER_PROMPT_CACHE_HIT_RATIO.labels(
            workspace_id=workspace_id or "",
        ).set(float(ratio))
    except (AttributeError, ValueError) as exc:  # pragma: no cover
        logger.debug("CODER_PROMPT_CACHE_HIT_RATIO.set failed: %s", exc)


# ── Test helpers (S3.2-bridge) ──────────────────────────────────────────────


def _read_cache_tokens_counter(
    workspace_id: str, kind: str,
) -> Optional[float]:
    if not _HAS_PROMETHEUS:
        return None
    try:
        return CODER_PROMPT_CACHE_TOKENS.labels(
            workspace_id=workspace_id, kind=kind,
        )._value.get()  # type: ignore[attr-defined]
    except (AttributeError, KeyError) as exc:
        logger.debug("_read_cache_tokens_counter failed: %s", exc)
        return None


def _read_compaction_counter(
    workspace_id: str, severity: str,
) -> Optional[float]:
    if not _HAS_PROMETHEUS:
        return None
    try:
        return CODER_COMPACTION_TRIGGERS.labels(
            workspace_id=workspace_id, severity=severity,
        )._value.get()  # type: ignore[attr-defined]
    except (AttributeError, KeyError) as exc:
        logger.debug("_read_compaction_counter failed: %s", exc)
        return None


def _read_worktree_counter(
    workspace_id: str, outcome: str,
) -> Optional[float]:
    if not _HAS_PROMETHEUS:
        return None
    try:
        return CODER_WORKTREE_MERGES.labels(
            workspace_id=workspace_id, outcome=outcome,
        )._value.get()  # type: ignore[attr-defined]
    except (AttributeError, KeyError) as exc:
        logger.debug("_read_worktree_counter failed: %s", exc)
        return None


# ── Sprint 11 PR-A4 — acceptance failure recorder ──────────────────────────

_VALID_ACCEPTANCE_CAUSES = frozenset({
    "parse_failed",
    "denied",
    "nonzero_exit",
    "timeout",
    "shell_error",
    "cwd_rejected",
})


def record_acceptance_failure(
    *,
    workspace_id: str,
    cause: str,
    llm_model: str = "",
) -> None:
    """Bump the acceptance-failure counter at one of the structural
    failure sites in :func:`MilestoneExecutor._verify_command`.

    Recorder never raises — observability must never break the
    failure-handling hot path.  Unknown ``cause`` values are still
    recorded (logged as debug) so a future PR adding a new cause
    string doesn't disappear from the dashboard.
    """
    if not _HAS_PROMETHEUS:
        return
    if cause not in _VALID_ACCEPTANCE_CAUSES:
        logger.debug("unknown acceptance cause: %s", cause)
    try:
        CODER_ACCEPTANCE_FAILURES.labels(
            workspace_id=workspace_id or "",
            cause=cause,
            llm_model=llm_model or "",
        ).inc()
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("CODER_ACCEPTANCE_FAILURES.inc failed: %s", exc)


def _read_acceptance_failure_counter(
    workspace_id: str, cause: str, llm_model: str = ""
) -> Optional[float]:
    """Test-only: read the acceptance-failure counter value."""
    if not _HAS_PROMETHEUS:
        return None
    try:
        return CODER_ACCEPTANCE_FAILURES.labels(
            workspace_id=workspace_id, cause=cause, llm_model=llm_model,
        )._value.get()  # type: ignore[attr-defined]
    except (AttributeError, KeyError) as exc:
        logger.debug("_read_acceptance_failure_counter failed: %s", exc)
        return None


__all__ = [
    "record_spawn_sibling_invocation",
    "record_task_budget_consumed_ratio",
    "record_milestone_wall_time",
    "record_replan_attempt",
    "record_dag_abort",
    "record_prompt_cache_tokens",
    "record_prompt_cache_hit_ratio",
    "record_compaction_trigger",
    "record_worktree_merge",
    "record_acceptance_failure",
]
