"""
Module Toggles — per-module enable/disable switches (§3.4)

Each runtime module can be independently toggled:
  runtime.modules.<module>.enabled = true | false

Supports emergency override via env var:
  RUNTIME__MODULES__<MODULE>__ENABLED=true|false  (double underscore = nesting)

This allows production teams to:
  1. Incrementally roll out Phase 1 features behind toggles
  2. Emergency-disable a misbehaving module without code deploy
  3. Test modules in isolation during development

Phase 1 modules:
  fallback_restore    — turn-scoped fallback restore (§5.7)
  budget_pressure     — 4-tier budget pressure injection (§5.8)
  budget_stripping    — stale warning stripping at turn start (§5.1)
  tool_dedup          — duplicate tool call removal (§5.1)
  tool_repair         — fuzzy tool name repair (§5.1)
  activity_tracking   — activity tracker (§5.11)
  plugin_hooks        — pre/post LLM call hooks (§5.13)
  session_fsm         — session state machine enforcement (§5.4)
  preflight_compress  — pre-turn compression check (§5.6)

Phase 2 modules:
  tool_hook_middleware — pre/post/failure hooks wrapping tool execution (§6.7)
  policy_engine        — rule-based permission policy evaluation (§6.8)
  permission_resolver  — 3-level permission cascade (§6.6)
  memory_store         — MemoryStore versioned persistence (§7.3)
  memory_provider      — MemoryProvider lifecycle hooks (§7.2)
  skill_registry_db    — SkillRegistry MongoDB dual-source loading (§8.8)

Phase 2 P1 modules:
  telemetry_recorder   — TelemetryRecorder SLI/SLO tracking (§11.5)
  skill_api            — Skill REST API versioning endpoints (§8.7)
  schedule_persistence — Schedule RFC-5 Phase 2: MongoDB backend for schedule_jobs
  checkpoint_manager   — CheckpointManager local filesystem session snapshots
  trajectory_recorder  — TrajectoryRecorder ShareGPT-compatible JSONL turn log

Phase 3 modules (P0):
  typed_subagent       — TypedSubAgent 4-barrier isolation + SubAgentSpawner (§9.1)
  coordinator          — CoordinatorAgent + AgentThread persistence (§9.3)

Phase 3 modules (P1):
  lane_eventbus        — Lane parallel model + EventBus ordered merge (§9.4)
  task_packet          — TaskPacket + ValidatedPacket + DAGPlan (§9.5)
  outcome_grader       — Outcome/Rubric + Grader LLM evaluation (§10.2)
  agent_versioning     — AgentVersionManager immutable snapshots + archive (§10.1)
  schedule_celery      — Celery Beat + RabbitMQ production scheduler (§9.6.2)

Phase 3 modules (P2):
  span_events          — SpanEvent lifecycle markers in TelemetryRecorder (§10.2 P2)

Phase 4 modules (P0):
  environment          — Declarative Environment model + snapshot + API (§12.1, §14.9)
  vault                — Vault per-user credential management (§12.2)

Phase 4 modules (P1):
  custom_tool          — Custom Tool Protocol client pass-through (§6.5)

Phase 4 modules (P2):
  mock_service         — Mock Service composable test providers (§15.1)
  dashboard            — Dashboard Prometheus metrics + JSON API (§15.3)
  benchmark_runner     — Performance Benchmarks regression detection (§15.2)

Phase 8.2 modules:
  eval_pipeline        — batch offline evaluation; CI regression block at >5% quality drop

Phase 8.4 modules (all default False — enable per-environment for gradual rollout):
  a2a_transport    — Phase A: pluggable BusBackend (local | redis_streams)
  a2a_registry     — Phase B: AgentRegistry + heartbeat (Redis HSET)
  a2a_worker       — Phase B: AgentWorker consumer process
  a2a_rpc          — Phase C: AgentRPCClient location-transparent dispatch
  a2a_remote_spawn — Phase D: SubAgentSpawner → RPC routing (live traffic switch)

Multi-agent optimization modules (default False — Sprint 0 of docs/多Agent优化实施方案-SDLC.md):
  grader_retry_loop         — P0: Generator-Verifier feedback-retry loop around Grader
  a2a_gateway_events        — P1: Gateway publishes routing/dispatch events to A2ABus
  persistent_worker_pool    — P2: Persona-level long-running workers with experience archive

Coder Agent modules (default False — Route B of docs/coder-agent-技术方案.md):
  coder_agent               — master toggle for CoderAgent (AgentType.CODER)
  coder_agent_slash         — slash commands (/plan, /fix, /review, /test, /explain, /refactor)
  coder_agent_memory        — project memory file (<workspace>/.coder/memory.md)
  coder_agent_plan_mode     — /plan read-only-then-approve mode
  coder_agent_compaction    — coder-specific preflight compaction strategy
  coder_agent_milestone     — MilestoneExecutor (acceptance_criteria + touched_paths + budget guards)
  coder_agent_task_mode     — V2 task mode: TaskPlanner + MilestoneDAGExecutor (goal decomposition)

Coder Agent 长程自主化 modules (docs/Coder-Agent长程自主化技术方案.md §6.1):
  Group B — Context quality (default OFF unless noted):
    coder_prompt_cache                — B1: provider cache_control breakpoints
    coder_read_dedup                  — B2: read_file content-hash dedup (default ON)
    coder_context_tiered_compaction   — B3 + D2: tiered compaction w/ util% threshold
    coder_live_repo_context           — B4: auto-collect git/CLAUDE.md/manifest
    coder_auto_working_memory         — B5: milestone-end distill → .coder/memory.md
  Group C — Long-horizon autonomy (mixed defaults after PR-D1):
    coder_midflight_replan            — C1: re-plan remaining DAG
    coder_dag_expansion               — C2: spawn_sibling_milestone tool (default ON
                                          per PR-D1 #1 decision; per-mode caps:
                                          task=3, milestone=1)
    coder_task_checkpoint             — C3: DAG-level checkpoint + resume
                                          (default ON per PR-D1 #1; satisfies
                                          dag_expansion interlock §6.2 rule 3)
    coder_milestone_auto_commit       — C3 sub: auto git commit per milestone
    coder_mandatory_grader            — C4: force Grader eval post-acceptance
    coder_fresh_grader                — PR-R4: spawn fresh-context Grader subagent
                                          (eliminates in-session confirmation bias;
                                          requires coder_mandatory_grader)
  Group D — Industry alignment (mixed defaults):
    coder_steering_queue              — D1: mid-turn interrupt queue (default ON)
    coder_todo_write                  — PR-D1: LLM-managed task list tool
                                          (default ON per decision #1)
    coder_worktree_isolation          — D3: git worktree per parallel milestone
    coder_milestone_model_routing     — D7: complexity_tag → model selector
    coder_semantic_index              — D4: Sprint 5+ placeholder
  Group A — Entry unification (stage-based feature flags):
    coder_milestone_entry_deprecated  — §6.2.4: grace-period deprecation warning
    legacy_milestone_entry_restore    — §11.1: Sprint 4 emergency rollback (re-activates the deleted /coder/milestones path)

Interlocks (fail-closed at from_config, §6.2):
  - coder_live_repo_context requires coder_prompt_cache
  - coder_dag_expansion requires coder_task_checkpoint

Backend selectors (scalar — NOT a boolean toggle):
  persistent_worker_backend — "celery" | "local_sqlite" | "auto" (default "auto")
                              Controls which WorkerBackend the persistent worker
                              pool binds to.  HTTP sidecar (FastAPI + Celery beat)
                              → "celery"; CLI daemon (aibuddy daemon start) →
                              "local_sqlite".  "auto" defers to runtime form:
                              CLI picks local_sqlite, HTTP picks celery.
                              Config: runtime.persistent_worker_backend
                              Env:    RUNTIME__PERSISTENT_WORKER_BACKEND=<value>
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Module names — canonical list ──────────────────────────────────────────────
KNOWN_MODULES = frozenset(
    {
        # Phase 1
        "fallback_restore",
        "budget_pressure",
        "budget_stripping",
        "tool_dedup",
        "tool_repair",
        "activity_tracking",
        "plugin_hooks",
        "session_fsm",
        "preflight_compress",
        # Phase 2
        "tool_hook_middleware",
        "policy_engine",
        "permission_resolver",
        "memory_store",
        "memory_provider",
        "skill_registry_db",
        # Phase 2 P1
        "telemetry_recorder",
        "skill_api",
        "schedule_persistence",
        "checkpoint_manager",
        "trajectory_recorder",
        # Phase 3 P0
        "typed_subagent",
        "coordinator",
        # Phase 3 P1
        "lane_eventbus",
        "task_packet",
        "outcome_grader",
        "agent_versioning",
        "schedule_celery",
        # Phase 3 P2
        "span_events",
        # Phase 4 P0
        "environment",
        "vault",
        # Phase 4 P1
        "custom_tool",
        # Phase 4 P2
        "mock_service",
        "dashboard",
        "benchmark_runner",
        # Phase 5
        "persona",
        "query_router",
        # Phase 6.3 — Memory system wiring (§6.3 future-plan)
        "memory_tool_exposure",     # expose memory_* tools to the LLM
        "memory_prompt_injection",  # inject memory summaries into system prompt
        "activity_distillation",    # background L2 → L3/L4 distillation
        # Phase 6.1 — Vector RAG (§6.1 future-plan)
        "rag_retrieval",            # enable vector semantic search in kb_search
        "rag_ingestion",            # guard ingest CLI (disable in locked-down envs)
        "rag_tool_exposure",        # expose kb_semantic_search tool to the LLM
        # Phase 6.2 — Output Guard (§6.2 future-plan)
        "output_guard",             # master toggle for 3-layer output guard
        "output_guard_grounding",   # per-layer: numeric grounding
        "output_guard_citation",    # per-layer: citation verification
        "output_guard_nli",         # per-layer: LLM-based NLI
        "output_guard_enforce",     # permits mode=enforce (BLOCK on critical)
        # Phase 7.1 — OpenTelemetry distributed tracing (§7.1 future-plan)
        "otel_tracing",             # master toggle: provider setup + span export
        # Phase 7.2 — Multimodal Input (§7.2 future-plan)
        "multimodal_input",         # enable image content blocks in user messages
        # Phase 8.1 — Agent-to-Agent Standard Protocol (§8.1 future-plan)
        "a2a_protocol",             # publish AgentEnvelope/AgentEvent via A2ABus after dispatch
        # Phase 8.2 — Auto-evaluation pipeline (§8.2 future-plan)
        "eval_pipeline",            # enable batch offline evaluation; gated for prod safety
        # Phase 8.3 — Streaming structured output (§8.3 future-plan)
        "structured_output",        # inject response_format into DAG plan + follow-up Q calls
        # Phase 8.4 — Cross-process Agent communication (§8.4 future-plan)
        "a2a_transport",    # Phase A: pluggable BusBackend (local | redis_streams)
        "a2a_registry",     # Phase B: AgentRegistry + heartbeat (Redis HSET)
        "a2a_worker",       # Phase B: AgentWorker consumer process
        "a2a_rpc",          # Phase C: AgentRPCClient location-transparent dispatch
        "a2a_remote_spawn", # Phase D: SubAgentSpawner → RPC routing (live traffic)
        # Multi-agent optimization (Sprint 0 — default False, opt-in gradual rollout)
        "grader_retry_loop",         # P0: Generator-Verifier feedback-retry loop
        "a2a_gateway_events",        # P1: Gateway → A2ABus event publishing
        "persistent_worker_pool",    # P2: Persona-level long-running worker pool
        # SDLC PM Orchestrator (Sprint 1 — default False, opt-in rollout)
        "sdlc_pm_orchestrator",              # PM orchestration pipeline for SDLC delivery
        # Coder Agent (Route B — default False, opt-in gradual rollout)
        "coder_agent",               # master toggle for AgentType.CODER routing
        "coder_agent_slash",         # slash command expansion
        "coder_agent_memory",        # project memory file injection
        "coder_agent_plan_mode",     # /plan read-only then HITL approve mode
        "coder_agent_compaction",    # coder-specific preflight compaction strategy
        "coder_agent_milestone",     # MilestoneExecutor guards (paths/budget/accept)
        "coder_agent_task_mode",     # V2 — TaskGoal → MilestoneDAG planner + executor
        # Digital Avatar V1 (Gap 1 / S-1 POC → S1 — default False, opt-in rollout)
        "digital_avatar",              # one-tier digital_avatars entity + isolation
        "avatar_orchestrator",         # AvatarOrchestrator dispatch layer
        "avatar_orchestration_mode",   # coordinator/lane mode selection on top of single
        # S1.2 — when ON, AvatarOrchestrator returns recommended_agent_type=
        # "CODER" + task_goal payload for code-task issues so the gateway
        # follows up with a real CoderAgent dispatch instead of just
        # persisting placeholder coordinator threads.
        "avatar_route_to_coder",
        # S1.3 — when ON, MilestoneDAGExecutor publishes coder lifecycle
        # AgentEvents (milestone succeeded/failed/spawned, task
        # completed/aborted) onto the A2A bus so other agents can
        # subscribe without polling MongoDB.  Defaults ON — the
        # publisher is fire-and-forget with zero overhead when no
        # subscribers are registered.
        "coder_a2a_publish",
        # S1.5 — when ON, AgentScheduleService dispatches schedule
        # jobs whose payload mode is ``coder_task`` directly to
        # ``Gateway.dispatch(agent_type_hint="CODER", task_goal=...)``
        # so cron / interval driven coder runs (nightly lint fix,
        # weekly README refresh, etc.) execute through the same
        # MilestoneDAG path as CLI / HTTP submissions.  Default ON —
        # AI Collab scheduled tasks are a core staff feature; disable
        # via ``RUNTIME__MODULES__SCHEDULE_CODER_TASK_DISPATCH__ENABLED=false``
        # only when rolling back.  Interlock at boot requires
        # ``coder_agent`` + ``coder_agent_task_mode`` (same lesson
        # as S1.2: dispatching a TaskGoal payload without task-mode
        # support degrades to silent no-op).
        "schedule_coder_task_dispatch",
        # S1.6 PR1 — when ON, register
        # ``RequestCodeReviewTool`` so the CoderAgent LLM can
        # invoke the CR Agent's secret scanner over its own
        # touched files BEFORE closing a milestone.  Direction B
        # (Coder → CR) of the §3.1.6 plan.  Default OFF — the
        # tool is purely additive (read-only, no LLM call) but
        # opt-in until operators ramp it up.
        "coder_request_review_tool",
        # S1.6 PR2 — when ON, ``CrAgent.spawn_fix_task`` dispatches
        # an exhausted CR loop result through Gateway with
        # ``agent_type_hint="CODER"`` so a CoderAgent can take a
        # crack at fixing the issues the verifier flagged.
        # Direction A (CR → Coder) of the §3.1.6 plan.  Default OFF
        # — opt-in gradual rollout.  Boot interlock requires
        # ``coder_agent`` + ``coder_agent_task_mode`` (S1.5 lesson:
        # dispatching a TaskGoal payload without task-mode support
        # degrades to silent no-op).  Spawn is narrowly scoped to
        # ``reason="exhausted"`` only — secret_scanner_hit /
        # budget / lock / exception reasons keep the legacy
        # ``needs_human_review`` path.
        "cr_spawn_coder_fix",
        # S1.7 — when ON, register ``DispatchToWorkerTool`` so the
        # CoderAgent LLM can hand long-running tasks (model
        # fine-tune, full regression suite, large data fetch) off
        # to the persistent worker pool instead of blowing the
        # current milestone budget.  Default OFF — opt-in gradual
        # rollout.  Interlock at boot requires ``coder_agent`` +
        # ``persistent_worker_pool`` (the dispatch surface is
        # meaningless without the master toggle, and there's no
        # backend to hand off to without the worker pool toggle).
        "coder_worker_dispatch_tool",
        # S2.1 — when ON, ``AgentLoop._execute_single_tool`` fires
        # external-process hooks at three points (PreToolUse /
        # PostToolUse / PostToolUseFailure).  Hooks are arbitrary
        # subprocess execution loaded from
        # ``~/.aibuddy/hooks.toml`` + ``<workspace>/.coder/hooks.toml``;
        # operators must explicitly opt in.  Default OFF — Claude
        # Code parity but with strict validation, hard timeout,
        # workspace-root CWD, and stderr cap.
        "external_process_hooks",
        # S2.2 — when ON, ``CoderAgent`` accepts ``TaskRequest.
        # attachments`` and converts them into multimodal content
        # blocks for the first user message.  Requires a vision-
        # capable model (Anthropic / Qwen-VL / OpenAI gpt-4o);
        # non-vision providers fail-fast at LLM call time.
        # Default OFF — opt-in until operators verify their
        # provider supports vision.
        "coder_multimodal_input",
        # S2.3 — when ON, register Playwright MCP browser tools
        # (browser_navigate / browser_snapshot / browser_click /
        # browser_console_messages) into the CoderAgent tool
        # registry so the LLM can self-validate web outputs.
        # Requires the ``@playwright/mcp`` npm package + a
        # Chromium install on the runtime host.  Default OFF.
        "coder_browser_tool",
        # Sprint 7 — when ON, ~/.aibuddy/mcp_servers.toml is parsed at
        # daemon / web app startup and every declared MCP server is
        # spawned (stdio) or connected (http).  Each server's tools
        # surface in CoderAgent's registry as ``{prefix}__{tool}``.
        # Schema enforces strict safety rules (no shell wrappers, no
        # http URLs, no inline secrets).  Requires coder_agent ON.
        "coder_mcp_external_servers",
        # Sprint 8 — when ON, the read-only ``get_worker_summary`` tool
        # is registered into the CoderAgent registry.  Returns
        # active_workers / queue_depth / failures_last_hour for the
        # LLM's persona; used to decide between dispatch_to_worker and
        # inline execution.  Per-(workspace, persona) call budget caps
        # at 5/milestone (anti-polling).  Requires
        # ``persistent_worker_pool`` ON for the backend.
        "coder_worker_summary_tool",
        # Sprint 10 PR-6 — when ON, ``PlanModeState.restriction`` ==
        # READ_AND_VALIDATE causes the plan-mode registry to expose
        # the FULL tool schema (mutating tools included).  The F7
        # enforcer denies mutating calls at runtime with
        # ``plan_mode_blocked`` reason.  Closes the plan ↔ exec
        # discontinuity (legacy READ_ONLY hid mutating tools so the
        # LLM's plan sometimes referenced tools it couldn't see).
        # Default OFF — restriction defaults to READ_ONLY which is
        # the legacy behaviour.
        "coder_plan_mode_lattice",
        # Sprint 10 PR-1 — when ON, register ``WebFetchTool`` and
        # ``WebSearchTool`` into the CoderAgent tool registry so the
        # LLM can fetch URLs / search the web in-loop without
        # operator intervention.  Both tools are independent —
        # operators can opt in to one without the other.  Default OFF;
        # interlock at boot requires ``coder_agent`` (the registry
        # exists only on the master path).
        "coder_web_fetch_tool",
        "coder_web_search_tool",
        # When ON, register ``CloneRepoTool`` so the LLM can shallow-clone
        # HTTPS repos into the workspace (``bash_exec git clone`` remains
        # denied). Default OFF; requires ``coder_agent`` ON.
        "coder_clone_repo_tool",
        # Sprint S-EK-V1 PR 4 — when ON, toggling an expert kit in
        # ``POST /api/v1/personas/{id}/toggle`` triggers full fan-out:
        # writes ``user_mcp_servers`` rows, calls
        # ``McpServerManager.reload_for_user`` (live-spawn the kit's
        # stdio MCP clients), enables ``user_skill_prefs``. Per-request
        # tool registry merges user-scope MCP tools into the LLM's
        # tool list so the LLM actually sees the bundled tools right
        # after toggle-on. Requires ``coder_mcp_external_servers`` ON
        # (we need a live ``McpServerManager`` to spawn into; without
        # it the toggle endpoint persists rows but tools never appear
        # — silent half-installed state, fail-closed at boot).
        "expert_kit_auto_install",
        # Sprint 9 — when ON, ``POST/GET/DELETE /api/v1/coder/attachments``
        # endpoints persist uploads to disk under shared storage,
        # enforce SHA dedupe / size+mime+magic-number validation /
        # per-task + per-workspace daily quotas, and write
        # attachment_upload / _download / _access_denied / _delete
        # entries to audit_logs.  Requires ``coder_multimodal_input``
        # ON (otherwise attachments are dropped silently at the
        # planner injection step — fail-closed at boot).
        "coder_attachment_persistence",
        # Sprint 9 — when ON, attachment blobs are encrypted at rest
        # using the configured Vault provider before being written
        # to disk.  Requires ``coder_attachment_persistence`` ON.
        "coder_attachment_vault",
        # S3.1 — when ON, the Celery beat task
        # ``scan_approval_sla_breaches`` runs every 5 min, finds
        # pending approval requests older than
        # ``APPROVAL_SLA_THRESHOLD_HOURS`` env (default 24h),
        # sends Lark notification + flips the breach-alerted-at
        # column so we never double-notify.  Default OFF — opt-in
        # until operators verify their Lark wiring.
        "approval_sla_alert",
        # Digital Avatar V1 (Gap 2 — S2 Git permission ACL + ephemeral tokens)
        "git_repo_acl",                # per-repo read/write ACL hook + command whitelist
        "vault_ephemeral_git_token",   # per-task deploy token mint/revoke
        # Digital Avatar V1 (Gap 4 — S3 CLI push channel + version negotiation)
        "staff_task_poll",             # /api/v1/staff/tasks long-poll endpoint
        "cli_version_compat",          # X-Client-Version enforcement + /version/compat
        "staff_auth",                  # OAuth-PKCE + JWT staff auth endpoints
        # Staff issue drawer: async LLM reply for member assignees (/api/staff/issue-conv)
        "issue_conversation_llm",
        # Digital Avatar V1 (Gap 5 — S4 cost attribution + budget enforcement)
        "cost_avatar_attribution",     # cost_records.avatar_id/issue_id/user_id injection
        "avatar_budget_cap",           # pre-flight month-to-date vs monthly_budget_cap
        # Digital Avatar V1 (Gap 3 — S5 Code Review C-tier closed loop)
        "cr_agent_loop",               # master toggle: CR Agent + GeneratorVerifierLoop
        "cr_secret_scanner",           # pre-LLM secret scan gate (must pair with cr_agent_loop)
        "cr_allowed_llm_providers",    # LLM provider whitelist gate (must pair with cr_agent_loop)
        "gitlab_webhook",              # /api/v1/webhook/gitlab endpoint (auth + replay)
        # Digital Avatar V1 (Gap 6 — S6 concurrency defenses)
        "worker_cas_verification",     # agent_task_queue.worker_id CAS on dispatch + terminal writes
        "mid_run_hitl_policy",         # PolicyEngine HITL rules: destructive shell/SQL, high-token LLM, non-whitelist git, high-cost API
        # Token billing optimization (P5)
        "token_quota",              # Session-level token quota management (3-level)
        "cache_layout",             # Prompt cache prefix alignment
        "tool_compression",         # Tool result smart compression
        "tool_cache",               # Redis-backed tool result short-lived cache
        # Server-side data localization (docs/服务端数据本地化整改技术方案.md)
        "shared_storage_enforce",       # pre-flight refuse-to-boot in production if paths point at /tmp or HOME
        "registry_redis",               # _RUNTIME_REGISTRY snapshots via Redis instead of in-process dict
        "checkpoint_mongo",             # checkpoint metadata indexed in Mongo (blob still on shared volume)
        "trajectory_mongo",             # trajectory as Mongo append-only (local JSONL as fallback)
        "audit_log_central",            # audit_logs as Mongo primary with per-POD_ID fallback file
        "memory_browser_logical_id",    # memory browser project_root as logical ID (not filesystem path)
        # ws:{workspace_id}: / global: key prefix enforcement; tri-state: off|migration|on
        "redis_key_normalized",
        # TUI/Web runtime convergence (docs/TUI-Web-Runtime同构化技术方案.md §A1)
        # When ON, ``_persist_hitl_pending`` routes through the
        # ``StorageBackend.hitl_gates`` Protocol injected by
        # ``ConversationRuntime(storage=...)`` instead of inlining the
        # direct ``ai_assistant_db.kia_sessions`` Mongo write. Default OFF
        # in Sprint 1 — flipped ON after TUI dual-run validation (PR-G).
        # Fallback to inline Mongo path remains intact whenever
        # ``self._storage is None`` regardless of toggle state.
        "hitl_storage_backend",
        # CLI sync API (workstream C of 33-PR CLI-runtime plan)
        "cli_bundle_api",            # PR 14: GET /api/v1/cli/bundle (config/toggles push-down)
        "cli_sync_cost_api",         # PR 16: POST /api/v1/cli/sync/cost (CLI cost_records upload)
        "cli_sync_qa_api",           # PR 17: POST /api/v1/cli/sync/qa (CLI QA records upload)
        "cli_sync_session_api",      # PR 18: POST /api/v1/cli/sync/session (CLI sessions upload)
        "cli_health_api",            # PR 19: GET /api/v1/cli/health (CLI diagnostics closeout)
        "cli_revocation_api",        # PR 20: POST/GET /api/v1/admin/cli/revocations (workstream G)
        "cli_sync_audit_log_api",    # PR 21: POST /api/v1/cli/sync/audit_log (CLI audit upload)
        "cli_sync_agent_version_api",  # PR 23: POST /api/v1/cli/sync/agent_version
        "cli_audit_sink",            # PR 24: LocalRuntime 写 audit_logs (生产者)
        "cli_sync_skill_nudge_api",  # PR 32: POST /api/v1/cli/sync/skill_nudge (server endpoint)
        "cli_skill_evolution",       # PR 32: CLI-side nudge trigger loop
        "cli_custom_tool",           # PR 31: user-authored custom tool loader (default OFF)
        "custom_tool_http",          # B2: admin-registered HTTP custom tools (HttpCustomToolWrapper, default OFF)
        # CR auto-trigger (Spec PR 25 — GitLab webhook → cr_review_queue)
        "cr_agent_auto_trigger",     # enable webhook → cr_review row creation (default ON when present)
        # Lark heartbeat fallback (Spec PR 22 — CLI offline → redacted Lark push)
        "cli_lark_heartbeat_fallback",  # beat task scans heartbeat + pushes redacted notice (default ON)
        # Lark deliverable confirmation (workflow deliverable confirm/reject via Feishu card)
        "lark_deliverable_confirm",     # deliverable confirm/reject cards in Feishu (default OFF)
        # Spec PR 28 — CLI → server memory upload
        "cli_memory_sync",           # POST /api/v1/cli/sync/memory endpoint + CLI uploader (default ON)
        # Spec PR 29 — CLI session cross-device resume
        "cli_session_cross_device",  # GET /api/v1/cli/session/history + CLI pull-on-start (default ON)
        # Coder Agent 长程自主化 (docs/Coder-Agent长程自主化技术方案.md §6.1) ────
        # Group B — Context quality
        "coder_prompt_cache",               # B1 — provider cache_control breakpoints
        "coder_read_dedup",                 # B2 — read_file content-hash dedup (default ON)
        "coder_context_tiered_compaction",  # B3 + D2 — tiered compaction with util% threshold
        "coder_live_repo_context",          # B4 — auto-collect git/CLAUDE.md/manifest
        "coder_auto_working_memory",        # B5 — milestone-end distill → .coder/memory.md
        # Group C — Long-horizon autonomy
        "coder_midflight_replan",           # C1 — re-plan remaining DAG on failure/budget cascade
        "coder_dag_expansion",              # C2 — spawn_sibling_milestone tool
        "coder_task_checkpoint",            # C3 — DAG-level checkpoint + /resume
        "coder_milestone_auto_commit",      # C3 sub — auto git commit per milestone
        "coder_mandatory_grader",           # C4 — force Grader eval post-acceptance
        "coder_fresh_grader",               # PR-R4 — fresh-context Verification Specialist subagent
        # Group D — Industry alignment
        "coder_steering_queue",             # D1 — mid-turn interrupt queue (default ON)
        "coder_todo_write",                 # PR-D1 — TodoWrite tool (default ON per decision #1)
        "coder_llm_driven_plan_mode",       # PR-D2 — EnterPlanMode/ExitPlanMode tools (default OFF)
        "coder_dynamic_task_mode",          # PR-D3 — single-ROOT DAG + LLM self-expansion (default OFF)
        "coder_worktree_isolation",         # D3 — git worktree per parallel milestone
        "coder_milestone_model_routing",    # D7 — complexity_tag → model selector
        "coder_semantic_index",             # D4 — Sprint 5+ placeholder
        # OS Sandbox (coder_os_sandbox — default OFF, opt-in gradual rollout)
        "coder_os_sandbox",                    # master toggle for OS-level process isolation
        "coder_os_sandbox_network_proxy",      # hostname-allowlist network proxy
        "coder_os_sandbox_resource_limits",    # cgroup v2 + RLIMIT enforcement
        # Group A — Entry unification
        "coder_milestone_entry_deprecated",  # §6.2.4 — grace-period deprecation warning flag
        "legacy_milestone_entry_restore",    # §11.1 — Sprint 4 emergency rollback flag
        # Coder Agent — root cause fix plan (docs/CoderAgent-多文件任务完成率根因修复方案.md)
        "coder_large_write_router",          # F1: refuse oversized write_file payloads
                                              # (force LLM through patch_apply / skeleton+patch).
                                              # Default ON (drop-in safety net for R1).
        "coder_edit_file_tool",              # F5: anchored string-replace tool
                                              # (Claude Code Edit parity). Default ON
                                              # (pure additive tool; no destructive change).
        "coder_dynamic_decompose_protocol",  # F4: dynamic-mode ROOT milestone
                                              # is injected with a "decompose first"
                                              # protocol prompt + first-turn nudge.
                                              # Default ON (riding on dynamic mode).
        "coder_validation_strategy_switch",  # F2: repeated-validation-error
                                              # streak triggers a 3-state
                                              # remediation (hint → restrict_tools
                                              # → abort) instead of fast abort.
                                              # Default ON.
        "coder_integration_milestone_split", # F6: planner auto-splits
                                              # "integration"-tagged milestones
                                              # into skeleton + logic pairs.
                                              # Default ON.
        # Sprint 6 PR-4b — coder_permission_mode_v2 removed entirely.
        # V2 lattice is the unconditional permission path (legacy
        # 3-step cascade was deleted, no rollback path exists).
        "coder_bash_validation_v2",          # F8: 6 sub-validator bash safety
                                              # net. Default OFF for canary.
        # Sprint 11 PR-A1 — when ON, ``_split_acceptance_chain`` uses
        # the bashlex AST parser instead of the legacy regex.  Fixes
        # the Sprint 10 dogfood long tail (quoted-operator false splits,
        # missing ``||`` / ``;`` support, silent mis-parse of subshells
        # / pipelines / redirects / command substitution).  Default OFF
        # for canary; AST parse failures fall back to single-segment
        # delivery so the existing allowlist still enforces safety.
        # NOTE: no boot-time interlock — the toggle is self-contained
        # inside ``_split_acceptance_chain`` and degrades to legacy
        # regex if the bashlex import or toggle read fails.
        "coder_acceptance_ast_split",
        # Sprint 11 PR-A2 — when ON, the planner system prompt
        # advertises the new ``cwd`` / ``setup_steps`` fields on
        # ``acceptance_criteria`` entries AND the executor honours
        # them at run time (criterion.cwd overrides legacy glob
        # heuristic; setup_steps run as independent allowlist-checked
        # subprocesses before the main command).  Default OFF for
        # canary.  No interlock — the new fields parse silently when
        # OFF (back-compat) and only become active when both planner
        # and executor see the toggle ON together (single switch
        # avoids half-on states).
        "coder_acceptance_schema_v2",
        # Sprint 11 PR-A3 — when ON, ``_verify_command`` runs every
        # segment of an acceptance chain inside a single persistent
        # ``/bin/bash`` subprocess.  Bash itself preserves ``cd`` /
        # env / shell functions across segments so the Python-side
        # ``running_cwd`` mutation hack from Sprint 10 disappears.
        # Allowlist still validates each segment.  Boot interlock:
        # requires ``coder_acceptance_ast_split`` (PR-A1) ON because
        # the segment boundaries must be AST-derived (regex split
        # mis-handles quoted operators, defeating the persistent
        # shell's quoting fidelity).
        "coder_persistent_shell_acceptance",
        # Option-3 Sprint PR 1 — when ON, HITL pause persists the live
        # ``DAGPlan`` + completed task outputs + paused task info to
        # ``kia_sessions.dag_checkpoint`` so the resume path (PR 3) can
        # re-enter ``DAGExecutor`` at the paused task with the SAME
        # ``tool_call_id``. Today's re-plan path generates a fresh call_id
        # which defeats ``scope=once`` and causes "approve once → re-plan
        # → re-ask" loops (observed 26 cycles in dogfood). Default OFF for
        # canary: PR 1 is pure infrastructure (this file imports & module
        # exist, but no callers wire it in until PR 3 lands). Toggle OFF =
        # byte-identical to today's behaviour. No boot-time interlock — the
        # module is self-contained and PR 3 will check this toggle at the
        # single switch point in ``continue_after_hitl_approval``.
        "dag_stateful_resume",
        # Conversational Coder mode — when ON, TUI chat panel routes
        # ``agent_type="CODER"`` turns through a lightweight ReAct loop
        # with coder file/bash/patch tools instead of the structured
        # task/milestone execution pipeline.  Enables multi-turn
        # conversational coding (fix bug, explain changes, follow-up
        # questions) without requiring a formal milestone payload.
        # Requires ``coder_agent`` ON (master toggle).  Default OFF —
        # opt-in rollout once conversational-coder path is validated.
        "coder_agent_chat_mode",
        # TUI/CLI Gateway routing — when ON, ``LocalRuntime.chat_turn``
        # runs ``Gateway.pre_filter`` (dedup / rate-limit / greeting
        # fast-track) and ``Gateway.route_only`` (Router LLM picks
        # ``agent_type`` from query semantics) before the existing
        # ``_build_*_loop`` paths.  Hydration data (skills / personas)
        # is pulled from the server on TUI launch and cached locally,
        # so the CLI-side Gateway sees the same data as the server-side
        # Gateway (双端同构).  Fail-soft everywhere — hydration miss
        # or Gateway exception falls back to the legacy path.
        "tui_gateway_routing",
        # V2 H1 — server endpoint that exposes MCP ``tools_info`` to
        # the CLI Hydrator.  Default OFF; when ON, returns the same
        # ``ToolsInfo`` shape as ``mcp_client.get_tools_info()``
        # (no shape transformation) so CLI ``MCPToolAdapter.register_all``
        # can consume it as-is.
        "cli_tools_info_api",
        # V2 H6 — when ON, ``LocalRuntime._get_or_build_gateway`` constructs
        # a local ``LaneManager`` (in-process; no DB / Redis / server
        # infra) and passes it to ``Gateway`` so future
        # ``Gateway.dispatch(agent_type=PARALLEL_LANE)`` paths run lanes
        # locally.  Lane / LaneCoordinator / EventBusMerger are already
        # in-process pure asyncio (agent/lane/lane.py + event_bus.py); no
        # extra plumbing needed.  V1 ``route_only`` path doesn't use this
        # — pre-baked for V2 H2 dispatch.
        "tui_lane_local",
        # V2 H6 — when ON, ``LocalRuntime._get_or_build_gateway`` constructs
        # a local ``AvatarOrchestrator`` backed by
        # ``SqliteCoordinatorThreadRepository`` (offline-first; no Mongo /
        # MySQL).  ``persona_resolver`` reads from the hydrated snapshot,
        # ``cost_record_dao=None`` (offline = no budget enforcement).
        "tui_avatar_local",
        # V2 H2 — when ON, ``LocalRuntime.chat_turn`` calls
        # ``Gateway.dispatch()`` after ``route_only`` to obtain a fully
        # configured BaseAgent (Gateway has applied ToolPolicy + skill
        # injection + persona allowlist + ask_colleague tool) and reuses
        # the dispatched agent's ``llm`` + ``_tool_registry`` to build a
        # fresh ``AgentLoop`` driven by the existing chat_turn machinery.
        # **Does NOT call BaseAgent.run()** — sidesteps the StreamResponse
        # ↔ LoopEvent abstraction mismatch.  Falls back to the legacy
        # ``_build_*_loop`` path on any dispatch / extraction error.
        # Hard requires ``tui_gateway_routing`` ON (interlock).
        "tui_gateway_dispatch",
        # When ON, the ``AgentLoop`` instances built by
        # ``LocalRuntime._build_coder_chat_loop`` and ``_build_agent_loop``
        # are constructed with ``enable_streaming=True``.  LLM content
        # tokens then flow through ``STREAMING_DELTA`` events as they
        # arrive, so the TUI's ``text_delta`` handler prints text live
        # instead of waiting for the full response.  Coder milestone /
        # task branches additionally emit per-tool TOOL_CALL/TOOL_RESULT
        # envelopes + REQUIRES_APPROVAL on HITL pause so the chat UI
        # renders Claude-Code-style inline tool cards + ApprovalCard.
        # Falls back to non-streaming on any LLM client that doesn't
        # support ``client.chat.completions.stream(...)``.  Default ON
        # post-HITL-redesign.
        "coder_loop_streaming",
        # When ON, ``agent.dag_execution._execute._ExecuteMixin`` upgrades
        # its per-task progress callback from ``StepType.CONTENT`` blobs
        # to per-tool ``StepType.TOOL_CALL`` / ``TOOL_RESULT`` envelopes
        # (one CALL on ``task_start`` + one RESULT on
        # ``task_complete`` / ``task_failed``, paired by ``task_id`` →
        # ``tool_call_id``).  Default OFF so existing CONTENT progress
        # consumers (DeepThink dashboards, log scrapers) stay
        # byte-identical until the chat UI's ToolEventList is rolled out
        # to non-Coder agents.
        "dag_tool_envelopes",
        # CLI Tavily fallback proxy for dispatched MCP ``web_search`` —
        # see ``_DEFAULT_DISABLED`` for rollout notes.
        "cli_web_search_tavily_fallback",
        # M1 (docs/平台底座沉淀路线图.md Track A) — internal plugin loader.
        # When ON, ``src/agent/plugin_loader.py`` scans ``importlib.metadata``
        # entry_points for groups ``aibuddy.agents`` / ``aibuddy.tools`` /
        # ``aibuddy.personas`` / ``aibuddy.skills`` at startup and registers
        # discovered objects into the live registries.
        #
        # Security-sensitive: anything an operator pip-installs in the same
        # venv that declares one of these entry_points will be loaded into
        # the agent process.  Default OFF.  See ``runtime.plugins.allowlist``
        # for distribution-name allowlist (companion config in default.yaml /
        # ``RUNTIME__PLUGINS__ALLOWLIST`` env).
        "agent_plugins",
        # M3 (docs/平台底座沉淀路线图.md Track A) — Persona / Skill hot-reload.
        # When ON, a background watcher polls each registered YAML
        # source directory every 30s; mtime changes trigger an
        # in-memory cache refresh.  Default OFF — operators opt in
        # per environment.  Independent from the ``agent_plugins``
        # toggle: hot-reload covers in-tree ``conf/personas/`` /
        # ``conf/skills/`` even without plugins.
        "persona_hot_reload",
        "skill_hot_reload",
        # M3 PR-4 — when ON, ``POST /api/admin/catalog/reload`` also
        # publishes to ``aibuddy:catalog:reload`` Redis pubsub channel
        # so other pods reload immediately (vs waiting up to 30s for
        # their own poll cycle).  Local reload is unaffected by this
        # toggle — broadcast is a multi-pod optimisation only.
        # Default OFF — multi-pod readiness is a Track B concern.
        "cross_pod_catalog_reload",
        # ── HITL Redesign (Claude-Code-style approval) ────────────────
        # Master switch for the V2 envelope (``arguments`` / ``risk_level`` /
        # ``editable_args`` / ``scope_options``). Default ON — the
        # legacy ``tool_args`` field is still mirrored for back-compat
        # so V1 frontends keep working during rollout.
        "hitl_v2_protocol",
        # When ON, ``runtime.policy.decision_memory.lookup`` checks
        # session/forever decisions before firing the resolver. OFF
        # forces every call to ask again — useful for debugging the
        # gate path or rolling back a regression in the memory store.
        "hitl_decision_memory",
        # When ON, ``/hitl/decide`` records ``session`` / ``forever``
        # scope decisions to Mongo (``hitl_decisions`` array on the
        # session doc + ``kia_user_tool_preferences`` collection).
        # OFF makes scope=session / scope=forever decay to scope=once
        # (no persistence, no cross-call reuse).
        "hitl_resume_react",
        # When ON, ``_handle_approve`` does not just single-step execute
        # the gated tool; it also fires a background task that re-enters
        # ``Gateway.dispatch`` with the same session id and ``agent_type_hint``
        # so the agent picks up its previous answer (now including the
        # HITL-approved tool result) and finishes the milestone without
        # the user having to type "continue". OFF keeps the V1 behavior:
        # the SSE channel is closed right after the tool result envelope.
        "hitl_auto_resume",
    }
)

# Modules that default to DISABLED (opt-in rollout).
# Every other module in KNOWN_MODULES defaults to enabled for backward compatibility.
_DEFAULT_DISABLED: frozenset[str] = frozenset(
    {
        "grader_retry_loop",
        "a2a_gateway_events",
        # Phase 8.4 Phase D — SubAgentSpawner → RPC routing.  Default OFF
        # to match the rest of the a2a Phase A-C toggles (transport /
        # registry / worker / rpc are all opt-in).  When ON without a
        # remote worker pool deployed AND without llm injected into the
        # AgentRPCClient singleton, `_local_call` falls through to a
        # FAILED envelope on every spawn — caught in the coordinator
        # thread dogfood where `spawn_subagent` returned success=False
        # within 14ms regardless of inputs.  Operators flipping this ON
        # must also ensure a2a_transport + a2a_registry + a2a_worker are
        # configured.
        "a2a_remote_spawn",
        "persistent_worker_pool",
        # PR 31 — CLI custom tool loader. Security-sensitive (loads
        # arbitrary user Python into the agent process); default OFF,
        # user must consciously opt in via toggle file.
        "cli_custom_tool",
        # B2 — admin-registered HTTP custom tools. Security-sensitive
        # (every enabled doc gets called as a remote HTTP endpoint by
        # the agent loop). Default OFF; operator must enable explicitly
        # after vetting which custom_tool_defs entries are safe.
        "custom_tool_http",
        # SDLC PM Orchestrator — opt-in gradual rollout
        "sdlc_pm_orchestrator",
        # Coder Agent (Route B) — opt-in gradual rollout
        "coder_agent_slash",
        "coder_agent_memory",
        "coder_agent_plan_mode",
        "coder_agent_compaction",
        "coder_agent_milestone",
        # Digital Avatar V1 (Gap 1) — opt-in gradual rollout
        "digital_avatar",
        "avatar_orchestrator",
        "avatar_orchestration_mode",
        "avatar_route_to_coder",  # S1.2 — opt-in
        "coder_request_review_tool",  # S1.6 PR1 — opt-in
        "cr_spawn_coder_fix",  # S1.6 PR2 — opt-in
        "coder_worker_dispatch_tool",  # S1.7 — opt-in
        "external_process_hooks",  # S2.1 — opt-in (subprocess execution)
        "coder_multimodal_input",  # S2.2 — opt-in (vision provider required)
        "coder_browser_tool",  # S2.3 — opt-in (Playwright MCP install required)
        "coder_mcp_external_servers",  # Sprint 7 — opt-in (toml + binaries required)
        "expert_kit_auto_install",  # Sprint S-EK-V1 PR 4 — opt-in (depends on MCP)
        "coder_worker_summary_tool",  # Sprint 8 — opt-in (worker pool required)
        "coder_web_fetch_tool",  # Sprint 10 PR-1 — opt-in (network egress)
        "coder_web_search_tool",  # Sprint 10 PR-1 — opt-in (search backend required)
        "coder_plan_mode_lattice",  # Sprint 10 PR-6 — opt-in (lattice gating)
        "coder_attachment_persistence",  # Sprint 9 — opt-in (disk + audit)
        "coder_attachment_vault",  # Sprint 9 — opt-in (Vault encrypt-at-rest)
        "approval_sla_alert",  # S3.1 — opt-in (Lark wiring required)
        "hitl_auto_resume",  # V2 HITL auto-continuation — opt-in until soaked

        # Digital Avatar V1 (Gap 2 / Gap 4) — opt-in gradual rollout
        "git_repo_acl",
        "vault_ephemeral_git_token",
        "staff_task_poll",
        "cli_version_compat",
        "staff_auth",
        # Digital Avatar V1 (Gap 5) — opt-in gradual rollout
        "cost_avatar_attribution",
        "avatar_budget_cap",
        # Digital Avatar V1 (Gap 3) — opt-in gradual rollout
        "cr_agent_loop",
        "cr_secret_scanner",
        "cr_allowed_llm_providers",
        "gitlab_webhook",
        # Digital Avatar V1 (Gap 6) — opt-in gradual rollout
        "worker_cas_verification",
        "mid_run_hitl_policy",
        # Token billing optimization (P5) — opt-in gradual rollout
        "token_quota",
        "cache_layout",
        "tool_compression",
        "tool_cache",
        # Server-side data localization — all opt-in; OFF == pre-remediation baseline
        "shared_storage_enforce",
        "registry_redis",
        "checkpoint_mongo",
        "trajectory_mongo",
        "audit_log_central",
        "memory_browser_logical_id",
        "redis_key_normalized",
        # TUI/Web runtime convergence — opt-in; OFF == direct Mongo write path
        "hitl_storage_backend",
        # F8 — opt-in canary per §3.F8.  Sprint 6 PR-4b removed F7's
        # ``coder_permission_mode_v2`` toggle entirely (V2 unconditional).
        "coder_bash_validation_v2",
        # Coder Agent 长程自主化 (docs/Coder-Agent长程自主化技术方案.md §6.1) ────
        # Default OFF — canary rollout per §6.3 Sprint 1-4 schedule.
        # coder_read_dedup and coder_steering_queue are intentionally NOT in this
        # list because they default ON per the plan (B2 is pure optimization,
        # semantically safe; D1 is low-risk and user-visible).
        # PR-D1 (动态Plan化迁移方案 decision #1) flips three more defaults to ON:
        # coder_todo_write, coder_dag_expansion, coder_task_checkpoint —
        # also kept OUT of this list. Rollback via env vars
        # `RUNTIME__MODULES__CODER_*__ENABLED=false`.
        "coder_prompt_cache",
        "coder_context_tiered_compaction",
        "coder_live_repo_context",
        "coder_auto_working_memory",
        "coder_midflight_replan",
        # PR-D1 #1 decision: coder_dag_expansion + coder_task_checkpoint flip
        # to default ON together (interlock §6.2 rule 3 requires both).
        # Both are intentionally NOT in this list.
        # "coder_dag_expansion" — default ON (PR-D1)
        # "coder_task_checkpoint" — default ON (PR-D1, satisfies dag_expansion interlock)
        "coder_milestone_auto_commit",
        "coder_mandatory_grader",
        "coder_fresh_grader",               # PR-R4
        # PR-D2 — LLM-driven plan mode tools. Default OFF for canary;
        # mutually exclusive with the slash-driven coder_agent_plan_mode
        # (validate_coder_interlocks enforces).
        "coder_llm_driven_plan_mode",
        # PR-D3 — dynamic task mode (single-ROOT DAG + LLM expansion).
        # Default OFF; interlock requires coder_todo_write +
        # coder_dag_expansion + coder_llm_driven_plan_mode (D1+D2 deps).
        "coder_dynamic_task_mode",
        "coder_worktree_isolation",
        "coder_milestone_model_routing",
        "coder_semantic_index",
        "coder_milestone_entry_deprecated",
        "legacy_milestone_entry_restore",
        # OS Sandbox — opt-in gradual rollout
        "coder_os_sandbox",
        "coder_os_sandbox_network_proxy",
        "coder_os_sandbox_resource_limits",
        # Lark deliverable confirmation — opt-in gradual rollout
        "lark_deliverable_confirm",
        # Sprint 11 — Acceptance command root-cause fix series.  All
        # default OFF for canary rollout (PR-A1 ramp-up runs alongside
        # the Sprint 10 regex path so a misbehaving AST parser can be
        # rolled back via env without code change).
        "coder_acceptance_ast_split",
        "coder_acceptance_schema_v2",
        "coder_persistent_shell_acceptance",
        # Option-3 Sprint PR 1 — opt-in canary; toggle OFF = byte-identical
        # to today (HITL resume re-plans from scratch, scope=once doesn't
        # match new call_id, loops). See toggle doc-block above for the full
        # PR series context.
        "dag_stateful_resume",
        # Conversational Coder mode — opt-in (requires coder_agent ON).
        "coder_agent_chat_mode",
        # TUI/CLI Gateway routing — opt-in.  No interlock (Gateway uses
        # graceful-degraded FastFilter and Router; hydration is
        # fail-soft).
        "tui_gateway_routing",
        # V2 H1 — opt-in (default OFF).  When OFF, /api/v1/cli/tools-info
        # returns 503 and the CLI Hydrator silently degrades (tools_info
        # field stays None on the snapshot).
        "cli_tools_info_api",
        # V2 H6 — opt-in (both default OFF).  Gateway construction in
        # LocalRuntime checks these to decide whether to inject local
        # LaneManager / AvatarOrchestrator instances.  Pre-baked plumbing
        # for V2 H2 dispatch path.  No interlock — both fail-soft on
        # construction errors.
        "tui_lane_local",
        "tui_avatar_local",
        # V2 H2 — opt-in (default OFF).  Interlock: requires
        # ``tui_gateway_routing`` ON (validated at boot in
        # ``validate_coder_interlocks`` analogue).  Construction failures
        # at the dispatch site are fail-soft (legacy path takes over).
        "tui_gateway_dispatch",
        # DAG per-task TOOL_CALL/TOOL_RESULT envelope upgrade for
        # DeepThink / QUICK_REASONING — opt-in (default OFF).  Frontend
        # ``ToolEventList`` already accepts the envelopes; turn ON once
        # downstream CONTENT-text consumers (dashboards / log scrapers)
        # have been migrated.
        "dag_tool_envelopes",
        # CLI web_search Tavily fallback — opt-in (default OFF).  When ON,
        # ``LocalRuntime`` dispatch path wraps the dispatched MCP
        # ``web_search`` wrapper with ``_TavilyFallbackProxy``: tries MCP
        # first, on isError / exception falls back to local
        # ``WebSearchTool`` (Tavily backend).  Interlock: requires
        # ``coder_web_search_tool`` ON (so a Tavily backend is configured
        # and ``WebSearchTool`` is importable).  No effect when MCP isn't
        # in the dispatched registry (e.g. legacy path / Eureka up).
        "cli_web_search_tavily_fallback",
        # M1 (docs/平台底座沉淀路线图.md) — entry_points-based plugin
        # loader.  Default OFF until each environment has reviewed the
        # plugin allowlist (``runtime.plugins.allowlist``) and ramped up.
        "agent_plugins",
        # M3 (docs/平台底座沉淀路线图.md) — Persona/Skill hot-reload.
        # Default OFF; opt-in per environment.
        "persona_hot_reload",
        "skill_hot_reload",
        # M3 PR-4 — cross-pod reload broadcast (Track B prerequisite).
        # Default OFF.
        "cross_pod_catalog_reload",
    }
)

# Default state map — True unless module is in _DEFAULT_DISABLED
_DEFAULT_ENABLED: dict[str, bool] = {
    name: (name not in _DEFAULT_DISABLED) for name in KNOWN_MODULES
}


# ── Toggle interlock rules ────────────────────────────────────────────────────


class ToggleInterlockError(RuntimeError):
    """Raised when two toggles violate a documented dependency.

    Interlocks are fail-closed: a misconfigured env that would produce
    divergent behavior aborts boot rather than silently enabling a broken
    combination.  Rules are defined in
    ``docs/Coder-Agent长程自主化技术方案.md §6.2``.
    """


def validate_coder_interlocks(states: dict[str, bool]) -> None:
    """Validate Coder Agent 长程自主化 toggle interlocks.

    Rules (§6.2 of the plan):

    1. ``coder_live_repo_context`` requires ``coder_prompt_cache``.
       Live repo context re-expanded every turn without provider cache would
       explode API cost 30-80%; the plan explicitly calls this fail-closed.

    3. ``coder_dag_expansion`` requires ``coder_task_checkpoint``.
       Expansion diverges the DAG from its original shape; without checkpoint
       a crash mid-expansion leaves no recovery surface.

    Rule 2 (``coder_midflight_replan`` half-on with ``coder_mandatory_grader``)
    is documented as an *allowed* half-open state and deliberately NOT enforced.

    Rule 4 (``coder_milestone_entry_deprecated``) is a stage-based feature flag,
    not an interlock.

    PR-D2 rule (动态Plan化迁移方案 decision #2): ``coder_llm_driven_plan_mode``
    and ``coder_agent_plan_mode`` are mutually exclusive. The legacy slash-
    driven plan mode (compile-time, prompt + registry baked in) and the new
    LLM-driven plan mode (runtime EnterPlanMode/ExitPlanMode tools) compose
    differently and would produce ambiguous behaviour if both fired.
    """
    violations: list[str] = []

    def _on(name: str) -> bool:
        return bool(states.get(name, False))

    if _on("coder_live_repo_context") and not _on("coder_prompt_cache"):
        violations.append(
            "coder_live_repo_context requires coder_prompt_cache "
            "(§6.2 rule 1: live context without cache explodes API cost)"
        )

    if _on("coder_dag_expansion") and not _on("coder_task_checkpoint"):
        violations.append(
            "coder_dag_expansion requires coder_task_checkpoint "
            "(§6.2 rule 3: expanded DAG diverges; no checkpoint = no recovery)"
        )

    if _on("coder_llm_driven_plan_mode") and _on("coder_agent_plan_mode"):
        violations.append(
            "coder_llm_driven_plan_mode and coder_agent_plan_mode are "
            "mutually exclusive (动态Plan化迁移方案 decision #2): pick "
            "either the runtime LLM tools (D2) OR the slash-driven "
            "compile-time plan mode (legacy)."
        )

    # PR-D3 dependency chain — dynamic mode needs:
    #   coder_todo_write           (LLM task list — decision #8)
    #   coder_dag_expansion        (spawn_sibling_milestone — D1)
    #   coder_llm_driven_plan_mode (LLM-driven plan/exec phases — D2)
    # Without all three, the dynamic-mode UX collapses (LLM has no way
    # to plan, no way to expand, no way to switch phases).
    if _on("coder_dynamic_task_mode"):
        for dep in (
            "coder_todo_write",
            "coder_dag_expansion",
            "coder_llm_driven_plan_mode",
        ):
            if not _on(dep):
                violations.append(
                    f"coder_dynamic_task_mode requires {dep} "
                    f"(动态Plan化迁移方案 §PR-D3 dependency chain)"
                )

    # OS Sandbox interlocks: sub-toggles require master toggle
    if _on("coder_os_sandbox_network_proxy") and not _on("coder_os_sandbox"):
        violations.append(
            "coder_os_sandbox_network_proxy requires coder_os_sandbox "
            "(network proxy without sandbox master toggle is meaningless)"
        )
    if _on("coder_os_sandbox_resource_limits") and not _on("coder_os_sandbox"):
        violations.append(
            "coder_os_sandbox_resource_limits requires coder_os_sandbox "
            "(resource limits without sandbox master toggle is meaningless)"
        )

    # S1.2 — avatar_route_to_coder dispatches a TaskGoal payload through
    # Gateway with agent_type_hint="CODER".  When coder_agent_task_mode
    # is OFF, ``CoderAgent._run()`` falls into the milestone branch and
    # the TaskGoal payload is silently ignored — the avatar invocation
    # appears to succeed but produces nothing.  Fail-closed at boot so
    # operators see the misconfiguration immediately.  Also requires the
    # master ``coder_agent`` toggle for the same reason.
    if _on("avatar_route_to_coder"):
        for dep in ("coder_agent", "coder_agent_task_mode"):
            if not _on(dep):
                violations.append(
                    f"avatar_route_to_coder requires {dep} "
                    "(S1.2: dispatching TaskGoal without task-mode "
                    "support degrades to silent no-op in CoderAgent._run)"
                )

    # S1.5 — schedule_coder_task_dispatch dispatches a TaskGoal payload
    # through Gateway with agent_type_hint="CODER" on every cron/interval
    # tick.  Same failure mode as S1.2: without coder_agent_task_mode the
    # CoderAgent falls into the milestone branch and the TaskGoal is
    # silently ignored — every scheduled run looks like it succeeded but
    # produces nothing.  Fail-closed at boot so operators see the
    # misconfiguration the first time a job fires.
    if _on("schedule_coder_task_dispatch"):
        for dep in ("coder_agent", "coder_agent_task_mode"):
            if not _on(dep):
                violations.append(
                    f"schedule_coder_task_dispatch requires {dep} "
                    "(S1.5: scheduled TaskGoal dispatch without "
                    "task-mode support degrades to silent no-op in "
                    "CoderAgent._run)"
                )

    # S1.6 PR1 — coder_request_review_tool only takes effect when the
    # CoderAgent path itself is reachable.  Without ``coder_agent`` the
    # tool is registered into a registry that's never built into a live
    # agent; turning the toggle on without the master is misconfigured
    # ops, not a working canary.  Fail-closed so operators see it the
    # first time they restart with the half-on combination.
    if _on("coder_request_review_tool") and not _on("coder_agent"):
        violations.append(
            "coder_request_review_tool requires coder_agent "
            "(S1.6: secret-scan tool is only registered into the "
            "CoderAgent tool registry; toggle ON without master is "
            "a no-op and signals misconfiguration)"
        )

    # S1.6 PR2 — same lesson as S1.2 / S1.5: dispatching a TaskGoal
    # payload through Gateway with agent_type_hint="CODER" requires
    # both the master ``coder_agent`` AND ``coder_agent_task_mode``,
    # otherwise the CoderAgent falls into the milestone branch and
    # the TaskGoal is silently ignored — every CR-spawned fix run
    # would look like it succeeded but produce nothing.
    if _on("cr_spawn_coder_fix"):
        for dep in ("coder_agent", "coder_agent_task_mode"):
            if not _on(dep):
                violations.append(
                    f"cr_spawn_coder_fix requires {dep} "
                    "(S1.6 PR2: dispatching TaskGoal without task-mode "
                    "support degrades to silent no-op in CoderAgent._run)"
                )
        # The spawn path is only reachable when the CR loop produces
        # a ``CrLoopResult`` — which only happens when the CR loop
        # itself runs.  Without ``cr_agent_loop`` operators turn the
        # spawn toggle on but it can never fire; flag the misconfig
        # at boot.
        if not _on("cr_agent_loop"):
            violations.append(
                "cr_spawn_coder_fix requires cr_agent_loop "
                "(S1.6 PR2: spawn path is only reachable when the CR "
                "loop runs; toggle ON without cr_agent_loop is a no-op)"
            )

    # S1.7 — coder_worker_dispatch_tool is registered only into the
    # CoderAgent tool registry (needs ``coder_agent``), and produces
    # work that goes to the persistent worker pool (needs
    # ``persistent_worker_pool``).  Either dep missing = silent
    # no-op or hard error at submit time; fail-closed at boot.
    if _on("coder_worker_dispatch_tool"):
        for dep in ("coder_agent", "persistent_worker_pool"):
            if not _on(dep):
                violations.append(
                    f"coder_worker_dispatch_tool requires {dep} "
                    "(S1.7: dispatch tool needs both the CoderAgent "
                    "registry and a live worker pool backend)"
                )

    # S2.2 / Sprint 9 follow-up — historical note:
    # ``coder_multimodal_input`` originally required ``coder_agent`` +
    # ``coder_agent_task_mode`` because attachments were ONLY consumed
    # on the CoderAgent task-mode planner path (TaskGoal → planner →
    # first user message).  A second consumer has since been wired in
    # the DeepThink / AICollab "添加文件" flow: Gateway.dispatch resolves
    # ``extraBody.attachment_ids`` via ``resolve_attachment_refs`` and
    # stores the inflated images on the agent; ``ResponseMixin``
    # injects them as multimodal blocks in the final-response LLM call.
    # That path runs regardless of CoderAgent toggles, so the
    # interlock is no longer fail-closed-correct — it would block
    # operators from enabling AICollab image upload unless they also
    # opt into the full CoderAgent + task-mode stack.  Removed.
    pass

    # S2.3 — coder_browser_tool only takes effect when the master
    # ``coder_agent`` toggle is on (the browser tools live in the
    # CoderAgent tool registry).  Without it the toggle is a no-op
    # and operators won't see "tool not found" until a real LLM
    # task tries to call ``browser_navigate``.
    # Sprint 7 — coder_mcp_external_servers requires coder_agent for
    # the same reason as browser_tool: external MCP tools register
    # into CoderAgent's tool registry, no point without master.
    if _on("coder_mcp_external_servers") and not _on("coder_agent"):
        violations.append(
            "coder_mcp_external_servers requires coder_agent "
            "(Sprint 7: external MCP tools are only registered into the "
            "CoderAgent tool registry; toggle ON without master "
            "is a no-op)"
        )

    # Sprint S-EK-V1 PR 4 — expert_kit_auto_install requires
    # coder_mcp_external_servers because the install fan-out spawns
    # MCP clients via McpServerManager.reload_for_user; without the
    # MCP master toggle, the manager is never bootstrapped (web app
    # set_external_mcp_manager(None)) and reload_for_user is a no-op.
    # The toggle endpoint would still write Mongo rows but no tool
    # ever surfaces to the LLM — silent half-installed state. Fail
    # closed at boot so operators see the misconfig before users do.
    if _on("expert_kit_auto_install") and not _on("coder_mcp_external_servers"):
        violations.append(
            "expert_kit_auto_install requires coder_mcp_external_servers "
            "(Sprint S-EK-V1 PR 4: kit fan-out spawns MCP clients via "
            "McpServerManager.reload_for_user; without the MCP master "
            "toggle, the manager is never bootstrapped — installs persist "
            "to Mongo but no tool reaches the LLM, a silent half-installed "
            "state)"
        )

    if _on("coder_browser_tool") and not _on("coder_agent"):
        violations.append(
            "coder_browser_tool requires coder_agent "
            "(S2.3: browser tools are only registered into the "
            "CoderAgent tool registry; toggle ON without master "
            "is a no-op)"
        )

    # Sprint 8 — coder_worker_summary_tool requires both ``coder_agent``
    # (the registry exists only on the master path) AND
    # ``persistent_worker_pool`` (no backend = nothing to query).  Half-on
    # would silently no-op so we fail closed at boot.
    if _on("coder_worker_summary_tool"):
        for dep in ("coder_agent", "persistent_worker_pool"):
            if not _on(dep):
                violations.append(
                    f"coder_worker_summary_tool requires {dep} "
                    "(Sprint 8 §5.6: read-only worker aggregate needs "
                    "both the CoderAgent registry and a live worker pool "
                    "backend)"
                )

    # Sprint 10 PR-1 — both web tools register only into the CoderAgent
    # registry; turning either on without the master is a no-op and
    # signals misconfiguration.  Same lesson as S2.3 / Sprint 7 / 8.
    if _on("coder_web_fetch_tool") and not _on("coder_agent"):
        violations.append(
            "coder_web_fetch_tool requires coder_agent "
            "(Sprint 10 PR-1: web_fetch is only registered into the "
            "CoderAgent tool registry)"
        )
    if _on("coder_web_search_tool") and not _on("coder_agent"):
        violations.append(
            "coder_web_search_tool requires coder_agent "
            "(Sprint 10 PR-1: web_search is only registered into the "
            "CoderAgent tool registry)"
        )
    if _on("coder_clone_repo_tool") and not _on("coder_agent"):
        violations.append(
            "coder_clone_repo_tool requires coder_agent "
            "(clone_repo is only registered into the CoderAgent tool registry)"
        )

    # cli_web_search_tavily_fallback wraps dispatched MCP web_search with a
    # Tavily fallback proxy; needs the local WebSearchTool importable AND
    # backend (TAVILY_API_KEY etc.) configured, both of which are gated by
    # coder_web_search_tool.
    if _on("cli_web_search_tavily_fallback") and not _on("coder_web_search_tool"):
        violations.append(
            "cli_web_search_tavily_fallback requires coder_web_search_tool "
            "(fallback target is the local Tavily WebSearchTool, which is "
            "only available when coder_web_search_tool is ON)"
        )

    # Sprint 9 — coder_attachment_persistence requires coder_multimodal_input.
    # Without multimodal, attachments are dropped at the planner injection
    # step (S2.2) so persisting them creates a backend leak with no
    # consumer.  Fail-closed at boot.
    if _on("coder_attachment_persistence") and not _on("coder_multimodal_input"):
        violations.append(
            "coder_attachment_persistence requires coder_multimodal_input "
            "(Sprint 9 §5.5: backend-only persistence with no LLM consumer "
            "leaks blobs to disk and burns daily quota)"
        )

    # Sprint 9 — coder_attachment_vault requires coder_attachment_persistence.
    # Vault encryption hooks live inside AttachmentStore; without persistence
    # there are no writes to encrypt.
    if _on("coder_attachment_vault") and not _on("coder_attachment_persistence"):
        violations.append(
            "coder_attachment_vault requires coder_attachment_persistence "
            "(Sprint 9 §5.5: encryption only triggers on the disk write "
            "path; no path = no-op)"
        )

    # Sprint 11 PR-A3 — coder_persistent_shell_acceptance requires the AST
    # split (PR-A1) so segment boundaries respect shell quoting.  The legacy
    # regex split would mis-cut commands like ``pytest -k "x && y"``, and
    # those mis-cut segments fed into a persistent shell would still execute
    # incorrectly — defeating the whole point of the rewire.
    if _on("coder_persistent_shell_acceptance") and not _on("coder_acceptance_ast_split"):
        violations.append(
            "coder_persistent_shell_acceptance requires coder_acceptance_ast_split "
            "(Sprint 11 PR-A3: persistent shell needs AST-derived segment "
            "boundaries; the regex splitter mis-handles quoted operators)"
        )

    # Conversational Coder mode — requires the master CoderAgent toggle.
    # Without coder_agent the tool registry and CoderAgent class are
    # gated off, so the chat-mode branch would silently no-op.
    if _on("coder_agent_chat_mode") and not _on("coder_agent"):
        violations.append(
            "coder_agent_chat_mode requires coder_agent "
            "(conversational coder mode routes through the CoderAgent "
            "tool registry; master toggle must be on)"
        )

    # V2 H2 — Gateway dispatch path can only run after pre_filter +
    # route_only have populated the dispatch context.  Without
    # tui_gateway_routing the Gateway instance isn't even constructed,
    # so dispatch would no-op silently.  Fail-closed at boot.
    if _on("tui_gateway_dispatch") and not _on("tui_gateway_routing"):
        violations.append(
            "tui_gateway_dispatch requires tui_gateway_routing "
            "(dispatch consumes the Gateway instance built only when "
            "the routing toggle is on)"
        )

    # M1 (docs/平台底座沉淀路线图.md) — agent_plugins is security-
    # sensitive: when ON, ``importlib.metadata`` entry_points from any
    # pip-installed distribution claiming the ``aibuddy.*`` groups are
    # loaded into the agent process.  Operators MUST configure an
    # explicit allowlist (``runtime.plugins.allowlist`` / env var
    # ``RUNTIME__PLUGINS__ALLOWLIST``) before flipping this on,
    # otherwise an accidental ``pip install`` of a third-party package
    # could inject arbitrary code.  The allowlist itself is enforced
    # in ``agent.plugin_loader``; here we just refuse to boot with
    # toggle ON + empty allowlist so the misconfiguration is caught
    # the first time it ships.
    if _on("agent_plugins"):
        # Accept either the live ModuleToggles attribute (carries the
        # parsed list) or fall back to env scan — works for unit tests
        # that exercise interlocks directly with a plain dict.
        allowlist_raw = states.get("__plugins_allowlist__")
        if allowlist_raw is None:
            allowlist_raw = os.environ.get(
                "RUNTIME__PLUGINS__ALLOWLIST", ""
            ).strip()
        if not allowlist_raw or (
            isinstance(allowlist_raw, (list, tuple, set, frozenset))
            and not allowlist_raw
        ):
            violations.append(
                "agent_plugins requires a non-empty plugin allowlist "
                "(set ``runtime.plugins.allowlist`` in default.yaml or "
                "``RUNTIME__PLUGINS__ALLOWLIST=pkg-a,pkg-b``).  "
                "Empty allowlist + toggle ON would load entry_points "
                "from ANY installed distribution — security risk."
            )

    # Sprint 1 PR-G — CLI/TUI/daemon must never connect to Mongo.
    # ``RUNTIME__STORAGE_BACKEND=mongo`` is an operator pin (the factory
    # ladder honours it ahead of the auto-detect). If that pin is set
    # while ``ENVIRONMENT`` is one of the local contexts, we have a
    # misconfiguration that would let a daemon / CLI process write
    # production Mongo from a developer laptop — refuse to boot.
    #
    # Read both vars directly (no toggle dependency) because the
    # storage backend selector is env-driven, not toggle-driven.
    _env = os.environ.get("ENVIRONMENT", "").strip().lower()
    _storage_pin = os.environ.get("RUNTIME__STORAGE_BACKEND", "").strip().lower()
    if _env in ("cli", "tui", "daemon") and _storage_pin == "mongo":
        violations.append(
            f"ENVIRONMENT={_env!r} + RUNTIME__STORAGE_BACKEND='mongo' is "
            "a forbidden combination — local contexts must not connect "
            "to production Mongo. Either unset RUNTIME__STORAGE_BACKEND "
            "(auto-detect picks SQLite) or set it to 'sqlite' explicitly. "
            "If you genuinely need Mongo from this process, change "
            "ENVIRONMENT to something other than cli/tui/daemon "
            "(docs/TUI-Web-Runtime同构化技术方案.md §A2)."
        )

    if violations:
        raise ToggleInterlockError("; ".join(violations))


@dataclass
class ModuleToggles:
    """
    Reads and caches the enabled/disabled state for every runtime module.

    Priority (highest wins):
      1. Environment variable  RUNTIME__MODULES__<MODULE>__ENABLED=true|false
      2. Config value           runtime.modules.<module>.enabled
      3. Hard-coded default     True (all modules enabled by default)

    Usage::

        toggles = ModuleToggles.from_config(app_config)

        if toggles.is_enabled("tool_dedup"):
            tool_calls = deduplicate_tool_calls(tool_calls)
    """

    # module_name → enabled
    _states: dict[str, bool] = field(default_factory=lambda: dict(_DEFAULT_ENABLED))

    # ── Queries ────────────────────────────────────────────────────────────────

    def is_enabled(self, module: str) -> bool:
        """
        Return True if *module* is enabled.

        Unknown module names return True (fail-open for forward compatibility).
        """
        if module not in KNOWN_MODULES:
            logger.debug("ModuleToggles.is_enabled: unknown module '%s', defaulting True", module)
        return self._states.get(module, True)

    def is_disabled(self, module: str) -> bool:
        return not self.is_enabled(module)

    def get_all(self) -> dict[str, bool]:
        """Return a snapshot of all module states."""
        return dict(self._states)

    # ── Mutations (runtime overrides) ─────────────────────────────────────────

    def enable(self, module: str) -> None:
        self._states[module] = True
        logger.info("ModuleToggles: enabled '%s'", module)

    def disable(self, module: str) -> None:
        self._states[module] = False
        logger.warning("ModuleToggles: DISABLED '%s'", module)

    # ── Factory ────────────────────────────────────────────────────────────────

    @classmethod
    def from_config(cls, config: Any) -> "ModuleToggles":
        """
        Build ModuleToggles from application config + environment variables.

        Config shape (conf/default.yaml)::

            runtime:
              modules:
                tool_dedup:
                  enabled: true
                tool_repair:
                  enabled: false
        """
        states = dict(_DEFAULT_ENABLED)

        # Layer 1: Config values
        try:
            rt = _get_nested(config, "runtime") or {}
            modules_cfg = _get_nested(rt, "modules") or {}

            for module in KNOWN_MODULES:
                mod_cfg = _get_nested(modules_cfg, module) or {}
                if mod_cfg is not None:
                    enabled = _get_nested(mod_cfg, "enabled")
                    if enabled is not None:
                        states[module] = bool(enabled)
        except Exception as exc:
            logger.warning("ModuleToggles.from_config: config read error (%s), using defaults", exc)

        # Layer 2: Environment variables override config
        for module in KNOWN_MODULES:
            env_key = f"RUNTIME__MODULES__{module.upper()}__ENABLED"
            env_val = os.environ.get(env_key)
            if env_val is not None:
                states[module] = env_val.strip().lower() in ("1", "true", "yes")
                logger.info(
                    "ModuleToggles: env override %s=%s → %s=%s",
                    env_key,
                    env_val,
                    module,
                    states[module],
                )

        # M1 — pre-resolve the plugin allowlist so interlock validation
        # can confirm the operator set one when ``agent_plugins`` is ON.
        # The list itself is not a toggle but the interlock needs it.
        try:
            states["__plugins_allowlist__"] = get_plugin_allowlist(config)  # type: ignore[assignment]
        except Exception as exc:  # noqa: BLE001 — interlock-only field
            logger.debug("plugin allowlist resolve error: %s", exc)
            states["__plugins_allowlist__"] = ()  # type: ignore[assignment]

        # Layer 3: Fail-closed interlock validation for Coder Agent 长程自主化
        # (docs/Coder-Agent长程自主化技术方案.md §6.2). Raised errors abort boot
        # rather than silently enabling broken combinations.
        validate_coder_interlocks(states)
        # Strip the side-channel so callers iterating ``get_all()`` only see
        # real boolean toggles (not internal interlock helpers).
        states.pop("__plugins_allowlist__", None)

        instance = cls(_states=states)
        disabled = [m for m, v in states.items() if not v]
        if disabled:
            # INFO not WARNING: this is a feature-flag inventory, not a
            # fault.  At WARNING level a 70-item list pollutes ops logs
            # and trains people to ignore the WARN tier.
            logger.info("ModuleToggles: disabled modules (%d) = %s", len(disabled), disabled)

        return instance

    def __repr__(self) -> str:
        disabled = [m for m, v in self._states.items() if not v]
        return f"ModuleToggles(disabled={disabled})"


# ── Helpers ────────────────────────────────────────────────────────────────────


def _get_nested(obj: Any, key: str) -> Any:
    """Safe attribute/dict access for config objects."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


# ── Scalar config selectors (not boolean toggles) ─────────────────────────────

_VALID_PERSISTENT_WORKER_BACKENDS = frozenset({"celery", "local_sqlite", "auto"})
_DEFAULT_PERSISTENT_WORKER_BACKEND = "auto"


def get_persistent_worker_backend(config: Any = None) -> str:
    """
    Resolve the ``persistent_worker_backend`` selector (celery | local_sqlite | auto).

    Priority (highest wins):
      1. env  ``RUNTIME__PERSISTENT_WORKER_BACKEND``
      2. config  ``runtime.persistent_worker_backend``
      3. default ``"auto"``

    Unknown values fall back to ``"auto"`` and emit a warning — this prevents
    a typo in production config from silently routing tasks to the wrong
    backend.  Callers that need a concrete backend must resolve ``"auto"``
    themselves based on deployment form (HTTP sidecar → celery, CLI → local_sqlite).
    """
    env_val = os.environ.get("RUNTIME__PERSISTENT_WORKER_BACKEND")
    if env_val is not None:
        candidate = env_val.strip().lower()
        if candidate in _VALID_PERSISTENT_WORKER_BACKENDS:
            return candidate
        logger.warning(
            "persistent_worker_backend: ignoring invalid env value %r (expected one of %s)",
            env_val,
            sorted(_VALID_PERSISTENT_WORKER_BACKENDS),
        )

    if config is not None:
        try:
            rt = _get_nested(config, "runtime") or {}
            cfg_val = _get_nested(rt, "persistent_worker_backend")
            if cfg_val is not None:
                candidate = str(cfg_val).strip().lower()
                if candidate in _VALID_PERSISTENT_WORKER_BACKENDS:
                    return candidate
                logger.warning(
                    "persistent_worker_backend: ignoring invalid config value %r",
                    cfg_val,
                )
        except Exception as exc:
            logger.debug("persistent_worker_backend: config read error %s", exc)

    return _DEFAULT_PERSISTENT_WORKER_BACKEND


# ── Redis key normalization tri-state selector ────────────────────────────────

_VALID_REDIS_KEY_MODES = frozenset({"off", "migration", "on"})
_DEFAULT_REDIS_KEY_MODE = "off"


def get_redis_key_mode(config: Any = None) -> str:
    """Resolve the ``redis_key_normalized`` mode selector.

    Returns one of ``"off" | "migration" | "on"`` (lowercase).

    Priority (highest wins):
      1. env  ``RUNTIME__MODULES__REDIS_KEY_NORMALIZED__MODE``
      2. env  ``RUNTIME__MODULES__REDIS_KEY_NORMALIZED__ENABLED``
         (``true`` → ``on``; any other → ``off``) — kept for backward compatibility
         with the boolean toggle surface so operations can flip a single
         env var during canary if tri-state not yet in Apollo.
      3. config ``runtime.modules.redis_key_normalized.mode``
      4. default ``"off"``
    """
    env_mode = os.environ.get("RUNTIME__MODULES__REDIS_KEY_NORMALIZED__MODE")
    if env_mode is not None:
        candidate = env_mode.strip().lower()
        if candidate in _VALID_REDIS_KEY_MODES:
            return candidate
        logger.warning(
            "redis_key_normalized: ignoring invalid env MODE %r (expected one of %s)",
            env_mode,
            sorted(_VALID_REDIS_KEY_MODES),
        )

    env_enabled = os.environ.get("RUNTIME__MODULES__REDIS_KEY_NORMALIZED__ENABLED")
    if env_enabled is not None:
        return "on" if env_enabled.strip().lower() in ("1", "true", "yes") else "off"

    if config is not None:
        try:
            rt = _get_nested(config, "runtime") or {}
            modules_cfg = _get_nested(rt, "modules") or {}
            mod_cfg = _get_nested(modules_cfg, "redis_key_normalized") or {}
            mode_val = _get_nested(mod_cfg, "mode")
            if mode_val is not None:
                candidate = str(mode_val).strip().lower()
                if candidate in _VALID_REDIS_KEY_MODES:
                    return candidate
                logger.warning(
                    "redis_key_normalized: ignoring invalid config mode %r", mode_val
                )
        except Exception as exc:
            logger.debug("redis_key_normalized: config read error %s", exc)

    return _DEFAULT_REDIS_KEY_MODE


# ── Plugin allowlist (M1: docs/平台底座沉淀路线图.md) ──────────────────────────


def get_plugin_allowlist(config: Any = None) -> tuple[str, ...]:
    """Resolve the entry_points distribution-name allowlist for ``agent_plugins``.

    Returns an empty tuple when nothing is configured.  Names are normalised
    to lowercase + canonical hyphenation (``importlib.metadata`` distribution
    names are case-insensitive but the canonical form replaces ``_``/space
    with ``-``) so operators don't have to worry about casing.

    Priority (highest wins):
      1. env  ``RUNTIME__PLUGINS__ALLOWLIST=pkg-a,pkg-b``
      2. config  ``runtime.plugins.allowlist`` (list[str] OR comma-separated str)
      3. default empty

    Even with the toggle ON, ``agent.plugin_loader`` will refuse to load any
    distribution whose canonical name isn't in this list — supply-chain
    defense for an opt-in feature.
    """

    def _canon(name: str) -> str:
        # PEP 503 normalisation: lowercase + collapse runs of [-_.] to single -.
        import re

        return re.sub(r"[-_.]+", "-", name.strip().lower())

    def _split(raw: Any) -> tuple[str, ...]:
        if raw is None:
            return ()
        if isinstance(raw, (list, tuple, set, frozenset)):
            items = [str(x) for x in raw]
        else:
            items = str(raw).split(",")
        cleaned = tuple(_canon(x) for x in items if str(x).strip())
        # de-dup while preserving order
        seen: set[str] = set()
        ordered: list[str] = []
        for x in cleaned:
            if x and x not in seen:
                seen.add(x)
                ordered.append(x)
        return tuple(ordered)

    env_val = os.environ.get("RUNTIME__PLUGINS__ALLOWLIST")
    if env_val is not None:
        return _split(env_val)

    if config is not None:
        try:
            rt = _get_nested(config, "runtime") or {}
            plugins_cfg = _get_nested(rt, "plugins") or {}
            cfg_val = _get_nested(plugins_cfg, "allowlist")
            return _split(cfg_val)
        except Exception as exc:
            logger.debug("plugin allowlist: config read error %s", exc)

    return ()


# ── Module-level singleton ────────────────────────────────────────────────────

_TOGGLES_SINGLETON: "ModuleToggles | None" = None


def get_toggles() -> "ModuleToggles":
    """Return the process-wide ModuleToggles singleton.

    Lazily constructed from `web.config.config` on first call. Falls back to
    defaults + env overrides if config cannot be loaded (fail-open for CLI/test).
    """
    global _TOGGLES_SINGLETON
    if _TOGGLES_SINGLETON is None:
        cfg: Any = None
        try:
            from web.config import config as _cfg
            cfg = _cfg
        except Exception as exc:
            logger.debug("get_toggles: web.config unavailable (%s), using env+defaults", exc)
        _TOGGLES_SINGLETON = ModuleToggles.from_config(cfg)
    return _TOGGLES_SINGLETON


def reset_toggles() -> None:
    """Clear the cached singleton — primarily for tests."""
    global _TOGGLES_SINGLETON
    _TOGGLES_SINGLETON = None
