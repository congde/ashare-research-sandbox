# -*- coding: utf-8 -*-
"""
SnapshotMixin — runtime snapshot and env snapshot

Auto-extracted from runtime/conversation.py during refactoring.
Part of the ConversationRuntime mixin chain.
"""

from __future__ import annotations
from vendor_runtime_sdk.runtime.budget.pressure import BudgetPressure, inject_into_last_tool_result

class SnapshotMixin:
    """SnapshotMixin — runtime snapshot and env snapshot"""

    @property
    def _env_snapshot(self):
        """Lazy accessor for Environment snapshot via agent reference.

        Returns None if the environment toggle is disabled, no agent is
        attached yet, or the agent has no snapshot.
        """
        if self._agent_ref is None:
            return None
        if not self._toggles.is_enabled("environment"):
            return None
        return getattr(self._agent_ref, "_environment_snapshot", None)

    # ── Snapshot for external inspection ────────────────────────────────
    def snapshot(self) -> dict:
        """
        Return a JSON-serialisable snapshot of the runtime's live state.

        Used by the dashboard UI via /api/v1/runtime/snapshot?session_id=X
        to drive the Budget/Token/Fallback/FSM panels in real time.
        """
        activity = self._activity.get_summary()

        # Budget pressure tier — computed directly from iteration / max_iterations
        # so the UI reflects the real-time ratio regardless of the
        # BudgetPressure class's per-level monotone injection state.
        # Thresholds match the warning levels in src/runtime/budget/pressure.py
        # (50% / 70% / 90% / 95%) mapped to 4 distinct UI colors.
        _ratio = (self._current_iteration / self._max_iterations) if self._max_iterations > 0 else 0.0
        if _ratio >= 0.95:
            budget_tier = "RED"       # critical — respond immediately
        elif _ratio >= 0.90:
            budget_tier = "RED"       # high — urgent, 1-2 steps
        elif _ratio >= 0.70:
            budget_tier = "ORANGE"    # medium — converge now
        elif _ratio >= 0.50:
            budget_tier = "YELLOW"    # low — half consumed
        else:
            budget_tier = "NORMAL"    # < 50%

        # Fallback state
        fallback_active = False
        fallback_model = ""
        fallback_attempt = 0
        fallback_chain: list[str] = []
        if self._fallback is not None:
            try:
                fallback_active = bool(getattr(self._fallback, "is_fallback_active", False))
                fallback_attempt = int(getattr(self._fallback, "fallback_attempt", 0))
                cur = getattr(self._fallback, "current", None)
                if cur is not None:
                    fallback_model = getattr(cur, "model", "") or getattr(cur, "model_name", "")
                # Chain, if exposed
                chain_attr = getattr(self._fallback, "_chain", None) or getattr(self._fallback, "chain", None)
                if chain_attr:
                    for item in chain_attr:
                        fallback_chain.append(getattr(item, "model", "") or getattr(item, "model_name", "") or str(item))
            except Exception:
                pass

        # FSM transitions — return the last 20
        transitions_out = [
            {"ts": ts, "from": _from, "to": _to}
            for ts, _from, _to in self._fsm_transitions[-20:]
        ]

        return {
            "session_id": self._session_id,
            "workspace_id": self._workspace_id,
            "fsm_state": self._fsm.state.value if hasattr(self._fsm.state, "value") else str(self._fsm.state),
            "fsm_is_terminal": self._fsm.is_terminal,
            "fsm_transitions": transitions_out,
            "budget": {
                "pressure": budget_tier,
                "iteration": self._current_iteration,
                "max_iterations": self._max_iterations,
                "iteration_ratio": (
                    self._current_iteration / self._max_iterations
                    if self._max_iterations > 0 else 0.0
                ),
                "compaction_triggered": self._compaction_triggered,
                "mem_flush_count": self._mem_flush_count,
                "hook_latency_ms": getattr(self._dispatcher, "last_hook_latency_ms", 0.0),
            },
            "tokens": {
                "input_last": self._input_tokens_last,
                "output_last": self._output_tokens_last,
                "total": self._tokens_total,
            },
            "fallback": {
                "active": fallback_active,
                "model": fallback_model,
                "attempt": fallback_attempt,
                "count": self._fallback_count,
                "last_reason": self._last_fallback_reason,
                "chain": fallback_chain,
            },
            "activity": {
                "last_desc": activity.last_activity_desc,
                "seconds_since": round(activity.seconds_since_activity, 2),
                "current_tool": activity.current_tool,
                "api_calls": activity.api_call_count,
                "tool_calls": activity.tool_call_count,
                # is_stale: true when no event has advanced the activity
                # heartbeat within _stale_timeout seconds. Surfaces the
                # existing idle-stream detector (separate from the env
                # wall-clock timeout) so the dashboard can show "this
                # session hasn't made progress for X seconds".
                "is_stale": self._activity.is_stale(self._stale_timeout),
                "stale_timeout_seconds": self._stale_timeout,
            },
            "interrupt": {
                "requested": self._interrupt_requested,
                "reason": self._interrupt_reason,
            },
            "evolution": {
                "nudge_count": self._nudge_count,
                "review_count": self._review_count,
                "turns_since_nudge": self._turns_since_nudge,
            },
            "observability": {
                "checkpoint_count": getattr(self, "_checkpoint_count", 0),
                "trajectory_success": getattr(self, "_trajectory_success", 0),
                "trajectory_failed": getattr(self, "_trajectory_failed", 0),
            },
            "environment": {
                "active": self._env_snapshot is not None,
                "name": self._env_snapshot.config.name if self._env_snapshot else "",
                "base_image": self._env_snapshot.config.base_image if self._env_snapshot else "",
                "timeout_seconds": self._env_snapshot.config.resources.timeout_seconds if self._env_snapshot else 0,
                "network_policy": self._env_snapshot.config.network.policy if self._env_snapshot else "",
            },
            "modules": {
                "memory_provider": self._memory_provider is not None,
                "vault": self._vault is not None,
                "custom_tool": self._custom_tool_handler is not None,
                "token_quota": self._token_quota is not None,
            },
            "quota": (
                self._token_quota.get_session_usage(self._session_id)
                if self._token_quota
                else {"total": 0, "turn": 0}
            ),
        }

