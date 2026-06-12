# -*- coding: utf-8 -*-
"""
TelemetryRecorder — §11.5

In-memory SLI/SLO tracking for the KuCoin AI Agent runtime.

Components
──────────
TurnMetrics          — per-turn metrics snapshot (timing + counts)
SLISnapshot          — computed SLI values at a point in time
PerformanceBaseline  — §11.5 performance target constants
TelemetryRecorder    — accumulates TurnMetrics; exposes SLI queries

6 performance baselines (§11.5):
  hook_latency        <   5 ms
  policy_eval_latency <   1 ms
  lane_spawn_latency  <  50 ms
  mcp_detect_latency  < 100 ms
  recovery_success    ≥  70 %   (one-shot)
  compaction_savings  ≥  60 %

5 SLI metrics (§11.5.1):
  availability              successful_requests / total_requests
  chat_latency_p50/p95/p99  first-token time distribution (ms)
  session_creation_success  successful_creations / creation_requests
  tool_execution_success    tool_successes / total_tool_calls
  llm_call_success          llm_successes / total_llm_calls

SLO targets (30-day rolling, §11.5.1):
  API Availability           ≥ 99.9 %
  Chat Latency P95           ≤  3 000 ms
  Chat Latency P99           ≤  8 000 ms
  Session Creation Success   ≥ 99.5 %
  Tool Execution Success     ≥ 95.0 %   (7-day)
  LLM Call Success           ≥ 99.0 %   (7-day)

Error budget thresholds:
  > 50 % consumed: normal iteration
  20–50 %:         extra approval required
  < 20 %:          freeze feature releases
    0 %:           post-mortem triggered
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Performance baselines ────────────────────────────────────────────────────────


class PerformanceBaseline:
    """§11.5 performance target constants (all latencies in milliseconds)."""

    HOOK_LATENCY_MAX_MS: float = 5.0
    POLICY_EVAL_LATENCY_MAX_MS: float = 1.0
    LANE_SPAWN_LATENCY_MAX_MS: float = 50.0
    MCP_DETECT_LATENCY_MAX_MS: float = 100.0
    RECOVERY_SUCCESS_MIN: float = 0.70      # 70 % one-shot
    COMPACTION_SAVINGS_MIN: float = 0.60    # 60 % token reduction


# ── SLO targets ───────────────────────────────────────────────────────────────────


class SLOTarget:
    """§11.5.1 SLO target constants."""

    AVAILABILITY_MIN: float = 0.999          # 99.9 %
    CHAT_P95_MAX_MS: float = 3_000.0         # 3 s
    CHAT_P99_MAX_MS: float = 8_000.0         # 8 s
    SESSION_CREATION_MIN: float = 0.995      # 99.5 %
    TOOL_EXECUTION_MIN: float = 0.95         # 95 %
    LLM_CALL_MIN: float = 0.99              # 99 %


# ── TurnMetrics ──────────────────────────────────────────────────────────────────


@dataclass
class TurnMetrics:
    """
    Metrics snapshot recorded at the end of a single agent turn.

    All latencies are in milliseconds.
    """

    # ── Latency measurements (ms) ─────────────────────────────────────────
    hook_latency_ms: float = 0.0
    policy_eval_latency_ms: float = 0.0
    lane_spawn_latency_ms: float = 0.0
    mcp_detect_latency_ms: float = 0.0
    # first_token_ms: end-to-end time from request received to first SSE byte
    first_token_ms: float = 0.0

    # ── Tool call outcomes ────────────────────────────────────────────────
    tool_calls: int = 0
    tool_successes: int = 0

    # ── LLM call outcomes ────────────────────────────────────────────────
    llm_calls: int = 0
    llm_successes: int = 0

    # ── Recovery outcomes ────────────────────────────────────────────────
    recovery_attempts: int = 0
    recovery_successes: int = 0

    # ── Compaction ───────────────────────────────────────────────────────
    # 0.0–1.0: fraction of tokens removed (0.7 = 70 % compressed)
    compaction_savings_ratio: float = 0.0

    # ── Policy decisions ─────────────────────────────────────────────────
    # action_type → count, e.g. {"allow": 3, "deny": 1}
    policy_decisions: Dict[str, int] = field(default_factory=dict)

    # ── Session creation ─────────────────────────────────────────────────
    session_create_attempted: bool = False
    session_create_success: bool = False

    # ── Request outcome ───────────────────────────────────────────────────
    request_success: bool = True  # False = 5xx-class error

    # ── Coder Agent 长程自主化 (§8 of docs/Coder-Agent长程自主化技术方案.md) ──
    # All fields default 0; existing call sites remain unchanged.

    # B1 — provider prompt cache (tokens served from cache vs newly cached)
    cache_read_input_tokens: int = 0
    cache_write_input_tokens: int = 0

    # B2 — read_file content-hash dedup hits
    read_dedup_hits: int = 0

    # B3 + D2 — tiered compaction trigger counts (per turn)
    compaction_soft_triggers: int = 0
    compaction_hard_triggers: int = 0

    # D1 — steering messages drained at start of turn
    steering_messages_consumed: int = 0

    # C1 — mid-flight replan attempts / successes
    replan_attempts: int = 0
    replan_successes: int = 0

    # C2 — DAG dynamic expansion requests (accepted vs rejected by BoundaryGuard)
    dag_expansions_requested: int = 0
    dag_expansions_accepted: int = 0
    dag_expansions_rejected: int = 0

    # PR-D1 #1 mitigation — count LLM-driven spawn_sibling_milestone tool
    # invocations (separate from C2's drain-side counters above). Drives
    # the Grafana ``kc_coder.spawn_sibling.rate`` alert: per-task baseline
    # is 0; >2 / task in canary week triggers re-evaluation of the cap.
    spawn_sibling_invocations: int = 0

    # C3 — DAG-level checkpoints written
    checkpoints_written: int = 0

    # C4 — mandatory Grader decisions
    grader_invocations: int = 0
    grader_fails: int = 0
    grader_escalations: int = 0

    # D3 — git worktree merge outcomes (parallel milestones)
    worktree_merges_success: int = 0
    worktree_merges_conflict: int = 0

    # OS Sandbox — process isolation metrics
    sandbox_exec_count: int = 0
    sandbox_exec_noop_count: int = 0
    sandbox_violations: int = 0
    sandbox_timeouts: int = 0
    sandbox_oom_kills: int = 0
    sandbox_wall_time_ms_total: float = 0.0

    # Sprint 1 PR-G — TUI/Web runtime convergence telemetry
    # Identifies which ``StorageBackend`` Protocol implementation handled
    # this turn's persistence (``mongo`` server / ``sqlite`` CLI/TUI).
    # ``None`` means storage was not wired (pre-Sprint-0 baseline behaviour
    # OR ``ConversationRuntime`` constructed without ``storage=...``).
    # Dashboards can partition every other metric by this label to detect
    # backend-specific regressions; alerting fires if the ratio of
    # ``None`` turns exceeds a threshold in environments where storage
    # injection is supposed to be ON.
    storage_backend_name: Optional[str] = None


# ── SLI snapshot ─────────────────────────────────────────────────────────────────


@dataclass
class SLISnapshot:
    """
    SLI values computed from accumulated TurnMetrics.

    Returned by TelemetryRecorder.get_sli_snapshot().
    """

    # ── SLI values ────────────────────────────────────────────────────────
    availability: float = 1.0
    chat_latency_p50_ms: float = 0.0
    chat_latency_p95_ms: float = 0.0
    chat_latency_p99_ms: float = 0.0
    session_creation_success: float = 1.0
    tool_execution_success: float = 1.0
    llm_call_success: float = 1.0

    # ── Performance baseline violations (counts since last reset) ─────────
    hook_latency_violations: int = 0
    policy_eval_violations: int = 0
    lane_spawn_violations: int = 0
    mcp_detect_violations: int = 0

    # ── SLO compliance flags ──────────────────────────────────────────────
    @property
    def slo_availability_ok(self) -> bool:
        return self.availability >= SLOTarget.AVAILABILITY_MIN

    @property
    def slo_chat_p95_ok(self) -> bool:
        return self.chat_latency_p95_ms <= SLOTarget.CHAT_P95_MAX_MS

    @property
    def slo_chat_p99_ok(self) -> bool:
        return self.chat_latency_p99_ms <= SLOTarget.CHAT_P99_MAX_MS

    @property
    def slo_session_ok(self) -> bool:
        return self.session_creation_success >= SLOTarget.SESSION_CREATION_MIN

    @property
    def slo_tool_ok(self) -> bool:
        return self.tool_execution_success >= SLOTarget.TOOL_EXECUTION_MIN

    @property
    def slo_llm_ok(self) -> bool:
        return self.llm_call_success >= SLOTarget.LLM_CALL_MIN

    def all_slo_ok(self) -> bool:
        return all([
            self.slo_availability_ok,
            self.slo_chat_p95_ok,
            self.slo_chat_p99_ok,
            self.slo_session_ok,
            self.slo_tool_ok,
            self.slo_llm_ok,
        ])

    def error_budget_consumed(self, slo: str) -> float:
        """
        Return the fraction of the error budget consumed for *slo*.

        0.0 = no budget consumed (SLO fully met)
        1.0 = budget fully consumed (SLO at limit)
        >1.0 = budget exceeded

        slo must be one of: "availability", "chat_p95", "chat_p99",
        "session_creation", "tool_execution", "llm_call".
        """
        if slo == "availability":
            budget = 1.0 - SLOTarget.AVAILABILITY_MIN         # 0.001
            shortfall = max(0.0, SLOTarget.AVAILABILITY_MIN - self.availability)
            return shortfall / budget if budget > 0 else 0.0

        if slo == "chat_p95":
            # Latency budget: how far over the target are we?
            return max(0.0, self.chat_latency_p95_ms - SLOTarget.CHAT_P95_MAX_MS) / SLOTarget.CHAT_P95_MAX_MS

        if slo == "chat_p99":
            return max(0.0, self.chat_latency_p99_ms - SLOTarget.CHAT_P99_MAX_MS) / SLOTarget.CHAT_P99_MAX_MS

        if slo == "session_creation":
            budget = 1.0 - SLOTarget.SESSION_CREATION_MIN
            shortfall = max(0.0, SLOTarget.SESSION_CREATION_MIN - self.session_creation_success)
            return shortfall / budget if budget > 0 else 0.0

        if slo == "tool_execution":
            budget = 1.0 - SLOTarget.TOOL_EXECUTION_MIN
            shortfall = max(0.0, SLOTarget.TOOL_EXECUTION_MIN - self.tool_execution_success)
            return shortfall / budget if budget > 0 else 0.0

        if slo == "llm_call":
            budget = 1.0 - SLOTarget.LLM_CALL_MIN
            shortfall = max(0.0, SLOTarget.LLM_CALL_MIN - self.llm_call_success)
            return shortfall / budget if budget > 0 else 0.0

        raise ValueError(f"Unknown SLO name: '{slo}'")


# ── Latency histogram ─────────────────────────────────────────────────────────────


class _LatencyHistogram:
    """
    Circular buffer of latency samples for percentile computation.

    Evicts the oldest sample when the buffer is full (reservoir-style).
    All latencies in milliseconds.
    """

    def __init__(self, max_samples: int = 10_000) -> None:
        self._samples: deque[float] = deque(maxlen=max_samples)
        self._lock = threading.Lock()

    def record(self, latency_ms: float) -> None:
        with self._lock:
            self._samples.append(latency_ms)

    def percentile(self, pct: float) -> float:
        """
        Return the *pct*-th percentile (0–100).

        Returns 0.0 if no samples have been recorded.
        """
        with self._lock:
            if not self._samples:
                return 0.0
            sorted_samples = sorted(self._samples)
            idx = max(0, int(len(sorted_samples) * pct / 100) - 1)
            return sorted_samples[idx]

    def count(self) -> int:
        with self._lock:
            return len(self._samples)

    def clear(self) -> None:
        with self._lock:
            self._samples.clear()


# ── TelemetryRecorder ─────────────────────────────────────────────────────────────


class TelemetryRecorder:
    """
    Accumulates TurnMetrics and exposes SLI/SLO queries.

    Thread-safe: all mutations are protected by a single lock.

    Usage::

        recorder = TelemetryRecorder()
        recorder.record_turn(TurnMetrics(
            first_token_ms=450.0,
            tool_calls=2, tool_successes=2,
            llm_calls=1, llm_successes=1,
            request_success=True,
        ))
        snapshot = recorder.get_sli_snapshot()
        if not snapshot.slo_chat_p95_ok:
            alert(...)
    """

    def __init__(self, max_latency_samples: int = 10_000) -> None:
        self._lock = threading.Lock()

        # Request availability counters
        self._total_requests: int = 0
        self._successful_requests: int = 0

        # Session creation counters
        self._session_create_attempts: int = 0
        self._session_create_successes: int = 0

        # Tool execution counters
        self._total_tool_calls: int = 0
        self._tool_call_successes: int = 0

        # LLM call counters
        self._total_llm_calls: int = 0
        self._llm_call_successes: int = 0

        # Latency histograms
        self._chat_latency = _LatencyHistogram(max_latency_samples)

        # Performance baseline violation counters
        self._hook_violations: int = 0
        self._policy_eval_violations: int = 0
        self._lane_spawn_violations: int = 0
        self._mcp_detect_violations: int = 0

        # Recovery tracking
        self._recovery_attempts: int = 0
        self._recovery_successes: int = 0

        # Self-evolution engine counters (cross-session, process-level)
        self._evolution_nudges: int = 0
        self._evolution_reviews: int = 0
        self._evolution_drafts: int = 0

        # Span events (Phase 3 P2) — bounded circular buffer
        self._span_events: deque[SpanEvent] = deque(maxlen=10_000)

        # ── Coder Agent 长程自主化 aggregate counters (§8) ───────────────────
        # Monotonically increasing; reset() zeros them for test isolation.
        self._coder_cache_read_tokens: int = 0
        self._coder_cache_write_tokens: int = 0
        self._coder_read_dedup_hits: int = 0
        self._coder_steering_consumed: int = 0
        self._coder_compaction_soft: int = 0
        self._coder_compaction_hard: int = 0
        self._coder_replan_attempts: int = 0
        self._coder_replan_successes: int = 0
        self._coder_dag_expansion_requested: int = 0
        self._coder_dag_expansion_accepted: int = 0
        self._coder_dag_expansion_rejected: int = 0
        # PR-D1 #1 — LLM-driven spawn_sibling_milestone tool invocations.
        self._coder_spawn_sibling_invocations: int = 0
        self._coder_checkpoints_written: int = 0
        self._coder_grader_invocations: int = 0
        self._coder_grader_fails: int = 0
        self._coder_grader_escalations: int = 0
        self._coder_worktree_success: int = 0
        self._coder_worktree_conflict: int = 0

        # ── Root-cause-fix-plan SLI counters (F2 / F7 / F8) ──────────────
        # Per docs/CoderAgent-多文件任务完成率根因修复方案.md observability
        # follow-up. Monotonic; reset() zeros for test isolation.
        self._coder_f7_denied: int = 0
        self._coder_f8_blocked: int = 0
        self._coder_f8_warn: int = 0
        self._coder_f2_hint_injected: int = 0
        self._coder_f2_tools_restricted: int = 0
        self._coder_f2_aborted: int = 0

    # ── Core recording API ────────────────────────────────────────────────────

    def record_turn(self, metrics: TurnMetrics) -> None:
        """
        Ingest a TurnMetrics snapshot.

        Called at the end of each agent turn.  Must be fast and non-blocking.
        """
        with self._lock:
            # Availability
            self._total_requests += 1
            if metrics.request_success:
                self._successful_requests += 1

            # Session creation
            if metrics.session_create_attempted:
                self._session_create_attempts += 1
                if metrics.session_create_success:
                    self._session_create_successes += 1

            # Tool calls
            self._total_tool_calls += metrics.tool_calls
            self._tool_call_successes += metrics.tool_successes

            # LLM calls
            self._total_llm_calls += metrics.llm_calls
            self._llm_call_successes += metrics.llm_successes

            # Recoveries
            self._recovery_attempts += metrics.recovery_attempts
            self._recovery_successes += metrics.recovery_successes

            # Performance baseline violations
            if metrics.hook_latency_ms > PerformanceBaseline.HOOK_LATENCY_MAX_MS:
                self._hook_violations += 1
            if metrics.policy_eval_latency_ms > PerformanceBaseline.POLICY_EVAL_LATENCY_MAX_MS:
                self._policy_eval_violations += 1
            if metrics.lane_spawn_latency_ms > PerformanceBaseline.LANE_SPAWN_LATENCY_MAX_MS:
                self._lane_spawn_violations += 1
            if metrics.mcp_detect_latency_ms > PerformanceBaseline.MCP_DETECT_LATENCY_MAX_MS:
                self._mcp_detect_violations += 1

            # Coder Agent 长程自主化 aggregates (§8) — monotonic increments.
            self._coder_cache_read_tokens += metrics.cache_read_input_tokens
            self._coder_cache_write_tokens += metrics.cache_write_input_tokens
            self._coder_read_dedup_hits += metrics.read_dedup_hits
            self._coder_steering_consumed += metrics.steering_messages_consumed
            self._coder_compaction_soft += metrics.compaction_soft_triggers
            self._coder_compaction_hard += metrics.compaction_hard_triggers
            self._coder_replan_attempts += metrics.replan_attempts
            self._coder_replan_successes += metrics.replan_successes
            self._coder_dag_expansion_requested += metrics.dag_expansions_requested
            self._coder_dag_expansion_accepted += metrics.dag_expansions_accepted
            self._coder_dag_expansion_rejected += metrics.dag_expansions_rejected
            self._coder_spawn_sibling_invocations += metrics.spawn_sibling_invocations
            self._coder_checkpoints_written += metrics.checkpoints_written
            self._coder_grader_invocations += metrics.grader_invocations
            self._coder_grader_fails += metrics.grader_fails
            self._coder_grader_escalations += metrics.grader_escalations
            self._coder_worktree_success += metrics.worktree_merges_success
            self._coder_worktree_conflict += metrics.worktree_merges_conflict

        # Chat latency is recorded outside the main lock (histogram has its own)
        if metrics.first_token_ms > 0:
            self._chat_latency.record(metrics.first_token_ms)

        # S3.2-bridge — fan out the per-turn coder counters to Prometheus
        # so the §7 acceptance row "Prometheus coder_* metric ≥ 8" is met
        # at scrape time (in-process aggregates above stay for the
        # ``coder_autonomy_stats`` API surface).  All recorders are
        # fail-soft when prometheus_client is missing.
        ws = getattr(metrics, "workspace_id", "") or ""
        try:
            from vendor_runtime_sdk.runtime.coder_metrics import (
                record_compaction_trigger,
                record_prompt_cache_hit_ratio,
                record_prompt_cache_tokens,
                record_worktree_merge,
            )
            if metrics.cache_read_input_tokens > 0:
                record_prompt_cache_tokens(
                    workspace_id=ws, kind="read",
                    tokens=metrics.cache_read_input_tokens,
                )
            if metrics.cache_write_input_tokens > 0:
                record_prompt_cache_tokens(
                    workspace_id=ws, kind="write",
                    tokens=metrics.cache_write_input_tokens,
                )

            # Sprint 5 PR-3 — hit-ratio Gauge + PROMPT_CACHE_HIT span.
            # Only fire when there's any cache activity (read or write);
            # zero-activity turns leave the gauge alone so it reflects
            # the last meaningful sample (Grafana avg_over_time smooths).
            cache_total = metrics.cache_read_input_tokens + metrics.cache_write_input_tokens
            if cache_total > 0:
                ratio = metrics.cache_read_input_tokens / cache_total
                record_prompt_cache_hit_ratio(workspace_id=ws, ratio=ratio)
                self.record_span_event(SpanEvent(
                    span_type=SpanType.PROMPT_CACHE_HIT,
                    metadata={
                        "read_tokens": metrics.cache_read_input_tokens,
                        "write_tokens": metrics.cache_write_input_tokens,
                        "ratio": round(ratio, 4),
                        "workspace_id": ws,
                    },
                ))

            for _ in range(metrics.compaction_soft_triggers):
                record_compaction_trigger(workspace_id=ws, severity="soft")
            for _ in range(metrics.compaction_hard_triggers):
                record_compaction_trigger(workspace_id=ws, severity="hard")
            for _ in range(metrics.worktree_merges_success):
                record_worktree_merge(workspace_id=ws, outcome="success")
            for _ in range(metrics.worktree_merges_conflict):
                record_worktree_merge(workspace_id=ws, outcome="conflict")
        except Exception as exc:  # pragma: no cover — observability never aborts
            logger.debug("coder_metrics bridge failed: %s", exc)

        logger.debug(
            "TelemetryRecorder.record_turn: requests=%d, tool_calls=%d, llm_calls=%d",
            self._total_requests,
            self._total_tool_calls,
            self._total_llm_calls,
        )

    # ── SLI query ─────────────────────────────────────────────────────────────

    def get_sli_snapshot(self) -> SLISnapshot:
        """
        Compute and return the current SLI values.

        O(n log n) due to percentile calculation; cache the result if
        called in a tight loop.
        """
        with self._lock:
            total_req = self._total_requests
            ok_req = self._successful_requests
            sess_att = self._session_create_attempts
            sess_ok = self._session_create_successes
            tool_total = self._total_tool_calls
            tool_ok = self._tool_call_successes
            llm_total = self._total_llm_calls
            llm_ok = self._llm_call_successes
            hook_v = self._hook_violations
            policy_v = self._policy_eval_violations
            lane_v = self._lane_spawn_violations
            mcp_v = self._mcp_detect_violations

        return SLISnapshot(
            availability=ok_req / total_req if total_req > 0 else 1.0,
            chat_latency_p50_ms=self._chat_latency.percentile(50),
            chat_latency_p95_ms=self._chat_latency.percentile(95),
            chat_latency_p99_ms=self._chat_latency.percentile(99),
            session_creation_success=sess_ok / sess_att if sess_att > 0 else 1.0,
            tool_execution_success=tool_ok / tool_total if tool_total > 0 else 1.0,
            llm_call_success=llm_ok / llm_total if llm_total > 0 else 1.0,
            hook_latency_violations=hook_v,
            policy_eval_violations=policy_v,
            lane_spawn_violations=lane_v,
            mcp_detect_violations=mcp_v,
        )

    # ── Accessors ─────────────────────────────────────────────────────────────

    def total_turns(self) -> int:
        """Total number of turns recorded since last reset."""
        with self._lock:
            return self._total_requests

    def recovery_success_rate(self) -> float:
        """
        One-shot recovery success rate.

        Returns 1.0 (100 %) if no recovery has been attempted.
        """
        with self._lock:
            if self._recovery_attempts == 0:
                return 1.0
            return self._recovery_successes / self._recovery_attempts

    # ── Coder Agent 长程自主化 stats (§8 成功指标) ──────────────────────────

    def cache_hit_ratio(self) -> float:
        """Prompt cache hit ratio for B1 (§8 target ≥ 0.6 for long tasks).

        cache_read_input_tokens / (cache_read + cache_write_input_tokens).
        Returns 0.0 when no cache activity has been observed (not 1.0, which
        would falsely suggest a fully-cached state).
        """
        with self._lock:
            total = self._coder_cache_read_tokens + self._coder_cache_write_tokens
            if total == 0:
                return 0.0
            return self._coder_cache_read_tokens / total

    def coder_autonomy_stats(self) -> Dict[str, int]:
        """Return a snapshot of all Coder Agent 长程自主化 aggregate counters.

        Maps to §8 of docs/Coder-Agent长程自主化技术方案.md.
        Callers can export this to Prometheus, dashboards, or benchmark reports.
        """
        with self._lock:
            return {
                # B1 cache
                "cache_read_input_tokens": self._coder_cache_read_tokens,
                "cache_write_input_tokens": self._coder_cache_write_tokens,
                # B2 read dedup
                "read_dedup_hits": self._coder_read_dedup_hits,
                # B3 + D2 compaction
                "compaction_soft_triggers": self._coder_compaction_soft,
                "compaction_hard_triggers": self._coder_compaction_hard,
                # D1 steering
                "steering_messages_consumed": self._coder_steering_consumed,
                # C1 replan
                "replan_attempts": self._coder_replan_attempts,
                "replan_successes": self._coder_replan_successes,
                # C2 expansion
                "dag_expansions_requested": self._coder_dag_expansion_requested,
                "dag_expansions_accepted": self._coder_dag_expansion_accepted,
                "dag_expansions_rejected": self._coder_dag_expansion_rejected,
                # PR-D1 #1 — LLM-driven spawn invocations
                "spawn_sibling_invocations": self._coder_spawn_sibling_invocations,
                # C3 checkpoint
                "checkpoints_written": self._coder_checkpoints_written,
                # C4 grader
                "grader_invocations": self._coder_grader_invocations,
                "grader_fails": self._coder_grader_fails,
                "grader_escalations": self._coder_grader_escalations,
                # D3 worktree
                "worktree_merges_success": self._coder_worktree_success,
                "worktree_merges_conflict": self._coder_worktree_conflict,
            }

    # ── Root-cause-fix-plan SLI counters (F2 / F7 / F8) ────────────────────
    #
    # Each ``inc_*`` is fire-and-forget (thread-safe atomic-ish bump under
    # the same lock as the main aggregates).  Called from the F2/F7/F8
    # emit sites alongside ``record_span_event`` so dashboards have both
    # diagnostic spans AND monotonic counters for SLI alerts.

    def inc_f7_denied(self) -> None:
        """PR-F7 — bump on a PermissionEnforcer denial outcome."""
        with self._lock:
            self._coder_f7_denied += 1

    def inc_f8_blocked(self) -> None:
        """PR-F8 — bump on a Bash mode_validation BLOCK."""
        with self._lock:
            self._coder_f8_blocked += 1

    def inc_f8_warn(self) -> None:
        """PR-F8 — bump on a Bash mode_validation WARN."""
        with self._lock:
            self._coder_f8_warn += 1

    def inc_f2_hint_injected(self) -> None:
        """PR-F2 — bump when streak=2 triggers ``inject_hint``."""
        with self._lock:
            self._coder_f2_hint_injected += 1

    def inc_f2_tools_restricted(self) -> None:
        """PR-F2 — bump when streak=3 triggers ``restrict_tools``."""
        with self._lock:
            self._coder_f2_tools_restricted += 1

    def inc_f2_aborted(self) -> None:
        """PR-F2 — bump when streak >= 5 triggers ``abort``."""
        with self._lock:
            self._coder_f2_aborted += 1

    def root_cause_stats(self) -> Dict[str, int]:
        """Return a snapshot of all F2/F7/F8 SLI counters.

        Maps to docs/CoderAgent-多文件任务完成率根因修复方案.md
        observability follow-up.  Callers can scrape this for
        Prometheus / dashboards / canary-rollout success criteria.
        """
        with self._lock:
            return {
                "f7_denied_count": self._coder_f7_denied,
                "f8_blocked_count": self._coder_f8_blocked,
                "f8_warn_count": self._coder_f8_warn,
                "f2_hint_injected_count": self._coder_f2_hint_injected,
                "f2_tools_restricted_count": self._coder_f2_tools_restricted,
                "f2_aborted_count": self._coder_f2_aborted,
            }

    def baseline_violation_count(self, baseline: str) -> int:
        """
        Return violation count for one of the 4 latency baselines.

        baseline must be one of: "hook", "policy_eval", "lane_spawn", "mcp_detect".
        """
        with self._lock:
            if baseline == "hook":
                return self._hook_violations
            if baseline == "policy_eval":
                return self._policy_eval_violations
            if baseline == "lane_spawn":
                return self._lane_spawn_violations
            if baseline == "mcp_detect":
                return self._mcp_detect_violations
        raise ValueError(f"Unknown baseline: '{baseline}'")

    # ── Span events (Phase 3 P2) ──────────────────────────────────────────────

    def record_evolution_event(self, event_type: str) -> None:
        """Record a self-evolution engine event (cross-session counter)."""
        with self._lock:
            if event_type == "nudge":
                self._evolution_nudges += 1
            elif event_type == "review_completed":
                self._evolution_reviews += 1
            elif event_type == "draft_created":
                self._evolution_drafts += 1

    @property
    def evolution_stats(self) -> dict:
        """Return cross-session evolution counters."""
        with self._lock:
            return {
                "nudges": self._evolution_nudges,
                "reviews_completed": self._evolution_reviews,
                "drafts_created": self._evolution_drafts,
            }

    def record_span_event(self, event: SpanEvent) -> None:
        """
        Record a SpanEvent lifecycle marker.

        Span events are stored in a bounded circular buffer.  They do not affect
        SLI/SLO counters but are available for diagnostic queries and export.
        Thread-safe; fast (no blocking I/O).

        §7.1: Also bridges to the active OTEL span as a span event (fail-soft).
        """
        with self._lock:
            self._span_events.append(event)
        logger.debug(
            "SpanEvent[%s] session=%s agent=%s",
            event.span_type, event.session_id, event.agent_id,
        )
        # §7.1 Bridge: emit as OTEL span event on the currently active span
        try:
            from vendor_runtime_sdk.runtime.otel import add_span_event as _add_otel_event
            _add_otel_event(
                span_type=event.span_type,
                metadata=dict(event.metadata) if event.metadata else {},
            )
        except Exception:
            pass

    def get_span_events(
        self,
        span_type: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 500,
    ) -> List[SpanEvent]:
        """
        Return recent SpanEvents, optionally filtered by span_type and session_id.

        Events are returned in insertion order (oldest first).
        *limit* caps the result to avoid unbounded output.
        """
        with self._lock:
            events: List[SpanEvent] = list(self._span_events)

        if span_type:
            events = [e for e in events if e.span_type == span_type]
        if session_id:
            events = [e for e in events if e.session_id == session_id]
        return events[-limit:]

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def reset(self) -> None:
        """
        Reset all counters and histograms.

        Intended for tests and rolling-window resets (not for production
        steady-state: counters are meant to be monotonically increasing).
        """
        with self._lock:
            self._total_requests = 0
            self._successful_requests = 0
            self._session_create_attempts = 0
            self._session_create_successes = 0
            self._total_tool_calls = 0
            self._tool_call_successes = 0
            self._total_llm_calls = 0
            self._llm_call_successes = 0
            self._recovery_attempts = 0
            self._recovery_successes = 0
            self._hook_violations = 0
            self._policy_eval_violations = 0
            self._lane_spawn_violations = 0
            self._mcp_detect_violations = 0
            # Coder Agent 长程自主化 counters
            self._coder_cache_read_tokens = 0
            self._coder_cache_write_tokens = 0
            self._coder_read_dedup_hits = 0
            self._coder_steering_consumed = 0
            self._coder_compaction_soft = 0
            self._coder_compaction_hard = 0
            self._coder_replan_attempts = 0
            self._coder_replan_successes = 0
            self._coder_dag_expansion_requested = 0
            self._coder_dag_expansion_accepted = 0
            self._coder_dag_expansion_rejected = 0
            self._coder_spawn_sibling_invocations = 0
            self._coder_checkpoints_written = 0
            self._coder_grader_invocations = 0
            self._coder_grader_fails = 0
            self._coder_grader_escalations = 0
            self._coder_worktree_success = 0
            self._coder_worktree_conflict = 0
            # Root-cause-fix-plan SLI counters
            self._coder_f7_denied = 0
            self._coder_f8_blocked = 0
            self._coder_f8_warn = 0
            self._coder_f2_hint_injected = 0
            self._coder_f2_tools_restricted = 0
            self._coder_f2_aborted = 0
        self._chat_latency.clear()
        with self._lock:
            self._span_events.clear()
        logger.info("TelemetryRecorder: counters reset")


# ── Span events (Phase 3 P2) ──────────────────────────────────────────────────
#
# Span events are fine-grained lifecycle markers emitted during sub-operations
# (e.g. outcome evaluation, lock renewal) that are not captured by per-turn
# TurnMetrics.  They complement the SLI/SLO layer with causal tracing.
#
# Defined span types:
#   outcome_evaluation_start    — Grader begins evaluating an agent's output
#   outcome_evaluation_ongoing  — per-criterion score recorded
#   outcome_evaluation_end      — Grader finishes; final score/status available
#   lock_renewal_failure        — LockRenewer failed to extend a distributed lease
#   lane_started                — a parallel Lane began execution
#   lane_completed              — a parallel Lane finished successfully
#   lane_failed                 — a parallel Lane failed
#   lane_timeout                — a parallel Lane timed out
#   thread_created              — a Coordinator AgentThread was created
#   thread_message_sent         — a message was dispatched to an AgentThread
#   thread_message_received     — an AgentThread produced a response
#
# Multi-agent optimization span types (Sprint 0 — see docs/多Agent优化实施方案-SDLC.md)
#   grader_retry_start          — P0: Generator-Verifier retry loop begins for an attempt
#   grader_retry_end            — P0: retry attempt finished (FAIL or PASS recorded)
#   grader_retry_exhausted      — P0: max_attempts hit; falling back to best attempt
#   bus_publish                 — P1: event published to A2ABus
#   bus_consume                 — P1: event consumed from A2ABus
#   bus_subscriber_error        — P1: subscriber callback raised (fail-closed swallowed)
#   worker_claim                — P2: worker claimed a task from persona queue
#   worker_release              — P2: worker released/completed a task
#   worker_heartbeat_fail       — P2: worker lock renewal failed → task reclaimable
#   worker_experience_write     — P2: task experience archived to coordinator_threads
#   worker_experience_read      — P2: prior experience injected into task prompt


class SpanType:
    """
    Canonical span_type string constants for TelemetryRecorder.record_span_event().

    Prefer these constants over string literals so that dashboard filters and
    downstream consumers have a single source of truth. Free-form span_type
    strings remain supported for backward compatibility with existing callers.
    """

    # ── P0 Generator-Verifier retry loop ────────────────────────────────────
    GRADER_RETRY_START:     str = "grader_retry_start"
    GRADER_RETRY_END:       str = "grader_retry_end"
    GRADER_RETRY_EXHAUSTED: str = "grader_retry_exhausted"

    # ── P1 A2A Bus production path ──────────────────────────────────────────
    BUS_PUBLISH:          str = "bus_publish"
    BUS_CONSUME:          str = "bus_consume"
    BUS_SUBSCRIBER_ERROR: str = "bus_subscriber_error"

    # ── P2 Persistent worker pool ───────────────────────────────────────────
    WORKER_CLAIM:              str = "worker_claim"
    WORKER_RELEASE:            str = "worker_release"
    WORKER_HEARTBEAT_FAIL:     str = "worker_heartbeat_fail"
    WORKER_EXPERIENCE_WRITE:   str = "worker_experience_write"
    WORKER_EXPERIENCE_READ:    str = "worker_experience_read"

    # ── Coder Agent 长程自主化 (docs/Coder-Agent长程自主化技术方案.md §8) ─────
    # B1 prompt cache
    PROMPT_CACHE_HIT:              str = "prompt_cache_hit"
    PROMPT_CACHE_MISS:             str = "prompt_cache_miss"
    # B2 read dedup
    READ_DEDUP_HIT:                str = "read_dedup_hit"
    READ_DEDUP_MODIFIED:           str = "read_dedup_modified"
    # B3 + D2 tiered compaction
    COMPACTION_SOFT_TRIGGERED:     str = "compaction_soft_triggered"
    COMPACTION_HARD_TRIGGERED:     str = "compaction_hard_triggered"
    # B4 live repo context
    LIVE_REPO_COLLECTED:           str = "live_repo_collected"
    # B5 auto working memory
    MEMORY_DISTILLED:              str = "memory_distilled"
    MEMORY_COMPACTED:              str = "memory_compacted"
    # C1 mid-flight replan
    MIDFLIGHT_REPLAN_START:        str = "midflight_replan_start"
    MIDFLIGHT_REPLAN_END:          str = "midflight_replan_end"
    MIDFLIGHT_REPLAN_EXHAUSTED:    str = "midflight_replan_exhausted"
    # C2 DAG expansion
    DAG_EXPANSION_REQUESTED:       str = "dag_expansion_requested"
    DAG_EXPANSION_ACCEPTED:        str = "dag_expansion_accepted"
    DAG_EXPANSION_REJECTED:        str = "dag_expansion_rejected"
    # C3 checkpoint
    CHECKPOINT_WRITTEN:            str = "checkpoint_written"
    CHECKPOINT_RESTORED:           str = "checkpoint_restored"
    CHECKPOINT_RESTORE_REJECTED:   str = "checkpoint_restore_rejected"
    # C4 mandatory Grader
    GRADER_DECISION_PASS:          str = "grader_decision_pass"
    GRADER_DECISION_FAIL:          str = "grader_decision_fail"
    GRADER_DECISION_ESCALATE:      str = "grader_decision_escalate"
    # D1 steering queue
    STEERING_INJECTED:             str = "steering_injected"
    # D3 worktree isolation
    WORKTREE_CREATED:              str = "worktree_created"
    WORKTREE_MERGED:               str = "worktree_merged"
    WORKTREE_CONFLICT:             str = "worktree_conflict"

    # OS Sandbox
    SANDBOX_EXEC:                  str = "sandbox_exec"
    SANDBOX_FALLBACK_TO_NOOP:      str = "sandbox_fallback_to_noop"
    SANDBOX_VIOLATION:             str = "sandbox_violation"
    SANDBOX_TIMEOUT:               str = "sandbox_timeout"
    SANDBOX_OOM_KILLED:            str = "sandbox_oom_killed"

    # ── Sprint 10 PR-7 — Subagent 4-barrier observability ───────────────────
    # ai-buddy's TypedSubAgent enforces a 4-barrier isolation: role-based
    # whitelist (Barrier 1), per-tool permission (Barrier 2 — covered by
    # F7), concurrency cap (Barrier 3), depth cap (Barrier 4 +
    # BLOCKED_TOOLS removal).  These spans surface every barrier hit so
    # operators can chart "why isn't my subagent using web_fetch" or
    # "how often does depth-limit fire".
    SUBAGENT_SPAWNED:                    str = "subagent_spawned"
    SUBAGENT_DENIED_BY_ROLE_WHITELIST:   str = "subagent_denied_by_role_whitelist"
    SUBAGENT_DENIED_BY_BLOCKED_TOOL:     str = "subagent_denied_by_blocked_tool"
    SUBAGENT_DENIED_BY_DEPTH_LIMIT:      str = "subagent_denied_by_depth_limit"
    SUBAGENT_TASK_COMPLETED:             str = "subagent_task_completed"

    # ── Coder Agent root-cause fix plan (docs/CoderAgent-多文件任务完成率根因修复方案.md) ──
    # F2 — repeated-validation 3-state remediation ladder
    F2_HINT_INJECTED:              str = "f2_hint_injected"
    F2_TOOLS_RESTRICTED:           str = "f2_tools_restricted"
    F2_ABORTED:                    str = "f2_aborted"
    # F7 — PermissionEnforcer denial
    F7_DENIED:                     str = "f7_denied"
    # F8 — Bash sub-validator outcomes
    F8_BLOCKED:                    str = "f8_blocked"
    F8_WARN:                       str = "f8_warn"

    # ── Sprint 11 PR-A4 — Acceptance command failure observability ──────────
    # Surface every acceptance-failure mode as a structured span so
    # operators can chart per-LLM failure-cause distribution and
    # decide where to invest prompt tuning.  Always-on (no toggle):
    # observability is a free deliverable when the failure already
    # happened, and the metadata never includes raw command bytes
    # (only structural facts: cause, segment_index, llm_model).
    ACCEPTANCE_CMD_PARSE_FAILED:   str = "acceptance_cmd_parse_failed"
    ACCEPTANCE_CMD_DENIED:         str = "acceptance_cmd_denied"
    ACCEPTANCE_CMD_NONZERO_EXIT:   str = "acceptance_cmd_nonzero_exit"
    ACCEPTANCE_CMD_TIMEOUT:        str = "acceptance_cmd_timeout"

    # ── Option-3 Sprint PR 4 — DAG checkpoint stateful resume ───────────────
    # Surface every step of the HITL pause → resume → token-consume cycle
    # so dashboards can answer:
    #   * "How often does scope=once actually break the loop?"
    #     (count DAG_CHECKPOINT_CONSUMED_ONCE_TOKEN)
    #   * "How many resumes fall back to legacy re-plan?"
    #     (DAG_CHECKPOINT_RESTORED vs lookups that returned None)
    #   * "Are stale tokens accumulating?"
    #     (DAG_CHECKPOINT_CLEARED rate vs SAVED rate)
    # Always-on (no toggle): observability is free at the call sites that
    # already log INFO; metadata never includes tool args / outputs.
    DAG_CHECKPOINT_SAVED:               str = "dag_checkpoint_saved"
    DAG_CHECKPOINT_RESTORED:            str = "dag_checkpoint_restored"
    DAG_CHECKPOINT_CONSUMED_ONCE_TOKEN: str = "dag_checkpoint_consumed_once_token"
    DAG_CHECKPOINT_CLEARED:             str = "dag_checkpoint_cleared"


@dataclass
class SpanEvent:
    """
    A lightweight lifecycle span event (§10.2 + Phase 3 P2).

    span_type   : identifies the operation (e.g. "outcome_evaluation_start")
    session_id  : owning session
    agent_id    : agent involved (empty string if not applicable)
    ts          : unix timestamp (set automatically if not provided)
    metadata    : arbitrary key-value context for this event
    """
    span_type:  str
    session_id: str = ""
    agent_id:   str = ""
    ts:         float = field(default_factory=time.time)
    metadata:   Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "span_type":  self.span_type,
            "session_id": self.session_id,
            "agent_id":   self.agent_id,
            "ts":         self.ts,
            "metadata":   self.metadata,
        }


# ── Module-level default instance ────────────────────────────────────────────────
# A shared recorder for use across the runtime without explicit DI.
# Replace with a configured instance via dependency injection in production.

_default_recorder: Optional[TelemetryRecorder] = None
_recorder_lock = threading.Lock()


def get_recorder() -> TelemetryRecorder:
    """Return the process-wide default TelemetryRecorder (lazy init)."""
    global _default_recorder
    if _default_recorder is None:
        with _recorder_lock:
            if _default_recorder is None:
                _default_recorder = TelemetryRecorder()
    return _default_recorder
