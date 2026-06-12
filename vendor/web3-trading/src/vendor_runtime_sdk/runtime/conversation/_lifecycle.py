# -*- coding: utf-8 -*-
"""
LifecycleMixin — init, registry, unregister, snapshot persistence

Auto-extracted from runtime/conversation.py during refactoring.
Part of the ConversationRuntime mixin chain.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, AsyncGenerator, List, Optional

from vendor_runtime_sdk.runtime.activity import ActivityTracker
from vendor_runtime_sdk.runtime.budget.pressure import BudgetPressure, inject_into_last_tool_result
from vendor_runtime_sdk.runtime.budget.warning import strip_budget_warnings
from vendor_runtime_sdk.runtime.config.toggles import ModuleToggles
from vendor_runtime_sdk.runtime.fallback.manager import (
    FallbackManager,
)
from vendor_runtime_sdk.runtime.hooks.base import HookContext, HookDispatcher
from vendor_runtime_sdk.runtime.session.fsm import IllegalTransitionError, SessionFSM, SessionState
from vendor_runtime_sdk.runtime.tools.dedup import deduplicate_tool_calls
from vendor_runtime_sdk.runtime.tools.repair import repair_tool_calls


from vendor_runtime_sdk.runtime.conversation._helpers import (
    _RUNTIME_REGISTRY, _LAST_RUNTIME, _BACKGROUND_TASKS,
    TurnResult, STALE_STREAM_TIMEOUT,
)

logger = logging.getLogger(__name__)

class LifecycleMixin:
    """
    Reliability-first ReAct runtime.

    Wraps the existing AgentLoop with turn-scoped lifecycle management:
    preflight checks, fallback, budget pressure, tool guardrails, and
    activity tracking.

    Parameters
    ----------
    agent_loop
        An AgentLoop instance (from agent/tools/loop.py).  The runtime
        delegates the actual ReAct iteration to this loop.
    session_id : str
        Identifies the current session (used in logs and SSE events).
    workspace_id : str
        Workspace isolation boundary.
    max_iterations : int
        Maximum ReAct iterations per turn.
    fallback_manager : FallbackManager | None
        Turn-scoped model fallback.  If None, no fallback is applied.
    toggles : ModuleToggles | None
        Per-module feature flags.  Defaults to all-enabled.
    hooks : list | None
        PluginHook instances to fire around LLM calls.
    stale_stream_timeout : float
        Seconds of inactivity before stale-stream reconnect is attempted.
    """

    def __init__(
        self,
        agent_loop=None,
        session_id: str = "",
        workspace_id: str = "",
        max_iterations: int = 10,
        hard_max_iterations: Optional[int] = None,
        fallback_manager: Optional[FallbackManager] = None,
        toggles: Optional[ModuleToggles] = None,
        hooks: Optional[list] = None,
        stale_stream_timeout: float = STALE_STREAM_TIMEOUT,
        compactor=None,
        memory_provider=None,
        vault=None,
        custom_tool_handler=None,
        checkpoint_base_dir: str = "data/checkpoints",
        trajectory_base_dir: str = "data/trajectories",
        avatar_id: Optional[str] = None,
        issue_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        user_id: Optional[str] = None,
        storage: Optional[Any] = None,
        prefer_storage_for_hitl: bool = False,
        prompter: Optional[Any] = None,
    ):
        # Sprint 0 PR-B (docs/TUI-Web-Runtime同构化技术方案.md §B1):
        # accept ``storage: StorageBackend | None`` passively. Sprint 1
        # PR-E flips the mixin code from direct DAO/Redis imports to
        # ``self._storage.*`` consumption. Until then this attribute is
        # held on self for downstream inspection (telemetry, tests) but
        # is NOT read by any code path — keeps PR-B a pure passthrough
        # with zero behaviour change.
        #
        # ``Any`` typing rather than ``StorageBackend | None`` avoids
        # circular import at the lifecycle layer. The real type is
        # ``runtime.storage.StorageBackend``; callers should pass an
        # instance produced by ``get_storage_backend(...)``.
        self._storage = storage
        # Sprint 2 PR-O2: CLI / TUI callers set this True (via
        # ``for_local_context`` factory) so ``_should_use_storage_for_hitl``
        # routes through ``storage.hitl_gates`` instead of attempting
        # the inline Mongo fallback (which would crash in non-Mongo
        # processes). Web stays False to honour the toggle-gated
        # gradual rollout — the toggle is the source of truth there.
        self._prefer_storage_for_hitl = prefer_storage_for_hitl
        # Sprint 2 PR-O4: passive prompter injection — matches the
        # ``LocalRuntime.chat_turn(prompter=...)`` PR-J pattern. Sprint
        # 3+ PR-O5 wires the actual ``prompter.prompt(req)`` call inside
        # the HITL exception handler. Until then this attribute is
        # held for downstream inspection but not consumed by any
        # active code path — keeps PR-O4 a pure-passthrough with zero
        # behaviour change.
        #
        # Web callers continue to leave this ``None`` — they handle
        # HITL via the off-process ``POST /hitl/decide`` resume cycle,
        # not via a prompter. CLI / TUI callers pass a
        # ``TerminalPrompter`` wrapping the broker (via PR-K wiring).
        #
        # ``Any`` typing rather than ``PermissionPrompter | None``
        # avoids a circular import at the lifecycle layer. The real
        # type is ``runtime.protocols.permission_prompter.PermissionPrompter``.
        self._prompter = prompter
        self._loop = agent_loop
        self._session_id = session_id
        self._workspace_id = workspace_id
        self._max_iterations = max_iterations
        # Gap 5 — cost attribution fields flowing through HookContext.metadata.
        # Optional; CostTrackingHook degrades to NULL avatar/issue when absent.
        self._avatar_id = avatar_id
        self._issue_id = issue_id
        self._agent_id = agent_id
        self._user_id = user_id
        # T3-2: Absolute hard cap beyond which the runtime emits
        # stop_reason=budget_exceeded. When None, the soft auto-expand
        # behavior below is unbounded (preserves prior production behavior).
        self._hard_max_iterations = hard_max_iterations
        self._fallback = fallback_manager
        # Snapshot primary LLM so restore_primary() can revert the loop
        self._primary_llm_snapshot = (agent_loop.llm, agent_loop.model_name) if (fallback_manager and agent_loop) else None
        self._toggles = toggles or ModuleToggles()
        self._dispatcher = HookDispatcher(hooks or [])
        self._stale_timeout = stale_stream_timeout
        self._compactor = compactor  # Optional[Compactor] — for preflight compression
        # Observer hook — Compactor may fire compaction from inside the
        # agent loop (via ContextAssembler), after our preflight check.
        # Install a success callback so we can surface a session.compression
        # SSE event even when the runtime does not own the trigger.
        if self._compactor is not None:
            try:
                self._compactor._on_compact_success = self._handle_compactor_success
                self._compactor._on_memory_flush = self._handle_memory_flush
            except Exception as _cb_exc:
                logger.debug(
                    "ConversationRuntime: failed to install compactor callback: %s",
                    _cb_exc,
                )

        # Phase 5 batch 3: session lifecycle modules
        self._memory_provider = memory_provider   # Optional[MemoryProvider]
        self._vault = vault                       # Optional[Vault]
        self._custom_tool_handler = custom_tool_handler  # Optional[CustomToolHandler]

        # Sub-components
        self._fsm = SessionFSM()
        self._activity = ActivityTracker(session_id=session_id)
        self._budget_pressure = BudgetPressure(max_iterations=max_iterations)
        # T3-2: grace slot for one synthesis event past the hard cap.
        # When iteration == hard_max_iterations we inject a forced
        # "conclude now" directive via the T3-1 bridge; the agent is
        # allowed exactly one ANSWER_RESPONSE / REPORT event past the
        # cap to emit its final synthesis. After that, any further
        # semantic event trips budget_exceeded.
        self._synthesis_grace_used: bool = False
        self._conclude_directive_injected: bool = False

        # P5: Token quota manager (3-level: User → Workspace → Session)
        self._token_quota = None
        if self._toggles.is_enabled("token_quota"):
            try:
                from vendor_runtime_sdk.runtime.budget.token_quota import get_token_quota_manager
                self._token_quota = get_token_quota_manager()
            except Exception as exc:
                logger.warning("ConversationRuntime: TokenQuotaManager init failed (disabled): %s", exc)

        # Self-evolution engine counters (§8.2-8.5)
        self._nudge_count = 0         # total nudge triggers
        self._review_count = 0        # completed background reviews
        self._turns_since_nudge = 0   # turns since last nudge
        _NUDGE_INTERVAL = 10          # trigger every N turns

        # Phase 5 batch 1: post-turn observability modules
        self._checkpoint = None
        if self._toggles.is_enabled("checkpoint_manager"):
            try:
                from vendor_runtime_sdk.runtime.checkpoint.manager import CheckpointManager
                self._checkpoint = CheckpointManager(base_dir=checkpoint_base_dir)
            except Exception as exc:
                logger.warning("ConversationRuntime: CheckpointManager init failed (disabled): %s", exc)
        self._trajectory = None
        if self._toggles.is_enabled("trajectory_recorder"):
            try:
                from vendor_runtime_sdk.runtime.checkpoint.trajectory import TrajectoryRecorder
                self._trajectory = TrajectoryRecorder(base_dir=trajectory_base_dir)
            except Exception as exc:
                logger.warning("ConversationRuntime: TrajectoryRecorder init failed (disabled): %s", exc)

        # Phase 4 P0 + 6.3: agent reference (set by chat.py after construction)
        # for Environment snapshot + activity distillation access to agent memory stores.
        self._agent_ref = None

        # Interrupt signal — set by external cancel requests
        self._interrupt_requested: bool = False
        self._interrupt_reason: str = ""

        # HITL Redesign — operator-initiated Cancel run from the chat
        # UI. ``True`` causes ``wrap_agent_stream`` to bail at the next
        # event boundary and mark FSM TERMINATED. Distinct from
        # ``_interrupt_requested`` (which is reserved for upstream
        # orchestration cancels) so a single global cancel button doesn't
        # accidentally terminate spawned subagents/HITL flows.
        self._cancel_requested: bool = False

        # Live telemetry counters (exposed via runtime snapshot endpoint)
        self._current_iteration: int = 0
        self._input_tokens_last: int = 0
        self._output_tokens_last: int = 0
        self._tokens_total: int = 0
        self._authoritative_usage_received: bool = False
        self._fallback_count: int = 0
        self._last_fallback_reason: str = ""
        self._fsm_transitions: list[tuple[float, str, str]] = []  # (ts, from, to)
        self._compaction_triggered: int = 0
        self._mem_flush_count: int = 0

        # §5.6 pending SSE event for compaction — filled when preflight
        # compaction runs, drained (yielded + cleared) by both run_turn and
        # wrap_agent_stream so the client can render a "整理对话记忆…" notice.
        self._pending_compaction_event: Optional[str] = None

        # Register this runtime globally for snapshot lookups
        if session_id:
            _RUNTIME_REGISTRY[session_id] = self

        # Register with WorkspaceManager for workspace-scoped queries
        if session_id and workspace_id:
            try:
                from vendor_runtime_sdk.runtime.workspace import get_workspace_manager
                get_workspace_manager().register_session(workspace_id, session_id)
            except Exception:
                pass  # fail-soft: workspace tracking is non-critical

    # ── Registry lookup ──────────────────────────────────────────────────
    @classmethod
    def get_active(cls, session_id: str) -> Optional["ConversationRuntime"]:
        """Return the in-flight ConversationRuntime for *session_id*, if any."""
        return _RUNTIME_REGISTRY.get(session_id)

    @classmethod
    def list_active_sessions(cls) -> list[str]:
        """Return all session_ids currently registered."""
        return list(_RUNTIME_REGISTRY.keys())

    def _unregister(self) -> None:
        """Remove self from the global registry (on turn end)."""
        global _LAST_RUNTIME
        if self._session_id and _RUNTIME_REGISTRY.get(self._session_id) is self:
            _RUNTIME_REGISTRY.pop(self._session_id, None)
            _LAST_RUNTIME = self  # keep ref for post-session nudge

        # Unregister from WorkspaceManager
        if self._session_id:
            try:
                from vendor_runtime_sdk.runtime.workspace import get_workspace_manager
                get_workspace_manager().unregister_session(self._session_id)
            except Exception:
                pass  # fail-soft

        # §3.1 of 服务端数据本地化整改技术方案 — drop the Redis snapshot
        # when the session is truly done so cross-pod lookups don't return
        # stale data. Fail-soft: registry store errors must not poison the
        # unregister path.
        if self._session_id and self._toggles.is_enabled("registry_redis"):
            try:
                from vendor_runtime_sdk.runtime.cache.registry_store import get_registry_store
                task = asyncio.create_task(
                    get_registry_store().delete_snapshot(
                        session_id=self._session_id,
                        workspace_id=self._workspace_id,
                    ),
                    name=f"registry_delete:{self._session_id}",
                )
                # Hold a strong reference so the task is not GC'd before it
                # runs (see _BACKGROUND_TASKS docstring); auto-discard on done.
                _BACKGROUND_TASKS.add(task)
                task.add_done_callback(_BACKGROUND_TASKS.discard)
            except RuntimeError:
                # No running event loop (rare — _unregister is normally in
                # async context). Drop silently; the TTL will clean up.
                pass
            except Exception:
                pass

    async def _persist_snapshot_if_enabled(self) -> None:
        """Push the current snapshot to the pluggable RegistryStore.

        §3.1 of ``docs/服务端数据本地化整改技术方案.md``: when
        ``registry_redis`` is on, multi-pod deployments need the dashboard
        ``/runtime/snapshot`` endpoint to succeed regardless of which pod
        serves the read. We snapshot **after** each turn's post-processing
        so the frontend sees the final counters — fail-soft so persistence
        hiccups never affect the user-visible turn.
        """
        if not self._session_id or not self._workspace_id:
            return
        if not self._toggles.is_enabled("registry_redis"):
            return
        try:
            snap = self.snapshot()
        except Exception as exc:
            logger.debug(
                "ConversationRuntime[%s]: snapshot() failed — skipping persist: %s",
                self._session_id,
                exc,
            )
            return
        try:
            from vendor_runtime_sdk.runtime.cache.registry_store import get_registry_store
            await get_registry_store().put_snapshot(
                session_id=self._session_id,
                workspace_id=self._workspace_id,
                snapshot=snap,
            )
        except Exception as exc:
            logger.debug(
                "ConversationRuntime[%s]: registry_store.put_snapshot failed: %s",
                self._session_id,
                exc,
            )

    @classmethod
    def get_last(cls) -> Optional["ConversationRuntime"]:
        """Return the most recently completed runtime (even after unregister)."""
        return _LAST_RUNTIME
