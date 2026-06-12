/* ── Shared type definitions (matching actual backend schemas) ── */

// ── Project ──
export interface Project {
  id: string;
  org_id: string;
  name: string;
  description: string;
  status: string;
  owner_user_id: string;
  risk_level: string;
  start_at: string | null;
  due_at: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  deleted_by: string | null;
}

// ── Task ──
export interface Task {
  id: string;
  project_id: string | null;
  parent_task_id: string | null;
  title: string;
  description: string;
  status: string;
  priority: string;
  risk_level: string;
  assignee_type: string;
  assignee_id: string | null;
  creator_user_id: string | null;
  due_at: string | null;
  input_payload: Record<string, unknown>;
  output_payload: Record<string, unknown> | null;
  acceptance_criteria: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  deleted_by: string | null;
}

// ── Task Comment ──
export interface TaskComment {
  id: string;
  task_id: string;
  author_type: string; // human / agent / system
  author_id: string | null;
  content: string;
  created_at: string;
}

// ── Task Artifact ──
export interface TaskArtifact {
  id: string;
  task_id: string;
  name: string;
  artifact_type: string; // document / code / data / report / other
  storage_url: string;
  size_bytes: number;
  content_type: string;
  metadata: Record<string, unknown>;
  created_at: string;
}

// ── Task Evaluation ──
export interface TaskEvaluation {
  id: string;
  task_id: string;
  run_id: string | null;
  evaluator_type: string;
  score: number;
  category_scores: Record<string, number>;
  reasoning: string;
  evaluator_model: string;
  passed: boolean;
  evaluation_cost: number;
  created_at: string;
}

// ── Optimize Rerun Preview ──
export interface OptimizePreview {
  task_id: string;
  evaluation_id: string;
  original_description: string;
  original_acceptance_criteria: Record<string, unknown>;
  optimized_description: string;
  optimized_acceptance_criteria: Record<string, unknown>;
  rationale: string;
  improvements_addressed: string[];
}

// ── Digital Role (岗位模板) ──
export interface DigitalRole {
  id: string;
  org_id: string;
  name: string;
  role_type: string; // product_manager / architect / developer / qa_engineer / researcher / reviewer / ml_engineer / devops
  mission: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  permission_profile_id: string | null;
  model_profile_id: string | null;
  tool_profile_id: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

// ── Agent Instance (岗位实例) ──
export interface Agent {
  id: string;
  role_id: string;
  name: string;
  version: string;
  state: string;
  config: Record<string, unknown>;
  boot_config: Record<string, unknown> | null;
  autonomy_policy: Record<string, string> | null;
  timezone: string | null;
  working_hours: Record<string, string | null> | null;
  avatar_url: string | null;
  // Market fields
  listing_status: string;
  price_per_task: string | null;
  price_model: string;
  rating: number | null;
  completed_task_count: number;
  workflow_count?: number;
  acceptance_rate: number | null;
  provider_user_id: string | null;
  // Employment lifecycle (WorkDAO MVP)
  employment_status: string;
  hired_by_org_id: string | null;
  description: string | null;
  asset_ownership: string;
  monthly_salary: number | null;
  nda_signed: boolean;
  // Phase 2: AgentKit chain identity
  wallet_address: string | null;
  did: string | null;
  // Phase 5: Visa TAP
  tap_key_id: string | null;
  tap_certificate: string | null;
  // RFC 0002 §3.4.2 — per-coding-agent defaults (optional; non-null
  // only for AgentInstances bound to a coding_* DigitalRole).
  coding_config: CodingAgentConfig | null;
  created_at: string;
  updated_at: string;
}

// RFC 0002 §3.4.2 — JSON shape of AgentInstance.coding_config
// Mirrored client-side so the admin form is type-safe; backend
// parses defensively so unknown / missing keys are tolerated.
export interface CodingAgentConfig {
  default_model?: string | null;
  default_mode?: "plan" | "agent" | "yolo";
  per_run_budget_usd?: number | null;
  allowed_repos?: string[];
  allowed_tools?: string[];
  sandbox_preference?: "local" | "docker" | "system";
}

// ── Run ──
// G2 (Claude Code parity): one entry in an LLM-managed todo list. Mirrors
// the schema enforced server-side by ``app.services.runtime.agent_todo``.
export type AgentTodoStatus = "pending" | "in_progress" | "completed";

export interface AgentTodo {
  content: string;       // imperative form, e.g. "Run unit tests"
  status: AgentTodoStatus;
  activeForm: string;    // present continuous, e.g. "Running unit tests"
}

export interface AgentTodoState {
  todos: AgentTodo[];
  updated_at: string;    // ISO 8601 timestamp from the backend
}

export interface AgentRun {
  id: string;
  task_id: string;
  agent_instance_id: string;
  session_key: string;
  workflow_step: string;
  status: string;
  input_snapshot: Record<string, unknown>;
  output_snapshot: Record<string, unknown> | null;
  error_snapshot: Record<string, unknown> | null;
  // G2: ``null`` until the agent invokes ``agent_todo_set`` for the first
  // time. Updated live via the ``lifecycle:agent_todos_updated`` WS event.
  todo_state: AgentTodoState | null;
  model_name: string;
  usage_prompt_tokens: number;
  usage_completion_tokens: number;
  started_at: string | null;
  ended_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface StreamEvent {
  id: string;
  run_id: string;
  seq: number;
  event_type: string;
  event_name: string;
  payload: Record<string, unknown>;
  detail: string;
  created_at: string;
}

// ── Approval ──
export interface ApprovalRequest {
  id: string;
  related_type: string;
  related_id: string;
  action_name: string;
  status: string;
  requested_by_type: string;
  requested_by_id: string;
  approver_user_id: string | null;
  policy_snapshot: Record<string, unknown>;
  reason: string | null;
  decided_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ApprovalAction {
  id: string;
  approval_id: string;
  approver_user_id: string;
  decision: string;
  comment: string;
  created_at: string;
  updated_at: string;
}

// ── Audit ──
export interface AuditEvent {
  id: string;
  org_id: string;
  project_id: string | null;
  task_id: string | null;
  run_id: string | null;
  actor_type: string;
  actor_id: string | null;
  event_type: string;
  event_name: string;
  summary: string;
  payload: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

// ── Knowledge ──
export interface KnowledgeDocument {
  id: string;
  org_id: string;
  scope_type: string;
  scope_id: string;
  title: string;
  source_type: string;
  status: string;
  chunk_count: number;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

// ── Skill ──
export interface Skill {
  id: string;
  org_id: string;
  name: string;
  slug: string;
  description: string;
  version: string;
  category: string;
  invocation_type: string;  // tool_augmented / cognitive
  source: string;           // builtin / huggingface / custom / clawhub
  content: string;
  resources: Record<string, unknown>;
  applicable_role_types: string[];
  is_builtin: boolean;
  is_active: boolean;
  is_callable: boolean;
  require_approval: boolean;
  inputs_schema: Record<string, unknown> | null;
  outputs_schema: Record<string, unknown> | null;
  // SkillBank visibility
  visibility: string;
  download_count: number;
  // Marketplace fields
  deliverables: Array<Record<string, unknown>> | null;
  pricing_model: string;
  price: number | null;
  // AutoSkill effectiveness metrics
  times_used: number;
  avg_task_score: number;
  last_used_at: string | null;
  effectiveness_score: number;
  created_at: string;
  updated_at: string;
}

export interface SkillRecommendation {
  skill_id: string;
  skill_name: string;
  skill_slug: string;
  skill_category: string;
  relevance_score: number;
  match_reason: string;
}

export interface SkillRecommendationResponse {
  task_id: string;
  items: SkillRecommendation[];
}

export interface SkillDraft {
  id: string;
  org_id: string;
  source_task_id: string | null;
  source_run_id: string | null;
  title: string;
  description: string;
  content: string;
  rationale: string;
  proposed_category: string;
  proposed_applicable_roles: string[];
  asset_type: string;
  confidence: number;
  source_eval_score: number;
  status: 'pending' | 'approved' | 'rejected' | 'merged';
  duplicate_of_skill_id: string | null;
  similarity_score: number | null;
  reviewed_at: string | null;
  reviewed_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface ToolStatus {
  tool_name: string;
  status: 'builtin' | 'auto_registered' | 'unknown' | 'no_mcp';
  server_id?: string;
  server_name?: string;
  server_url?: string;
  is_active: boolean;
}

export interface RoleSkill {
  role_id: string;
  skill_id: string;
  skill_name: string;
  skill_slug: string;
  skill_category: string;
  skill_description: string;
  priority: number;
}

// ── Channel Message ──
export interface ChannelMessage {
  id: string;
  project_id: string;
  sender_type: string; // agent / human / system
  sender_id: string | null;
  sender_name: string;
  message_type: string; // text / task_update / request
  content: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

// ── Agent Team ──
export interface AgentTeam {
  id: string;
  org_id: string;
  name: string;
  description: string | null;
  avatar_url: string | null;
  status: string;
  created_by: string | null;
  metadata: Record<string, unknown>;
  member_count: number;
  deployment_count: number;
  created_at: string;
  updated_at: string;
}

export interface AgentTeamDetail extends AgentTeam {
  members: AgentTeamMember[];
  deployments: AgentTeamDeployment[];
}

export interface AgentTeamMember {
  id: string;
  team_id: string;
  agent_id: string;
  role: string;
  agent_name: string | null;
  agent_state: string | null;
  role_type: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentTeamDeployment {
  id: string;
  team_id: string;
  project_id: string;
  deployed_by: string | null;
  status: string;
  project_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentTeamStats {
  team_id: string;
  total_tasks: number;
  completed_tasks: number;
  success_rate: number;
  active_projects: number;
  member_stats: MemberStat[];
}

export interface MemberStat {
  agent_id: string;
  agent_name: string | null;
  role: string;
  tasks_completed: number;
  tasks_failed: number;
}

// ── Workflow Profiles ──
export interface PermissionProfile {
  id: string;
  name: string;
  description: string;
  rules: Record<string, unknown>[];
  created_at: string;
  updated_at: string;
}

export interface ModelProfile {
  id: string;
  name: string;
  provider: string;
  model_name: string;
  temperature: number;
  max_tokens: number;
  timeout_seconds: number;
  supports_tools: boolean;
  supports_streaming: boolean;
  extra_config: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ToolProfile {
  id: string;
  name: string;
  description: string;
  allowed_tools: string[];
  denied_tools: string[];
  created_at: string;
  updated_at: string;
}

// ── Paginated response ──
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

// ── Coding Agent (RFC 0002) ──
export type CodingMode = "plan" | "agent" | "yolo";
export type CodingTerminalStatus = "succeeded" | "failed" | "cancelled";
export type CodingNonTerminalStatus =
  | "running"
  | "waiting_for_user"
  | "waiting_for_approval";
export type CodingSessionStatus =
  | CodingNonTerminalStatus
  | CodingTerminalStatus;

export interface CodingSession {
  id: string;
  agent_instance_id: string | null;
  workflow_node_execution_id: string | null;
  parent_session_id: string | null;
  title: string;
  mode: CodingMode | string;
  status: CodingSessionStatus | string;
  model_name: string;
  provider: string;
  last_seq: number;
  budget_cents: number | null;
  cost_cents: number;
  metadata: Record<string, unknown>;
  started_at: string | null;
  ended_at: string | null;
  is_deleted: boolean;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface CodingAgentEvent {
  seq: number;
  turn_seq: number;
  kind: string;
  payload: Record<string, unknown>;
  payload_truncated: boolean;
  timestamp: string;
}

export interface CodingAgentEventList {
  items: CodingAgentEvent[];
  after_seq: number;
  limit: number;
}

export interface CodingMessageDispatchResponse {
  session_id: string;
  task_id: string;
  status: "queued" | "running";
}

// ── Strategy Marketplace (MM1 Phase 0) ──────────────────────────────
//
// Mirrors the S14 ORM rows surfaced by the S15 HTTP gateway under
// `/api/v1/marketplace/*` and `/api/v1/employment/*`. All Decimal
// values arrive as JSON strings (FastAPI's default serialization) —
// keep them as `string` on the wire; convert with `Number()` or a
// `decimal.js` instance at the UI render site.
//
// See `docs/architecture/14a-strategy-marketplace-milestones.md` §MM1
// for the business semantics; the field-level rationale lives in
// `docs/implementation/sprints/Sprint-S14/plan.md`.

export type ListingStatus = "draft" | "active" | "paused" | "delisted";

export type EmploymentStatus = "pending" | "active" | "paused" | "terminated";

export type ReportStatus =
  | "pending"
  | "partial"
  | "signed"
  | "settled"
  | "disputed";

export type HighWaterMarkMethod = "rolling_no_decay" | "periodic_reset";

export interface StrategyListing {
  id: string;
  strategy_version_id: string;
  provider_user_id: string;
  fee_rate_management: string;
  fee_rate_performance: string;
  deposit_usd: string;
  status: ListingStatus;
  listing_signature: string | null;
  listing_signed_at: string | null;
  listing_meta: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ProviderReputationSummary {
  total_employers: number;
  active_employers: number;
  cumulative_pnl_usd: string;
  total_performance_fees_usd: string;
  breach_count: number;
  avg_rating: string | null;
  last_active_at: string;
}

/**
 * A `StrategyListing` joined with the provider's reputation + the
 * strategy version's metadata. This is what the `/marketplace` list
 * endpoint returns — pre-joined so the card render doesn't N+1.
 */
export interface StrategyListingDetail extends StrategyListing {
  provider_reputation: ProviderReputationSummary | null;
  strategy_name: string;
  strategy_card: Record<string, unknown>;
  high_water_mark_method: HighWaterMarkMethod;
}

export type MarketplaceSortBy =
  | "newest"
  | "oldest"
  | "highest_deposit"
  | "lowest_deposit";

export interface MarketplaceSearchParams {
  sort?: MarketplaceSortBy;
  limit?: number;
  offset?: number;
}

export interface CreateListingRequest {
  strategy_version_id: string;
  fee_rate_management: string;
  fee_rate_performance: string;
  deposit_usd: string;
}

export interface EmploymentContract {
  id: string;
  employer_user_id: string;
  provider_user_id: string;
  strategy_version_id: string;
  position_cap_usd: string;
  stop_loss_pct: string;
  max_drawdown_pct: string;
  fee_rate_management: string;
  fee_rate_performance: string;
  period_seconds: number;
  status: EmploymentStatus;
  started_at: string | null;
  terminated_at: string | null;
  high_water_mark_usd: string;
  onchain_contract_address: string | null;
  escrow_address: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateEmploymentRequest {
  listing_id: string;
  position_cap_usd: string;
  stop_loss_pct: string;
  max_drawdown_pct: string;
  period_seconds: number;
}

export interface PerformanceReport {
  id: string;
  employment_contract_id: string;
  period_start: string;
  period_end: string;
  period_pnl_usd: string;
  cumulative_pnl_usd: string;
  high_water_mark_usd: string;
  performance_fee_usd: string;
  payload_hash: string;
  platform_signature: string | null;
  employer_signature: string | null;
  provider_signature: string | null;
  status: ReportStatus;
  payload_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface SettlementEvent {
  id: string;
  performance_report_id: string;
  employment_contract_id: string;
  performance_fee_usd: string;
  platform_cut_usd: string;
  provider_payout_usd: string;
  tx_hash: string | null;
  /** "off-chain" (MM1) | "base-sepolia" (MM2) | "base" (MM3+). */
  chain: string;
  settled_at: string;
  created_at: string;
  updated_at: string;
}

/**
 * `/employment/:id` returns the contract + its full history so the
 * detail page can render the Hero chart + ledger table in one call.
 */
export interface EmploymentDetail extends EmploymentContract {
  performance_reports: PerformanceReport[];
  settlement_events: SettlementEvent[];
  provider_reputation: ProviderReputationSummary | null;
  strategy_name: string;
}

export type EmploymentRole = "employer" | "provider";

// ── Strategy Marketplace PMF dashboard (S17 PR-2) ───────────────
//
// 6-metric snapshot from `/api/v1/internal/marketplace-pmf`. Decimal
// values arrive as JSON strings (FastAPI default for pydantic Decimal).

export interface MarketplacePmfResponse {
  weekly_active_strategies: number;
  employer_retention_w1: string;  // Decimal
  employer_retention_w2: string;
  employer_retention_w4: string;
  provider_retention_w4: string;
  average_period_pnl_usd: string;
  cumulative_performance_fees_usd: string;
  cumulative_platform_cut_usd: string;
  computed_at: string;  // ISO-8601 UTC
}
