# -*- coding: utf-8 -*-
"""
Agent Runtime Prometheus Metrics — §15.3 (Phase 4 P2)

Domain-specific metrics for the AI Agent runtime, complementing the
generic HTTP metrics in prometheus.py.

12 metrics covering:
  - Cache hit/miss rates (Redis → MongoDB fallback)
  - Lane operations (started/completed/failed/timeout) + duration
  - Policy decisions (allow/deny/ask/degrade/alert)
  - Turn duration (per model, fallback flag)
  - Tool/LLM call counts (per tool/model, success flag)
  - Recovery attempts (per recipe, success flag)
  - SLO error budget ratio (per SLO name)
  - Compaction savings ratio
  - Hook latency (per hook type)

All metrics use the `agent_` prefix for namespace isolation.
Labels follow Prometheus naming conventions (snake_case, low cardinality).
"""

from __future__ import annotations

try:
    from prometheus_client import Counter, Gauge, Histogram
    _HAS_PROMETHEUS = True
except ImportError:
    _HAS_PROMETHEUS = False


# ── Cache metrics ────────────────────────────────────────────────────────────

if _HAS_PROMETHEUS:
    CACHE_HITS = Counter(
        "agent_cache_hits_total",
        "Total cache hits",
        ["cache_type", "key_pattern"],
    )

    CACHE_MISSES = Counter(
        "agent_cache_misses_total",
        "Total cache misses (fallback to MongoDB)",
        ["cache_type", "key_pattern"],
    )

    # ── Lane metrics ─────────────────────────────────────────────────────────

    LANE_OPERATIONS = Counter(
        "agent_lane_operations_total",
        "Lane lifecycle events",
        ["operation"],  # started, completed, failed, timeout
    )

    LANE_DURATION = Histogram(
        "agent_lane_duration_seconds",
        "Lane execution duration in seconds",
        ["lane_label"],
        buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
    )

    # ── Policy metrics ───────────────────────────────────────────────────────

    POLICY_DECISIONS = Counter(
        "agent_policy_decisions_total",
        "Policy engine decision outcomes",
        ["action", "rule_id"],  # action: allow, deny, ask, degrade, alert
    )

    # ── Turn metrics ─────────────────────────────────────────────────────────

    TURN_DURATION = Histogram(
        "agent_turn_duration_seconds",
        "Agent turn end-to-end duration in seconds",
        ["model", "is_fallback"],
        buckets=(0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 15.0, 30.0),
    )

    # ── Tool / LLM call metrics ──────────────────────────────────────────────

    TOOL_CALLS = Counter(
        "agent_tool_calls_total",
        "Total tool invocations",
        ["tool_name", "success"],
    )

    LLM_CALLS = Counter(
        "agent_llm_calls_total",
        "Total LLM API calls",
        ["model", "provider", "success"],
    )

    # ── Recovery metrics ─────────────────────────────────────────────────────

    RECOVERY_ATTEMPTS = Counter(
        "agent_recovery_attempts_total",
        "Recovery engine attempts",
        ["recipe_id", "success"],
    )

    # ── SLO error budget ─────────────────────────────────────────────────────

    SLO_ERROR_BUDGET = Gauge(
        "agent_slo_error_budget_ratio",
        "Remaining SLO error budget (0.0 = exhausted, 1.0 = full)",
        ["slo_name"],
    )

    # ── Compaction metrics ───────────────────────────────────────────────────

    COMPACTION_SAVINGS = Histogram(
        "agent_compaction_savings_ratio",
        "Token compaction savings ratio (0.0–1.0)",
        [],
        buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
    )

    # ── Hook latency ─────────────────────────────────────────────────────────

    HOOK_LATENCY = Histogram(
        "agent_hook_latency_seconds",
        "Hook dispatch latency in seconds",
        ["hook_type"],  # pre_llm, post_llm, post_tool
        buckets=(0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1),
    )


# ── Helper functions for recording metrics ───────────────────────────────────


def record_cache_hit(cache_type: str = "redis", key_pattern: str = "default") -> None:
    """Record a cache hit."""
    if _HAS_PROMETHEUS:
        CACHE_HITS.labels(cache_type=cache_type, key_pattern=key_pattern).inc()


def record_cache_miss(cache_type: str = "redis", key_pattern: str = "default") -> None:
    """Record a cache miss."""
    if _HAS_PROMETHEUS:
        CACHE_MISSES.labels(cache_type=cache_type, key_pattern=key_pattern).inc()


def record_lane_operation(operation: str) -> None:
    """Record a lane lifecycle event (started/completed/failed/timeout)."""
    if _HAS_PROMETHEUS:
        LANE_OPERATIONS.labels(operation=operation).inc()


def record_lane_duration(lane_label: str, duration_s: float) -> None:
    """Record lane execution duration."""
    if _HAS_PROMETHEUS:
        LANE_DURATION.labels(lane_label=lane_label).observe(duration_s)


def record_policy_decision(action: str, rule_id: str = "default") -> None:
    """Record a policy engine decision."""
    if _HAS_PROMETHEUS:
        POLICY_DECISIONS.labels(action=action, rule_id=rule_id).inc()


def record_turn_duration(model: str, is_fallback: bool, duration_s: float) -> None:
    """Record agent turn duration."""
    if _HAS_PROMETHEUS:
        TURN_DURATION.labels(model=model, is_fallback=str(is_fallback).lower()).observe(duration_s)


def record_tool_call(tool_name: str, success: bool) -> None:
    """Record a tool invocation."""
    if _HAS_PROMETHEUS:
        TOOL_CALLS.labels(tool_name=tool_name, success=str(success).lower()).inc()


def record_llm_call(model: str, provider: str, success: bool) -> None:
    """Record an LLM API call."""
    if _HAS_PROMETHEUS:
        LLM_CALLS.labels(model=model, provider=provider, success=str(success).lower()).inc()


def record_recovery_attempt(recipe_id: str, success: bool) -> None:
    """Record a recovery engine attempt."""
    if _HAS_PROMETHEUS:
        RECOVERY_ATTEMPTS.labels(recipe_id=recipe_id, success=str(success).lower()).inc()


def set_slo_error_budget(slo_name: str, ratio: float) -> None:
    """Set the remaining error budget for an SLO (0.0–1.0)."""
    if _HAS_PROMETHEUS:
        SLO_ERROR_BUDGET.labels(slo_name=slo_name).set(ratio)


def record_compaction_savings(ratio: float) -> None:
    """Record a compaction savings ratio."""
    if _HAS_PROMETHEUS:
        COMPACTION_SAVINGS.observe(ratio)


def record_hook_latency(hook_type: str, duration_s: float) -> None:
    """Record hook dispatch latency."""
    if _HAS_PROMETHEUS:
        HOOK_LATENCY.labels(hook_type=hook_type).observe(duration_s)


# ── Token Billing Optimization metrics (P1/P4/P5) ───────────────────────────

if _HAS_PROMETHEUS:
    TOKEN_CACHE_HIT_RATIO = Gauge(
        "agent_token_cache_hit_ratio",
        "Prompt cache hit ratio (cache_read / total_prompt_tokens)",
        ["model"],
    )

    TOKEN_CACHE_READ_TOTAL = Counter(
        "agent_token_cache_read_total",
        "Total cache-read tokens (billed at 0.1× input price)",
        ["model"],
    )

    TOKEN_CACHE_CREATION_TOTAL = Counter(
        "agent_token_cache_creation_total",
        "Total cache-creation tokens",
        ["model"],
    )

    LLM_CALL_COST_CNY = Counter(
        "agent_llm_call_cost_cny",
        "Accumulated LLM call cost in CNY",
        ["model", "agent_type", "is_fallback"],
    )

    COMPACTION_SAVINGS_TOKENS = Counter(
        "agent_compaction_savings_tokens_total",
        "Total tokens saved by context compaction",
        [],
    )

    QUOTA_REJECTIONS = Counter(
        "agent_quota_rejections_total",
        "Total requests rejected due to token quota",
        ["scope"],  # user_daily, user_monthly, workspace_daily, session_total, session_turn
    )

    TOOL_COMPRESSION_SAVINGS = Counter(
        "agent_tool_compression_savings_tokens_total",
        "Total tokens saved by tool result compression",
        ["tool_name"],
    )

    TOOL_CACHE_HITS = Counter(
        "agent_tool_cache_hits_total",
        "Total tool result cache hits (avoided re-fetching)",
        ["tool_name"],
    )


def record_token_cache_hit_ratio(model: str, ratio: float) -> None:
    """Record prompt cache hit ratio for a model."""
    if _HAS_PROMETHEUS:
        TOKEN_CACHE_HIT_RATIO.labels(model=model).set(ratio)


def record_token_cache_read(model: str, tokens: int) -> None:
    """Record cache-read tokens (billed at 0.1×)."""
    if _HAS_PROMETHEUS:
        TOKEN_CACHE_READ_TOTAL.labels(model=model).inc(tokens)


def record_token_cache_creation(model: str, tokens: int) -> None:
    """Record cache-creation tokens."""
    if _HAS_PROMETHEUS:
        TOKEN_CACHE_CREATION_TOTAL.labels(model=model).inc(tokens)


def record_llm_call_cost(model: str, agent_type: str, is_fallback: bool, cost_cny: float) -> None:
    """Record LLM call cost in CNY."""
    if _HAS_PROMETHEUS:
        LLM_CALL_COST_CNY.labels(
            model=model, agent_type=agent_type, is_fallback=str(is_fallback).lower()
        ).inc(cost_cny)


def record_compaction_savings_tokens(tokens_saved: int) -> None:
    """Record tokens saved by context compaction."""
    if _HAS_PROMETHEUS:
        COMPACTION_SAVINGS_TOKENS.inc(tokens_saved)


def record_quota_rejection(scope: str) -> None:
    """Record a token quota rejection."""
    if _HAS_PROMETHEUS:
        QUOTA_REJECTIONS.labels(scope=scope).inc()


def record_tool_compression_savings(tool_name: str, tokens_saved: int) -> None:
    """Record tokens saved by tool result compression."""
    if _HAS_PROMETHEUS:
        TOOL_COMPRESSION_SAVINGS.labels(tool_name=tool_name).inc(tokens_saved)


def record_tool_cache_hit(tool_name: str) -> None:
    """Record a tool result cache hit."""
    if _HAS_PROMETHEUS:
        TOOL_CACHE_HITS.labels(tool_name=tool_name).inc()
