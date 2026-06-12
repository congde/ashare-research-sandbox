# -*- coding: utf-8 -*-
"""
Digital Avatar Platform Prometheus Metrics — S7 (Gap 5/6 monitoring surface).

Domain-specific counters/gauges/histograms for the digital-employee
collaboration platform, complementing the generic ``agent_*`` metrics in
:mod:`libs.agent_metrics`.

All metrics use the ``avatar_`` prefix for namespace isolation.
Labels are intentionally low-cardinality to keep Prometheus happy:

*   ``workspace_id``  — always present; required for isolation in dashboards.
*   ``avatar_id``     — omitted when cardinality would exceed 10k series.
*   ``reason``        — enumerated short string, never free-form user input.

Design notes
------------
*   Every recorder helper is a **no-op** when ``prometheus_client`` is not
    installed, keeping the runtime import-safe even in offline environments
    (CLI Runtime, unit tests, air-gapped deployments).
*   Helpers never raise — observability must never break the hot path.
*   Metric names map 1:1 to the S7 §Monitoring clipboard of
    ``docs/数字员工协同V1实施计划.md`` so Grafana dashboards and
    alertmanager rules can reference them without further translation.
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


# ── Avatar orchestration ─────────────────────────────────────────────────────

if _HAS_PROMETHEUS:
    AVATAR_ORCHESTRATOR_RUNS = Counter(
        "avatar_orchestrator_runs_total",
        "AvatarOrchestrator executions partitioned by mode & outcome",
        ["workspace_id", "mode", "outcome"],
        # mode:    single | coordinator | lane
        # outcome: success | failure | needs_human_review | budget_block
    )

    AVATAR_ORCHESTRATOR_DURATION = Histogram(
        "avatar_orchestrator_duration_seconds",
        "AvatarOrchestrator end-to-end duration (excludes LLM wait)",
        ["mode"],
        buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0),
    )

    AVATAR_BUDGET_BLOCKS = Counter(
        "avatar_budget_blocks_total",
        "Tasks rejected because monthly budget cap would be exceeded",
        ["workspace_id"],
    )

    AVATAR_STATUS_TRANSITIONS = Counter(
        "avatar_status_transitions_total",
        "State transitions on digital_avatars.status",
        ["workspace_id", "from_status", "to_status"],
    )

    AVATAR_ARCHIVE_CASCADE_TASKS = Counter(
        "avatar_archive_cascade_tasks_total",
        "Tasks cancelled in cascade when an avatar is archived",
        ["workspace_id"],
    )

    # ── Git ACL layer ─────────────────────────────────────────────────────────

    GIT_ACL_DECISIONS = Counter(
        "git_acl_decisions_total",
        "Outcome of GitRepoAclHook pre-execution checks",
        ["workspace_id", "decision"],
        # decision: allow | deny_repo | deny_command | deny_access | hitl_required
    )

    GIT_ACL_COMMAND_DENIALS = Counter(
        "git_acl_command_denials_total",
        "git commands blocked by the command whitelist",
        ["workspace_id", "command"],
    )

    GIT_ONBOARDING_SYNCS = Counter(
        "git_onboarding_syncs_total",
        "user_git_permissions refresh events (onboarding / admin / cron)",
        ["workspace_id", "source", "outcome"],
        # source:  onboarding | admin_refresh | celery_cron
        # outcome: upserted | conflict_skipped | failed
    )

    EPHEMERAL_TOKEN_ISSUED = Counter(
        "ephemeral_token_issued_total",
        "Per-task short-lived GitLab deploy tokens issued by Vault",
        ["workspace_id"],
    )

    EPHEMERAL_TOKEN_REVOKE_FAILURES = Counter(
        "ephemeral_token_revoke_failure_total",
        "Failures when revoking ephemeral deploy tokens — hard alert on any",
        ["workspace_id"],
    )

    # ── Code-review (CR) loop ─────────────────────────────────────────────────

    CR_LOOP_ITERATIONS = Histogram(
        "cr_loop_iterations",
        "Number of CR loop iterations before PASS / fail-closed",
        ["workspace_id"],
        buckets=(0, 1, 2, 3),  # hard cap is 2
    )

    CR_LOOP_OUTCOMES = Counter(
        "cr_loop_outcomes_total",
        "CR loop terminal outcomes",
        ["workspace_id", "outcome"],
        # outcome: pass | fail | budget_exceeded | needs_human_review | provider_blocked
    )

    CR_LOOP_BUDGET_EXCEEDED = Counter(
        "cr_loop_budget_exceeded_total",
        "CR loops aborted because CR_LOOP_TOKEN_CAP was exceeded",
        ["workspace_id"],
    )

    CR_SECRET_SCANNER_HITS = Counter(
        "cr_secret_scanner_hits_total",
        "Secret scanner matches before diff enters any LLM",
        ["workspace_id", "rule_id"],
    )

    CR_PROVIDER_DENIALS = Counter(
        "cr_provider_denials_total",
        "CR loops rejected because LLM provider is not on the whitelist",
        ["workspace_id", "provider"],
    )

    CR_PR_LOCK_CONTENTION = Counter(
        "cr_pr_lock_contention_total",
        "CR per-PR lock was held by another avatar when acquire was attempted",
        ["workspace_id"],
    )

    # ── CLI poll + push channel ──────────────────────────────────────────────

    CLI_POLL_REQUESTS = Counter(
        "cli_poll_requests_total",
        "Long-poll requests to /api/v1/staff/tasks",
        ["workspace_id", "status"],
        # status: ok | rate_limited | unauthorized | version_rejected | error
    )

    CLI_POLL_LATENCY = Histogram(
        "cli_poll_latency_seconds",
        "Latency of GET /api/v1/staff/tasks",
        ["workspace_id"],
        buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0),
    )

    CLI_TASK_CANCEL_ACK_LATENCY = Histogram(
        "cli_task_cancel_ack_latency_seconds",
        "Time between cancel_requested_at and cancel_ack_at",
        ["workspace_id"],
        buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
    )

    CLI_OFFLINE_FALLBACK = Counter(
        "cli_offline_fallback_to_lark_total",
        "CLI heartbeat older than threshold → Lark fallback notification fired",
        ["workspace_id"],
    )

    CLI_VERSION_REJECTIONS = Counter(
        "cli_version_rejection_total",
        "Requests rejected by X-Client-Version compat check",
        ["workspace_id", "reason"],
        # reason: below_minimum | malformed | missing
    )

    # ── Webhook ingress ───────────────────────────────────────────────────────

    WEBHOOK_REPLAY_HITS = Counter(
        "webhook_replay_hit_total",
        "Duplicate webhook event_id rejected by Redis replay cache",
        ["provider"],
    )

    WEBHOOK_AUTH_FAILURES = Counter(
        "webhook_auth_failure_total",
        "Webhook rejected by token / HMAC / IP allow-list",
        ["provider"],
    )

    # ── Cost / billing ────────────────────────────────────────────────────────

    AVATAR_COST_BUDGET_USED = Gauge(
        "avatar_cost_budget_used_ratio",
        "Month-to-date cost ÷ monthly_budget_cap (0.0–1.0+)",
        ["workspace_id", "avatar_id"],
    )

    AVATAR_MONTHLY_COST = Gauge(
        "avatar_monthly_cost_usd",
        "Month-to-date cost in USD per avatar (UTC month boundary)",
        ["workspace_id", "avatar_id"],
    )

    BILLING_AGGREGATE_DURATION = Histogram(
        "avatar_billing_aggregate_duration_seconds",
        "Latency of /admin/billing/avatars + /staff/me/billing aggregation",
        ["endpoint"],
        buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0),
    )

    # ── Coordinator state integrity ───────────────────────────────────────────

    COORDINATOR_STATE_CORRUPTION = Counter(
        "coordinator_state_corruption_total",
        "Coordinator thread state failed schema/consistency validation",
        ["workspace_id", "store"],
        # store: mongo | sqlite
    )

    # ── Worker CAS / reclaim ──────────────────────────────────────────────────

    WORKER_CAS_LOST = Counter(
        "worker_cas_lost_total",
        "update_status_cas returned rowcount=0 (zombie write refused)",
        ["workspace_id"],
    )

    WORKER_RECLAIMS = Counter(
        "worker_reclaims_total",
        "Worker successfully reclaimed a task from a stalled predecessor",
        ["workspace_id"],
    )


# ── Helpers ──────────────────────────────────────────────────────────────────
#
# Every helper follows the same pattern:
#   * short-circuit when prometheus_client is not installed
#   * swallow all exceptions (observability must never break the hot path)
#   * coerce labels to strings / empty string when None


def _safe(label: Optional[str]) -> str:
    """Coerce an optional label to a non-empty string."""
    return str(label) if label else "unknown"


def record_avatar_run(
    workspace_id: Optional[str],
    mode: str,
    outcome: str,
    duration_s: Optional[float] = None,
) -> None:
    """Record an AvatarOrchestrator execution."""
    if not _HAS_PROMETHEUS:
        return
    try:
        AVATAR_ORCHESTRATOR_RUNS.labels(
            workspace_id=_safe(workspace_id), mode=mode, outcome=outcome
        ).inc()
        if duration_s is not None:
            AVATAR_ORCHESTRATOR_DURATION.labels(mode=mode).observe(duration_s)
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("avatar_metrics.record_avatar_run failed: %s", exc)


def record_avatar_budget_block(workspace_id: Optional[str]) -> None:
    if not _HAS_PROMETHEUS:
        return
    try:
        AVATAR_BUDGET_BLOCKS.labels(workspace_id=_safe(workspace_id)).inc()
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("avatar_metrics.record_avatar_budget_block failed: %s", exc)


def record_avatar_status_transition(
    workspace_id: Optional[str], from_status: str, to_status: str
) -> None:
    if not _HAS_PROMETHEUS:
        return
    try:
        AVATAR_STATUS_TRANSITIONS.labels(
            workspace_id=_safe(workspace_id),
            from_status=from_status,
            to_status=to_status,
        ).inc()
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("avatar_metrics.record_avatar_status_transition failed: %s", exc)


def record_avatar_archive_cascade(workspace_id: Optional[str], tasks_cancelled: int) -> None:
    if not _HAS_PROMETHEUS or tasks_cancelled <= 0:
        return
    try:
        AVATAR_ARCHIVE_CASCADE_TASKS.labels(
            workspace_id=_safe(workspace_id)
        ).inc(tasks_cancelled)
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("avatar_metrics.record_avatar_archive_cascade failed: %s", exc)


def record_git_acl_decision(
    workspace_id: Optional[str],
    decision: str,
    command: Optional[str] = None,
) -> None:
    if not _HAS_PROMETHEUS:
        return
    try:
        GIT_ACL_DECISIONS.labels(
            workspace_id=_safe(workspace_id), decision=decision
        ).inc()
        if decision == "deny_command" and command:
            GIT_ACL_COMMAND_DENIALS.labels(
                workspace_id=_safe(workspace_id), command=command
            ).inc()
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("avatar_metrics.record_git_acl_decision failed: %s", exc)



def record_ephemeral_token_issued(workspace_id: Optional[str]) -> None:
    if not _HAS_PROMETHEUS:
        return
    try:
        EPHEMERAL_TOKEN_ISSUED.labels(workspace_id=_safe(workspace_id)).inc()
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("avatar_metrics.record_ephemeral_token_issued failed: %s", exc)


def record_ephemeral_token_revoke_failure(workspace_id: Optional[str]) -> None:
    if not _HAS_PROMETHEUS:
        return
    try:
        EPHEMERAL_TOKEN_REVOKE_FAILURES.labels(
            workspace_id=_safe(workspace_id)
        ).inc()
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug(
            "avatar_metrics.record_ephemeral_token_revoke_failure failed: %s", exc
        )


def record_cr_loop(
    workspace_id: Optional[str],
    outcome: str,
    iterations: int,
) -> None:
    if not _HAS_PROMETHEUS:
        return
    try:
        CR_LOOP_OUTCOMES.labels(
            workspace_id=_safe(workspace_id), outcome=outcome
        ).inc()
        CR_LOOP_ITERATIONS.labels(workspace_id=_safe(workspace_id)).observe(iterations)
        if outcome == "budget_exceeded":
            CR_LOOP_BUDGET_EXCEEDED.labels(
                workspace_id=_safe(workspace_id)
            ).inc()
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("avatar_metrics.record_cr_loop failed: %s", exc)


def record_cr_secret_hit(workspace_id: Optional[str], rule_id: str) -> None:
    if not _HAS_PROMETHEUS:
        return
    try:
        CR_SECRET_SCANNER_HITS.labels(
            workspace_id=_safe(workspace_id), rule_id=rule_id
        ).inc()
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("avatar_metrics.record_cr_secret_hit failed: %s", exc)


def record_cr_provider_denial(workspace_id: Optional[str], provider: str) -> None:
    if not _HAS_PROMETHEUS:
        return
    try:
        CR_PROVIDER_DENIALS.labels(
            workspace_id=_safe(workspace_id), provider=_safe(provider)
        ).inc()
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("avatar_metrics.record_cr_provider_denial failed: %s", exc)


def record_cr_pr_lock_contention(workspace_id: Optional[str]) -> None:
    if not _HAS_PROMETHEUS:
        return
    try:
        CR_PR_LOCK_CONTENTION.labels(workspace_id=_safe(workspace_id)).inc()
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("avatar_metrics.record_cr_pr_lock_contention failed: %s", exc)


def record_cli_poll(
    workspace_id: Optional[str],
    status: str,
    duration_s: Optional[float] = None,
) -> None:
    if not _HAS_PROMETHEUS:
        return
    try:
        CLI_POLL_REQUESTS.labels(
            workspace_id=_safe(workspace_id), status=status
        ).inc()
        if duration_s is not None and status == "ok":
            CLI_POLL_LATENCY.labels(
                workspace_id=_safe(workspace_id)
            ).observe(duration_s)
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("avatar_metrics.record_cli_poll failed: %s", exc)


def record_cli_cancel_ack(workspace_id: Optional[str], delta_s: float) -> None:
    if not _HAS_PROMETHEUS or delta_s < 0:
        return
    try:
        CLI_TASK_CANCEL_ACK_LATENCY.labels(
            workspace_id=_safe(workspace_id)
        ).observe(delta_s)
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("avatar_metrics.record_cli_cancel_ack failed: %s", exc)


def record_cli_offline_fallback(workspace_id: Optional[str]) -> None:
    if not _HAS_PROMETHEUS:
        return
    try:
        CLI_OFFLINE_FALLBACK.labels(workspace_id=_safe(workspace_id)).inc()
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("avatar_metrics.record_cli_offline_fallback failed: %s", exc)


def record_cli_version_rejection(workspace_id: Optional[str], reason: str) -> None:
    if not _HAS_PROMETHEUS:
        return
    try:
        CLI_VERSION_REJECTIONS.labels(
            workspace_id=_safe(workspace_id), reason=reason
        ).inc()
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("avatar_metrics.record_cli_version_rejection failed: %s", exc)


def record_webhook_replay_hit(provider: str) -> None:
    if not _HAS_PROMETHEUS:
        return
    try:
        WEBHOOK_REPLAY_HITS.labels(provider=_safe(provider)).inc()
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("avatar_metrics.record_webhook_replay_hit failed: %s", exc)


def record_webhook_auth_failure(provider: str) -> None:
    if not _HAS_PROMETHEUS:
        return
    try:
        WEBHOOK_AUTH_FAILURES.labels(provider=_safe(provider)).inc()
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("avatar_metrics.record_webhook_auth_failure failed: %s", exc)


def set_avatar_budget_used(
    workspace_id: Optional[str], avatar_id: Optional[str], ratio: float
) -> None:
    if not _HAS_PROMETHEUS:
        return
    try:
        AVATAR_COST_BUDGET_USED.labels(
            workspace_id=_safe(workspace_id), avatar_id=_safe(avatar_id)
        ).set(ratio)
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("avatar_metrics.set_avatar_budget_used failed: %s", exc)


def set_avatar_monthly_cost(
    workspace_id: Optional[str], avatar_id: Optional[str], usd: float
) -> None:
    if not _HAS_PROMETHEUS:
        return
    try:
        AVATAR_MONTHLY_COST.labels(
            workspace_id=_safe(workspace_id), avatar_id=_safe(avatar_id)
        ).set(usd)
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("avatar_metrics.set_avatar_monthly_cost failed: %s", exc)


def record_billing_aggregate_latency(endpoint: str, duration_s: float) -> None:
    if not _HAS_PROMETHEUS:
        return
    try:
        BILLING_AGGREGATE_DURATION.labels(endpoint=endpoint).observe(duration_s)
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug(
            "avatar_metrics.record_billing_aggregate_latency failed: %s", exc
        )


def record_coordinator_state_corruption(
    workspace_id: Optional[str], store: str
) -> None:
    if not _HAS_PROMETHEUS:
        return
    try:
        COORDINATOR_STATE_CORRUPTION.labels(
            workspace_id=_safe(workspace_id), store=store
        ).inc()
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug(
            "avatar_metrics.record_coordinator_state_corruption failed: %s", exc
        )


def record_worker_cas_lost(workspace_id: Optional[str]) -> None:
    if not _HAS_PROMETHEUS:
        return
    try:
        WORKER_CAS_LOST.labels(workspace_id=_safe(workspace_id)).inc()
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("avatar_metrics.record_worker_cas_lost failed: %s", exc)


def record_worker_reclaim(workspace_id: Optional[str]) -> None:
    if not _HAS_PROMETHEUS:
        return
    try:
        WORKER_RECLAIMS.labels(workspace_id=_safe(workspace_id)).inc()
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("avatar_metrics.record_worker_reclaim failed: %s", exc)


__all__ = [
    # ── avatar ────────────────────────────────────────────────────────────────
    "record_avatar_run",
    "record_avatar_budget_block",
    "record_avatar_status_transition",
    "record_avatar_archive_cascade",
    # ── git acl ───────────────────────────────────────────────────────────────
    "record_git_acl_decision",
    "record_ephemeral_token_issued",
    "record_ephemeral_token_revoke_failure",
    # ── cr loop ───────────────────────────────────────────────────────────────
    "record_cr_loop",
    "record_cr_secret_hit",
    "record_cr_provider_denial",
    "record_cr_pr_lock_contention",
    # ── cli poll / push ───────────────────────────────────────────────────────
    "record_cli_poll",
    "record_cli_cancel_ack",
    "record_cli_offline_fallback",
    "record_cli_version_rejection",
    # ── webhook ───────────────────────────────────────────────────────────────
    "record_webhook_replay_hit",
    "record_webhook_auth_failure",
    # ── cost / billing ────────────────────────────────────────────────────────
    "set_avatar_budget_used",
    "set_avatar_monthly_cost",
    "record_billing_aggregate_latency",
    # ── coordinator / worker ──────────────────────────────────────────────────
    "record_coordinator_state_corruption",
    "record_worker_cas_lost",
    "record_worker_reclaim",
]
