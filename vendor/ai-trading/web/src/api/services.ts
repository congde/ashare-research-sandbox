import api from "./client";
import type {
  Project,
  Task,
  DigitalRole,
  Agent,
  CodingAgentConfig,
  AgentRun,
  StreamEvent,
  ApprovalRequest,
  ApprovalAction as LegacyApprovalAction,
  AuditEvent,
  KnowledgeDocument,
  Skill,
  SkillDraft,
  ToolStatus,
  RoleSkill,
  ChannelMessage,
  AgentTeam,
  AgentTeamDetail,
  AgentTeamMember,
  AgentTeamDeployment,
  AgentTeamStats,
  PermissionProfile,
  ModelProfile,
  ToolProfile,
  PaginatedResponse,
  SkillRecommendationResponse,
} from "../types";

// ── Projects ──
export const projectApi = {
  list: (params?: { show?: string; offset?: number; limit?: number }) =>
    api.get<PaginatedResponse<Project>>("/projects", { params }),
  get: (id: string) => api.get<Project>(`/projects/${id}`),
  create: (data: { name: string; description?: string; risk_level?: string; due_at?: string | null }) =>
    api.post<Project>("/projects", data),
  update: (id: string, data: Partial<Project>) => api.patch<Project>(`/projects/${id}`, data),
  activate: (id: string) => api.post<Project>(`/projects/${id}/activate`),
  complete: (id: string) => api.post<Project>(`/projects/${id}/complete`),
  reactivate: (id: string, reason: string) => api.post<Project>(`/projects/${id}/reactivate`, { reason }),
  pause: (id: string) => api.post<Project>(`/projects/${id}/pause`),
  archive: (id: string) => api.post<Project>(`/projects/${id}/archive`),
  unarchive: (id: string) => api.post<Project>(`/projects/${id}/unarchive`),
  delete: (id: string) => api.delete<Project>(`/projects/${id}`),
  restore: (id: string) => api.post<Project>(`/projects/${id}/restore`),
  getRecommendation: (id: string) => api.get(`/projects/${id}/recommend`),
  recommend: (id: string) => api.post(`/projects/${id}/recommend`, {}, { timeout: 120_000 }),
  applyRecommendation: (id: string, data: { tasks: Array<{ title: string; description?: string; priority?: string; suggested_role_type?: string | null; suggested_agent_id?: string | null; suggested_agent_name?: string | null; order?: number }>; team_id?: string | null }) =>
    api.post(`/projects/${id}/apply-recommendation`, data),
};

// ── Tasks ──
export const taskApi = {
  list: (projectId: string | undefined, params?: { assignee_id?: string; include_archived?: boolean; include_deleted?: boolean; status?: string; offset?: number; limit?: number }) =>
    api.get<PaginatedResponse<Task>>("/tasks", { params: { ...(projectId ? { project_id: projectId } : {}), ...params } }),
  get: (id: string) => api.get<Task>(`/tasks/${id}`),
  create: (data: {
    project_id: string;
    title: string;
    description?: string;
    priority?: string;
    risk_level?: string;
    assignee_type?: string;
    assignee_id?: string | null;
    parent_task_id?: string | null;
    due_at?: string | null;
    input_payload?: Record<string, unknown>;
    acceptance_criteria?: Record<string, unknown>;
    task_type?: string;
  }) => api.post<Task>("/tasks", data),
  update: (id: string, data: Partial<Task>) => api.patch<Task>(`/tasks/${id}`, data),
  assign: (id: string, data: { assignee_type: string; assignee_id: string }) =>
    api.post<Task>(`/tasks/${id}/assign`, data),
  run: (id: string) => api.post<Task>(`/tasks/${id}/run`),
  review: (id: string) => api.post<Task>(`/tasks/${id}/review`),
  approve: (id: string) => api.post<Task>(`/tasks/${id}/approve`),
  reject: (id: string) => api.post<Task>(`/tasks/${id}/reject`),
  takeover: (id: string) => api.post<Task>(`/tasks/${id}/takeover`),
  archive: (id: string) => api.post<Task>(`/tasks/${id}/archive`),
  cancel: (id: string, reason = "") => api.post<Task>(`/tasks/${id}/cancel`, { reason }),
  delete: (id: string) => api.delete<Task>(`/tasks/${id}`),
  restore: (id: string) => api.post<Task>(`/tasks/${id}/restore`),
  bulkArchive: (taskIds: string[]) => api.post("/tasks/bulk-archive", { task_ids: taskIds }),
  bulkDelete: (taskIds: string[]) => api.post("/tasks/bulk-delete", { task_ids: taskIds }),
  listComments: (id: string) => api.get<Array<import("../types").TaskComment>>(`/tasks/${id}/comments`),
  addComment: (id: string, content: string) => api.post(`/tasks/${id}/comments`, { content }),
  listArtifacts: (id: string) => api.get<Array<import("../types").TaskArtifact>>(`/tasks/${id}/artifacts`),
  backfillArtifacts: (id: string) => api.post(`/tasks/${id}/backfill-artifacts`),
  getMandate: (id: string) => api.get<{ task_id?: string; amount_limit?: number; amount_used?: number; expires_at?: string; status?: string }>(`/tasks/${id}/mandate`),
};

// ── Digital Roles (岗位模板) ──
export const roleApi = {
  list: () => api.get<PaginatedResponse<DigitalRole>>("/roles"),
  create: (data: { name: string; role_type: string; mission?: string; output_schema?: Record<string, unknown>; permission_profile_id?: string; model_profile_id?: string; tool_profile_id?: string }) =>
    api.post<DigitalRole>("/roles", data),
  update: (id: string, data: Partial<DigitalRole>) =>
    api.patch<DigitalRole>(`/roles/${id}`, data),
};

// ── Profiles (能力配置) ──
export const profileApi = {
  // Permission profiles
  listPermissions: () => api.get<PaginatedResponse<PermissionProfile>>("/profiles/permissions"),
  createPermission: (data: { name: string; description?: string; rules?: Record<string, unknown>[] }) =>
    api.post<PermissionProfile>("/profiles/permissions", data),
  updatePermission: (id: string, data: Partial<PermissionProfile>) =>
    api.patch<PermissionProfile>(`/profiles/permissions/${id}`, data),
  deletePermission: (id: string) => api.delete(`/profiles/permissions/${id}`),
  // Model profiles
  listModels: () => api.get<PaginatedResponse<ModelProfile>>("/profiles/models"),
  createModel: (data: { name: string; provider: string; model_name: string; temperature?: number; max_tokens?: number; timeout_seconds?: number }) =>
    api.post<ModelProfile>("/profiles/models", data),
  updateModel: (id: string, data: Partial<ModelProfile>) =>
    api.patch<ModelProfile>(`/profiles/models/${id}`, data),
  deleteModel: (id: string) => api.delete(`/profiles/models/${id}`),
  // Tool profiles
  listTools: () => api.get<PaginatedResponse<ToolProfile>>("/profiles/tools"),
  createTool: (data: { name: string; description?: string; allowed_tools?: string[]; denied_tools?: string[] }) =>
    api.post<ToolProfile>("/profiles/tools", data),
  updateTool: (id: string, data: Partial<ToolProfile>) =>
    api.patch<ToolProfile>(`/profiles/tools/${id}`, data),
  deleteTool: (id: string) => api.delete(`/profiles/tools/${id}`),
};

// ── Agents (岗位实例) ──
export const agentApi = {
  list: (params?: { role_id?: string; hired_by_org_id?: string; limit?: number } | string, limit?: number) => {
    // Backward compat: list(roleId, limit) or list({params})
    const p = typeof params === "string" ? { role_id: params, limit: limit ?? 50 } : { limit: 50, ...params };
    return api.get<PaginatedResponse<Agent>>("/agents", { params: p });
  },
  get: (id: string) => api.get<Agent>(`/agents/${id}`),
  register: (data: { role_id: string; name: string; version?: string; config?: Record<string, unknown>; boot_config?: Record<string, unknown> }) =>
    api.post<Agent>("/agents/register", data),
  update: (id: string, data: { name?: string; version?: string; boot_config?: Record<string, unknown>; autonomy_policy?: Record<string, string> | null; timezone?: string | null; working_hours?: Record<string, string | null> | null; avatar_url?: string; description?: string | null; listing_status?: string; coding_config?: CodingAgentConfig | null }) =>
    api.patch<Agent>(`/agents/${id}`, data),
  disable: (id: string) => api.post<Agent>(`/agents/${id}/disable`),
  enable: (id: string) => api.post<Agent>(`/agents/${id}/enable`),
  initWallet: (id: string) => api.post<Agent>(`/agents/${id}/init-wallet`),
  promote: (id: string) => api.post<Agent>(`/agents/${id}/promote`),
  demote: (id: string) => api.post<Agent>(`/agents/${id}/demote`),
  terminate: (id: string) => api.post<Agent>(`/agents/${id}/terminate`),
  listWorkflows: (id: string) => api.get<{ items: Array<{ workflow_id: string; name: string; status: string; latest_execution_status: string; task_ids?: string[] }>; total: number }>(`/agents/${id}/workflows`),
  testChat: (id: string, message: string, messages?: Array<{ role: string; content: string }>) =>
    api.post<{ reply: string }>(`/agents/${id}/test-chat`, messages ? { messages } : { message }),
  listEmployees: (params?: { limit?: number }) =>
    api.get<{ items: Agent[]; total: number }>("/agents/employees", { params }),
  // Agent memories
  listMemories: (id: string) =>
    api.get<{ episodic: Array<{ id: string; episode_type: string; title: string; content: string; importance: number; created_at: string | null }>; semantic: Array<{ id: string; category: string; title: string; content: string; created_at: string | null }> }>(`/agents/${id}/memories`),
  deleteMemory: (agentId: string, memoryId: string) =>
    api.delete(`/agents/${agentId}/memories/${memoryId}`),
};

// ── Runs ──
export const runApi = {
  create: (data: {
    task_id: string;
    agent_instance_id: string;
    workflow_step?: string;
    input_payload?: Record<string, unknown>;
    max_tokens?: number;
  }) => api.post<AgentRun>("/runs", data),
  get: (id: string) => api.get<AgentRun>(`/runs/${id}`),
  listByTask: (taskId: string) =>
    api.get<PaginatedResponse<AgentRun>>(`/tasks/${taskId}/runs`),
  cancel: (id: string, reason = "") =>
    api.post<AgentRun>(`/runs/${id}/cancel`, { reason }),
  events: (id: string, afterSeq = 0) =>
    api.get<PaginatedResponse<StreamEvent>>(`/runs/${id}/events`, { params: { after_seq: afterSeq } }),
};

// ── Approvals ──
export const approvalApi = {
  list: (status?: string) =>
    api.get<PaginatedResponse<ApprovalRequest>>("/approvals", { params: { status } }),
  get: (id: string) => api.get<ApprovalRequest>(`/approvals/${id}`),
  create: (data: Partial<ApprovalRequest>) => api.post<ApprovalRequest>("/approvals", data),
  decide: (id: string, data: { decision: string; comment?: string }) =>
    api.post<ApprovalRequest>(`/approvals/${id}/decide`, data),
  cancel: (id: string) => api.post<ApprovalRequest>(`/approvals/${id}/cancel`),
  actions: (id: string) => api.get<{ items: LegacyApprovalAction[] }>(`/approvals/${id}/actions`),
};

// ── Audit ──
export const auditApi = {
  timeline: (data: { task_id?: string; run_id?: string; project_id?: string }) =>
    api.post<PaginatedResponse<AuditEvent>>("/audit/timeline", data),
  listByProject: (projectId: string, offset = 0, limit = 50) =>
    api.get<PaginatedResponse<AuditEvent>>(`/audit/project/${projectId}`, { params: { offset, limit } }),
  get: (id: string) => api.get<AuditEvent>(`/audit/events/${id}`),
};

// ── Knowledge ──
export const knowledgeApi = {
  listDocs: (scopeType: string, scopeId?: string) =>
    api.get<PaginatedResponse<KnowledgeDocument>>("/knowledge/documents", {
      params: { scope_type: scopeType, scope_id: scopeId },
    }),
  getDoc: (id: string) => api.get<KnowledgeDocument>(`/knowledge/documents/${id}`),
  getChunks: (id: string) => api.get<{ items: { id: string; content: string; chunk_index: number }[] }>(`/knowledge/documents/${id}/chunks`),
  ingest: (data: { title: string; content: string; scope_type: string; scope_id: string; org_id: string; source_type?: "upload" | "url" | "generated" | "bad_case"; chunk_size?: number; chunk_overlap?: number }) =>
    api.post("/knowledge/ingest", data),
  search: (data: { query: string; scope_type: string; scope_id: string; org_id?: string; top_k?: number }) =>
    api.post("/knowledge/search", data),
  deleteDoc: (id: string) => api.delete(`/knowledge/documents/${id}`),
};

// ── Skills ──
export const skillApi = {
  list: (params?: { category?: string; invocation_type?: string; source?: string; role_type?: string; strict_role_type?: boolean; offset?: number; limit?: number }) =>
    api.get<PaginatedResponse<Skill>>("/skills", { params }),
  get: (id: string) => api.get<Skill>(`/skills/${id}`),
  create: (data: {
    name: string;
    slug: string;
    description?: string;
    category?: string;
    content?: string;
    resources?: Record<string, unknown>;
    applicable_role_types?: string[];
    deliverables?: Array<Record<string, unknown>>;
    pricing_model?: string;
    price?: number;
  }) => api.post<Skill>("/skills", data),
  update: (id: string, data: Partial<Skill>) => api.patch<Skill>(`/skills/${id}`, data),
  delete: (id: string) => api.delete(`/skills/${id}`),
  // Role-skill bindings
  listByRole: (roleId: string) =>
    api.get<{ items: RoleSkill[] }>(`/roles/${roleId}/skills`),
  bindToRole: (roleId: string, data: { skill_id: string; priority?: number }) =>
    api.post(`/roles/${roleId}/skills`, data),
  unbindFromRole: (roleId: string, skillId: string) =>
    api.delete(`/roles/${roleId}/skills/${skillId}`),
  importFromUrl: (data: { url: string; role_ids?: string[] }) =>
    api.post<Skill & { tool_statuses?: ToolStatus[] }>("/skill-import", data),
  // SkillDraft (AutoSkill Phase 2)
  listDrafts: (params?: { status?: string; offset?: number; limit?: number }) =>
    api.get<PaginatedResponse<SkillDraft>>("/skills/drafts", { params }),
  approveDraft: (id: string, data?: { name?: string; slug?: string; category?: string; applicable_role_types?: string[] }) =>
    api.post<Skill>(`/skills/drafts/${id}/approve`, data ?? {}),
  rejectDraft: (id: string) =>
    api.post<SkillDraft>(`/skills/drafts/${id}/reject`),
  mergeDraft: (id: string, targetSkillId: string) =>
    api.post<Skill>(`/skills/drafts/${id}/merge`, { target_skill_id: targetSkillId }),
  // SkillBank (Phase 2.5)
  publish: (id: string) => api.post<Skill>(`/skills/${id}/publish`),
  listMarket: (params?: { category?: string; source?: string; offset?: number; limit?: number }) =>
    api.get<PaginatedResponse<Skill>>("/skills/market", { params }),
  cloneFromMarket: (id: string) => api.post<Skill>(`/skills/market/${id}/clone`),
  // Skill detail: mounted agents & task performance
  listAgents: (id: string) =>
    api.get<Array<{ agent_id: string; agent_name: string; avatar_url: string | null; role_name: string }>>(`/skills/${id}/agents`),
  listTasks: (id: string, params?: { offset?: number; limit?: number; min_score?: number }) =>
    api.get<{ items: Array<{ task_id: string; task_name: string; workflow_name: string; employer_name: string; completed_at: string | null; score: number | null; feedback: string | null }>; total: number }>(`/skills/${id}/tasks`, { params }),
  // Phase 3: Skill recommendation
  getRecommended: (taskId: string) =>
    api.get<SkillRecommendationResponse>(`/tasks/${taskId}/recommended-skills`),
};

// ── Channel ──
export const channelApi = {
  list: (projectId: string, params?: { since_id?: string; message_type?: string; limit?: number }) =>
    api.get<PaginatedResponse<ChannelMessage>>(`/projects/${projectId}/channel`, { params }),
  post: (projectId: string, data: { content: string; message_type?: string; metadata?: Record<string, unknown> }) =>
    api.post<ChannelMessage>(`/projects/${projectId}/channel`, data),
  proposalAction: (projectId: string, data: { action: "approve" | "reject"; proposal: Record<string, unknown> }) =>
    api.post<{ status: string; result?: string }>(`/projects/${projectId}/channel/proposal-action`, data),
};

// ── Dashboard ──
export interface DashboardStats {
  project_count: number;
  active_task_count: number;
  active_agent_count: number;
  total_agent_count: number;
  pending_approval_count: number;
}

export interface ActivityItem {
  id: string;
  type: string;
  name: string;
  detail: string;
  time: string;
}

export const dashboardApi = {
  stats: () => api.get<DashboardStats>("/dashboard/stats"),
  activityFeed: (limit = 50) =>
    api.get<{ items: ActivityItem[] }>("/dashboard/activity-feed", { params: { limit } }),
};

// ── Teams ──
export const teamApi = {
  list: (offset = 0, limit = 50, status?: string) =>
    api.get<PaginatedResponse<AgentTeam>>("/teams", { params: { offset, limit, status } }),
  get: (id: string) => api.get<AgentTeamDetail>(`/teams/${id}`),
  create: (data: { name: string; description?: string; members?: { agent_id: string; role: string }[] }) =>
    api.post<AgentTeam>("/teams", data),
  update: (id: string, data: { name?: string; description?: string; avatar_url?: string }) =>
    api.put<AgentTeam>(`/teams/${id}`, data),
  archive: (id: string) => api.delete<AgentTeam>(`/teams/${id}`),
  // Members
  listMembers: (teamId: string) =>
    api.get<AgentTeamMember[]>(`/teams/${teamId}/members`),
  addMember: (teamId: string, data: { agent_id: string; role: string }) =>
    api.post<AgentTeamMember>(`/teams/${teamId}/members`, data),
  updateMemberRole: (teamId: string, agentId: string, data: { role: string }) =>
    api.patch<AgentTeamMember>(`/teams/${teamId}/members/${agentId}`, data),
  removeMember: (teamId: string, agentId: string) =>
    api.delete(`/teams/${teamId}/members/${agentId}`),
  // Deployments
  deploy: (teamId: string, projectId: string) =>
    api.post<AgentTeamDeployment>(`/teams/${teamId}/deploy/${projectId}`),
  withdraw: (teamId: string, projectId: string) =>
    api.delete(`/teams/${teamId}/deploy/${projectId}`),
  listProjects: (teamId: string) =>
    api.get<AgentTeamDeployment[]>(`/teams/${teamId}/projects`),
  // Stats
  stats: (teamId: string) => api.get<AgentTeamStats>(`/teams/${teamId}/stats`),
};

// ── Analytics ──
export interface DashboardCostSummary {
  cost_this_month: number;
  cost_last_month: number;
  cost_trend_7d: { date: string; cost: number }[];
  avg_quality_score: number | null;
  quality_pass_rate: number | null;
  top_agents: { agent_id: string; name: string; task_count: number; avg_score: number | null }[];
}

export interface AgentRanking {
  agent_id: string;
  name: string;
  role_type: string;
  total_tasks: number;
  done_count: number;
  success_rate: number;
  total_cost: number;
  cost_per_task: number;
  avg_quality_score: number | null;
  avg_duration_seconds: number | null;
}

export interface CostTrends {
  total_cost: number;
  period: string;
  trend: { date: string; cost: number }[];
  by_event_type: { event_type: string; cost: number; count: number }[];
  by_model: { model_name: string; cost: number; count: number; prompt_tokens: number; completion_tokens: number }[];
}

export const analyticsApi = {
  dashboardSummary: () => api.get<DashboardCostSummary>("/analytics/dashboard-summary"),
  agentRankings: (params?: { days?: number; project_id?: string; role_type?: string; offset?: number; limit?: number }) =>
    api.get<PaginatedResponse<AgentRanking>>("/analytics/agents", { params }),
  agentHistory: (agentId: string, days = 30) =>
    api.get<{ agent_id: string; cost_trend: { date: string; cost: number }[]; task_trend: { date: string; count: number }[] }>(
      `/analytics/agents/${agentId}/history`, { params: { days } },
    ),
  costTrends: (params?: { period?: string; days?: number; project_id?: string }) =>
    api.get<CostTrends>("/analytics/cost-trends", { params }),
  roi: (params?: { project_id?: string; days?: number }) =>
    api.get<{ total_estimated_value: number; total_actual_cost: number; roi: number; valued_task_count: number }>(
      "/analytics/roi", { params },
    ),
};

// ── Economics ──
export const economicsApi = {
  runCost: (runId: string) => api.get(`/economics/runs/${runId}/cost`),
  taskCost: (taskId: string) => api.get(`/economics/tasks/${taskId}/cost`),
  projectCost: (projectId: string, days = 30) =>
    api.get(`/economics/projects/${projectId}/cost`, { params: { days } }),
  agentCost: (agentId: string, days = 30) =>
    api.get(`/economics/agents/${agentId}/cost`, { params: { days } }),
  listBudgets: (params?: { scope_type?: string; offset?: number; limit?: number }) =>
    api.get("/economics/budgets", { params }),
  createBudget: (data: { scope_type: string; scope_id: string; budget_amount: number; period_type?: string; alert_threshold_pct?: number; hard_limit?: boolean }) =>
    api.post("/economics/budgets", data),
  deleteBudget: (budgetId: string) => api.delete(`/economics/budgets/${budgetId}`),
};

// ── Evaluations ──
export const evaluationApi = {
  evaluate: (taskId: string, force = false) =>
    api.post("/evaluations/evaluate", { task_id: taskId, force }, { timeout: 120_000 }),
  listByTask: (taskId: string, offset = 0, limit = 20) =>
    api.get(`/evaluations/tasks/${taskId}`, { params: { offset, limit } }),
  getLatest: (taskId: string) => api.get(`/evaluations/tasks/${taskId}/latest`),
  getCriteria: () => api.get("/evaluations/criteria"),
  optimizePreview: (taskId: string) =>
    api.post(`/tasks/${taskId}/optimize-rerun`, {}, { timeout: 120_000 }),
  applyOptimizeRerun: (taskId: string, data: { description: string; acceptance_criteria: Record<string, unknown> }) =>
    api.post(`/tasks/${taskId}/apply-optimize-rerun`, data, { timeout: 60_000 }),
};

// ── Task Valuation ──
export const valuationApi = {
  estimate: (taskId: string) => api.post(`/tasks/${taskId}/estimate-value`),
  roi: (taskId: string) => api.get(`/tasks/${taskId}/roi`),
};

// ── Feishu ──
export const feishuApi = {
  createGroup: (projectId: string, data?: { owner_open_id?: string; member_phones?: string[]; member_open_ids?: string[] }) =>
    api.post<{ chat_id: string; name: string }>(`/projects/${projectId}/feishu-group`, data || {}),
  unlinkGroup: (projectId: string) =>
    api.delete(`/projects/${projectId}/feishu-group`),
};

// ── MCP Tool Market ──
export interface MCPServer {
  id: string;
  name: string;
  url: string;
  description: string;
  transport: string;
  is_public: boolean;
  org_id: string | null;
  is_active: boolean;
  tag: string | null;
  cached_tools: { name: string; description: string }[] | null;
  auth_headers: Record<string, string> | null;
  last_refreshed_at: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export const mcpApi = {
  listServers: () => api.get<{ items: MCPServer[]; total: number }>("/mcp/servers"),
  createServer: (data: { name: string; url: string; description?: string; transport?: string; auth_headers?: Record<string, string> | null; is_public?: boolean }) =>
    api.post<MCPServer>("/mcp/servers", data),
  getServer: (id: string) => api.get<MCPServer>(`/mcp/servers/${id}`),
  updateServer: (id: string, data: Partial<{ name: string; url: string; description: string; transport: string; auth_headers: Record<string, string> | null; is_public: boolean }>) =>
    api.put<MCPServer>(`/mcp/servers/${id}`, data),
  refreshServer: (id: string) => api.post<MCPServer>(`/mcp/servers/${id}/refresh`),
  deleteServer: (id: string) => api.delete(`/mcp/servers/${id}`),
  installToAgent: (serverId: string, agentInstanceId: string) =>
    api.post(`/mcp/servers/${serverId}/install`, { agent_instance_id: agentInstanceId }),
  uninstallFromAgent: (serverId: string, agentInstanceId: string) =>
    api.delete(`/mcp/servers/${serverId}/install`, { data: { agent_instance_id: agentInstanceId } }),
  listAgentTools: (agentId: string) =>
    api.get<{ items: MCPServer[]; total: number }>(`/agents/${agentId}/mcp-tools`),
  configureTool: (data: { tool_name: string; has_mcp: boolean; name?: string; url?: string; transport?: string; description?: string }) =>
    api.post<{ status: string; tool_name: string; has_mcp: boolean; server_id: string | null }>("/mcp/tools/configure", data),
  syncCatalog: () => api.post<{ status: string; message: string }>("/mcp/sync-catalog"),
};

// ── Triggers ──
export interface AgentTrigger {
  id: string;
  agent_instance_id: string;
  name: string;
  trigger_type: string;
  config: Record<string, unknown>;
  action_type: string;
  action_payload: Record<string, unknown>;
  is_active: boolean;
  cooldown_seconds: number;
  max_fires: number | null;
  expires_at: string | null;
  fire_count: number;
  last_fired_at: string | null;
  created_at: string;
  updated_at: string;
}

export const triggerApi = {
  list: (agentId: string, activeOnly = false) =>
    api.get<{ items: AgentTrigger[]; total: number }>(`/agents/${agentId}/triggers`, { params: { active_only: activeOnly } }),
  create: (agentId: string, data: {
    name: string;
    trigger_type: string;
    config: Record<string, unknown>;
    action_type: string;
    action_payload: Record<string, unknown>;
    cooldown_seconds?: number;
    max_fires?: number | null;
    expires_at?: string | null;
  }) => api.post<AgentTrigger>(`/agents/${agentId}/triggers`, data),
  get: (triggerId: string) => api.get<AgentTrigger>(`/triggers/${triggerId}`),
  update: (triggerId: string, data: { name?: string; is_active?: boolean; cooldown_seconds?: number }) =>
    api.patch<AgentTrigger>(`/triggers/${triggerId}`, data),
  delete: (triggerId: string) => api.delete(`/triggers/${triggerId}`),
};

// ── Knowledge Plaza ──
export interface KnowledgePost {
  id: string;
  title: string;
  body: string;
  tags: string[] | null;
  visibility: string;
  agent_instance_id: string | null;
  agent_name: string;
  agent_role: string;
  org_id: string | null;
  project_id: string | null;
  source_task_id: string | null;
  created_at: string;
  updated_at: string;
}

export const knowledgePlazaApi = {
  list: (params?: { project_id?: string; agent_instance_id?: string; offset?: number; limit?: number }) =>
    api.get<{ items: KnowledgePost[]; total: number }>("/knowledge-posts", { params }),
  search: (q: string, params?: { project_id?: string; limit?: number }) =>
    api.get<{ items: KnowledgePost[]; total: number }>("/knowledge-posts/search", { params: { q, ...params } }),
  create: (data: { title: string; body: string; tags?: string[]; visibility?: string; project_id?: string }) =>
    api.post<KnowledgePost>("/knowledge-posts", data),
  get: (id: string) => api.get<KnowledgePost>(`/knowledge-posts/${id}`),
  delete: (id: string) => api.delete(`/knowledge-posts/${id}`),
};

// ── Contracts ──
export interface Contract {
  id: string;
  org_id: string;
  project_id: string;
  employer_user_id: string | null;
  agent_instance_id: string | null;
  title: string;
  scope: string | null;
  budget_amount: string;
  payment_terms: string;
  acceptance_criteria: string | null;
  status: string;
  due_at: string | null;
  signed_at: string | null;
  completed_at: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  // Joined display fields (populated by backend list/get endpoints)
  agent_name?: string | null;
  provider_user_id?: string | null;
  provider_username?: string | null;
  provider_display_name?: string | null;
}

export const contractApi = {
  list: (params?: { project_id?: string; workflow_id?: string; agent_instance_id?: string; status?: string; offset?: number; limit?: number }) =>
    api.get<PaginatedResponse<Contract>>("/contracts", { params }),
  get: (id: string) => api.get<Contract>(`/contracts/${id}`),
  create: (data: {
    project_id: string;
    agent_instance_id?: string | null;
    title: string;
    scope?: string;
    budget_amount?: string;
    payment_terms?: string;
    acceptance_criteria?: string;
    due_at?: string;
  }) => api.post<Contract>("/contracts", data),
  update: (id: string, data: Partial<Contract>) => api.patch<Contract>(`/contracts/${id}`, data),
  sign: (id: string) => api.post<Contract>(`/contracts/${id}/sign`),
  complete: (id: string) => api.post<Contract>(`/contracts/${id}/complete`),
  cancel: (id: string) => api.post<Contract>(`/contracts/${id}/cancel`),
};

// ── Wallet ──
export interface Wallet {
  id: string;
  owner_type: string;
  owner_id: string;
  balance: string;
  frozen_amount: string;
  total_earned: string;
  total_spent: string;
  currency: string;
  created_at: string;
  updated_at: string;
}

export interface WalletTransaction {
  id: string;
  wallet_id: string;
  tx_type: string;
  amount: string;
  balance_after: string;
  reference_type: string | null;
  reference_id: string | null;
  note: string | null;
  created_at: string;
  updated_at: string;
}

export interface Settlement {
  id: string;
  contract_id: string | null;
  task_id: string | null;
  agent_instance_id: string | null;
  amount: string;
  status: string;
  note: string | null;
  created_at: string;
  updated_at: string;
}

export interface OnchainSettlement {
  id: string;
  task_id: string | null;
  agent_instance_id: string | null;
  settlement_type: string;
  tx_hash: string | null;
  chain_id: number;
  from_address: string | null;
  to_address: string | null;
  amount_usdc: string;
  status: string;
  confirmed_at: string | null;
  created_at: string;
}

// ── Market ──
export interface MarketAgent {
  id: string;
  name: string;
  version: string;
  state: string;
  avatar_url: string | null;
  listing_status: string;
  price_per_task: string | null;
  price_model: string;
  rating: number | null;
  completed_task_count: number;
  acceptance_rate: number | null;
  description: string | null;
  boot_config: Record<string, unknown> | null;
  role_id: string;
  role_type: string | null;
  role_name: string | null;
  role_mission: string | null;
  // Phase 2/5: chain identity + TAP
  wallet_address: string | null;
  did: string | null;
  tap_key_id: string | null;
  tap_certificate: string | null;
  follower_count: number;
  is_followed: boolean;
  created_at: string;
  updated_at: string;
}

export const marketApi = {
  listAgents: (params?: { role_type?: string; min_rating?: number; max_price?: number; offset?: number; limit?: number }) =>
    api.get<PaginatedResponse<MarketAgent>>("/market/agents", { params }),
  getAgent: (id: string) => api.get<MarketAgent>(`/market/agents/${id}`),
  hire: (agentId: string, data: { project_id: string; budget_amount?: string; payment_terms?: string; acceptance_criteria?: string }) =>
    api.post<Contract>(`/market/agents/${agentId}/hire`, data),
  updateListing: (agentId: string, data: { listing_status?: string; price_per_task?: string; price_model?: string }) =>
    api.patch<MarketAgent>(`/market/agents/${agentId}/listing`, data),
  refreshStats: (agentId: string) => api.post<MarketAgent>(`/market/agents/${agentId}/refresh-stats`),
  follow: (agentId: string) => api.post(`/market/agents/${agentId}/follow`),
  unfollow: (agentId: string) => api.delete(`/market/agents/${agentId}/follow`),
  listFollowing: (params?: { offset?: number; limit?: number }) =>
    api.get<PaginatedResponse<MarketAgent>>("/market/agents/following", { params }),
};

// ── ValueScan market intelligence ──
export interface ValueScanEndpointInfo {
  key: string;
  path: string;
  label: string;
}

export interface ValueScanStatus {
  configured: boolean;
  base_url: string;
  endpoints: ValueScanEndpointInfo[];
  docs: Record<string, string>;
}

export interface ValueScanQueryRequest {
  path: string;
  payload?: Record<string, unknown>;
}

export interface ValueScanQueryResponse {
  path: string;
  data: Record<string, unknown>;
}

export const valueScanApi = {
  status: () => api.get<ValueScanStatus>("/valuescan/status"),
  query: (data: ValueScanQueryRequest) =>
    api.post<ValueScanQueryResponse>("/valuescan/query", data),
  queryEndpoint: (endpointKey: string, payload: Record<string, unknown>) =>
    api.post<ValueScanQueryResponse>(`/valuescan/endpoints/${endpointKey}`, payload),
};

// ── Research Agent (unified ValueScan + DexScan) ──
//
// Stage 2 of the integrations arc — `/api/v1/research/*` exposes a
// single namespace over both market-data integrations. Frontend
// consumers (the Research panel) reach for this API, NOT the
// per-source APIs above; those are kept for backward compatibility
// + admin-style direct probing.

export type ResearchSource = "vs" | "dex" | "mcp";

/**
 * Body-shape hint for the payload editor.
 *
 * `"dict"` — single JSON object (all ValueScan tools, plus most
 *            DexScan single-target tools).
 * `"coin_key"` — single `{chainName, tokenContractAddress}` object.
 * `"coin_key_list"` — array of `coin_key` objects (batch DexScan).
 * `"unknown"` — schema is still being discovered; the panel renders
 *               a "schema TBD" hint instead of a working seed.
 */
export type ResearchBodyShape =
  | "dict"
  | "coin_key"
  | "coin_key_list"
  | "mcp"
  | "unknown";

export interface ResearchToolInfo {
  qualified_key: string;
  source: ResearchSource;
  local_key: string;
  path: string;
  label: string;
  body_shape: ResearchBodyShape;
}

export interface ResearchCatalogueResponse {
  tools: ResearchToolInfo[];
  valuescan_configured: boolean;
  dexscan_configured: boolean;
  total: number;
}

/**
 * Payload for {@link researchApi.invoke}.
 *
 * `payload` accepts a dict OR a list — DexScan endpoints like
 * `dex.current_price` want a JSON array `ArrayList<ApiCoinKey>`;
 * most others want a dict. The Research panel's per-tool form
 * picks the right shape via the tool's metadata.
 */
export interface ResearchInvokeRequest {
  tool: string;
  payload?: Record<string, unknown> | unknown[];
}

export interface ResearchInvokeResponse {
  tool: string;
  source: ResearchSource;
  path: string;
  data: Record<string, unknown>;
}

export const researchApi = {
  catalogue: () => api.get<ResearchCatalogueResponse>("/research/catalogue"),
  invoke: (data: ResearchInvokeRequest) =>
    api.post<ResearchInvokeResponse>("/research/invoke", data),
};

// ── Research Stream (ValueScan SSE → WebSocket fan-out) ──
//
// The backend service `ResearchStreamFanout` (services/
// research_stream_fanout.py) bridges ValueScan SSE channels into
// our /ws WebSocket. This API surface lets the frontend start /
// stop subscriptions; the actual events arrive over WS in the
// existing `research-stream:*` rooms.

export interface ResearchStreamMetrics {
  events_received: number;
  events_published: number;
  reconnects: number;
  last_event_at: string | null;
  last_error: string | null;
}

export interface ResearchStreamSubscription {
  room_name: string;
  channel_path: string;
  query_params: Record<string, unknown> | null;
  running: boolean;
  metrics: ResearchStreamMetrics;
}

export interface ResearchStreamStartRequest {
  channel?: string;
  room_name?: string;
  query_params?: Record<string, unknown> | null;
}

export interface ResearchStreamStartResponse {
  room_name: string;
  channel_path: string;
  query_params: Record<string, unknown> | null;
  created: boolean;
  metrics: ResearchStreamMetrics;
}

export interface ResearchStreamStopRequest {
  room_name: string;
}

export interface ResearchStreamStopResponse {
  room_name: string;
  stopped: boolean;
}

export interface ResearchStreamListResponse {
  subscriptions: ResearchStreamSubscription[];
  total: number;
}

export const researchStreamApi = {
  start: (data: ResearchStreamStartRequest) =>
    api.post<ResearchStreamStartResponse>("/research/stream/start", data),
  stop: (data: ResearchStreamStopRequest) =>
    api.post<ResearchStreamStopResponse>("/research/stream/stop", data),
  list: () => api.get<ResearchStreamListResponse>("/research/stream/list"),
};

// ── Exchange accounts ──
export type ExchangeName = "binance" | "okx" | "bybit" | "coinbase" | "hyperliquid";

export interface ExchangeAccountResponse {
  id: string;
  user_id: string;
  exchange: ExchangeName;
  label: string;
  permissions: Record<string, boolean>;
  is_testnet: boolean;
  last_verified_at: string | null;
  fingerprint: string;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ExchangeAccountCreate {
  exchange: ExchangeName;
  label: string;
  api_key: string;
  api_secret: string;
  api_passphrase?: string | null;
  permissions?: Record<string, boolean>;
  is_testnet?: boolean;
}

export type ExchangeAccountUpdate = Partial<ExchangeAccountCreate>;

export const exchangeAccountApi = {
  list: (params?: { offset?: number; limit?: number }) =>
    api.get<PaginatedResponse<ExchangeAccountResponse>>("/exchange-accounts", { params }),
  get: (id: string) => api.get<ExchangeAccountResponse>(`/exchange-accounts/${id}`),
  create: (data: ExchangeAccountCreate) =>
    api.post<ExchangeAccountResponse>("/exchange-accounts", data),
  update: (id: string, data: ExchangeAccountUpdate) =>
    api.patch<ExchangeAccountResponse>(`/exchange-accounts/${id}`, data),
  remove: (id: string) => api.delete(`/exchange-accounts/${id}`),
};

// ── Backtests ──
export type BacktestState = "queued" | "running" | "done" | "failed";

export interface BacktestMetrics {
  total_trades?: number;
  win_rate?: number;
  pnl_pct?: number;
  pnl_abs?: string;
  sharpe?: number;
  sortino?: number;
  max_drawdown_pct?: number;
  final_equity?: string;
}

export interface BacktestResponse {
  id: string;
  strategy_version_id: string;
  state: BacktestState;
  symbol: string;
  timeframe: string;
  period_start: string;
  period_end: string;
  initial_capital: string;
  metrics: BacktestMetrics;
  trades_count: number;
  s3_report_url?: string | null;
  error_message?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface BacktestCreateRequest {
  symbol: string;
  timeframe?: string;
  strategy_version_id?: string | null;
  initial_capital?: string | null;
  limit?: number;
}

export const backtestApi = {
  list: (params?: { offset?: number; limit?: number }) =>
    api.get<PaginatedResponse<BacktestResponse>>("/backtests", { params }),
  get: (id: string) => api.get<BacktestResponse>(`/backtests/${id}`),
  create: (data: BacktestCreateRequest) =>
    api.post<BacktestResponse>("/backtests", data),
};

// ── Strategy Architect (S5 / S6) ──────────────────────────────
//
// Wraps the backend endpoints from PR #50 (generate) + S6's eventual
// multi-turn endpoints. v1 ships generate; multi-turn convo lands in
// a follow-up PR with the conversation-state-machine HTTP shell.

export interface GenerateStrategyRequest {
  prompt: string;
  symbol?: string;
  timeframe?: string;
}

export interface StrategyGenerationFinding {
  layer: "validator" | "lookahead";
  rule: string;
  line: number;
  col: number;
  message: string;
  suggestion?: string | null;
}

export interface StrategyAttemptSummary {
  iteration: number;
  extracted_code: string;
  findings: StrategyGenerationFinding[];
  input_tokens: number;
  output_tokens: number;
  model_used?: string;
  cost_usd?: number;
  cost_known?: boolean;
}

/** LLM-authored strategy card from the second generation pass (S6 schema). */
export interface StrategyCardData {
  name: string;
  thesis: string;
  valid_when: string[];
  invalid_when: string[];
  risk_checklist: string[];
  expected_metrics: Record<string, unknown>;
  symbol: string;
  timeframe: string;
  version: number;
}

export interface GenerateStrategyResponse {
  success: boolean;
  code: string;
  attempts: StrategyAttemptSummary[];
  elapsed_seconds: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_usd?: number;
  budget_usd?: number;
  budget_exhausted?: boolean;
  /** Best-effort card; null when the card pass failed (code still valid). */
  card?: StrategyCardData | null;
}

// ── Strategy persistence / library (PR: strategy-persistence-library) ──
//
// The generate endpoint above is stateless. These wrap the persistence
// surface that saves an accepted generation as a Strategy + first version
// and lists / fetches them for the strategy library.

export type StrategyStatus = "draft" | "dry_run" | "live" | "paused" | "stopped";

export interface SaveStrategyRequest {
  name: string;
  code: string;
  strategy_card?: Record<string, unknown>;
}

/** Headline metrics from a strategy's latest DONE backtest (list view only). */
export interface BacktestMetricsSummary {
  sharpe: number | null;
  pnl_pct: number | null;
  max_drawdown_pct: number | null;
  total_trades: number | null;
  ran_at: string | null;
}

export interface StrategyResponse {
  id: string;
  name: string;
  current_version: string;
  status: StrategyStatus;
  strategy_card: Record<string, unknown>;
  /** Source code — present on detail (GET /{id}) + just-saved; omitted in list. */
  code?: string | null;
  /** Latest successful backtest's metrics — present on the list view; null until backtested. */
  latest_backtest?: BacktestMetricsSummary | null;
  /** UUID of the current version — present on the list view; pass as strategy_version_id to backtest it. */
  current_version_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface StrategyListResponse {
  items: StrategyResponse[];
  total: number;
  offset: number;
  limit: number;
}

export const strategiesApi = {
  /** POST /strategies/generate — natural language → safe Python. */
  generate: (data: GenerateStrategyRequest) =>
    api.post<GenerateStrategyResponse>("/strategies/generate", data),
  /** POST /strategies — persist an accepted generation into the library. */
  save: (data: SaveStrategyRequest) => api.post<StrategyResponse>("/strategies", data),
  /** GET /strategies — list the user's saved strategies (metadata only). */
  list: (params?: { offset?: number; limit?: number }) =>
    api.get<StrategyListResponse>("/strategies", { params }),
  /** GET /strategies/{id} — one strategy + its latest version code. */
  get: (id: string) => api.get<StrategyResponse>(`/strategies/${id}`),
};

// ── Risk rules (read-only list — Risk Center reference table) ───

export type RiskScope = "global" | "account" | "strategy";
export type RiskRuleKind =
  | "max_position_pct"
  | "max_slippage_pct"
  | "max_daily_loss_pct"
  | "abnormal_orderbook"
  | "hard_daily_loss_pct";
export type RiskAction = "alert" | "propose" | "auto_halt";

export interface RiskRuleResponse {
  id: string;
  scope: RiskScope;
  scope_target_id?: string | null;
  kind: RiskRuleKind;
  threshold: Record<string, unknown>;
  action: RiskAction;
  active: boolean;
  created_at: string;
  updated_at: string;
}

export interface RiskRuleListResponse {
  items: RiskRuleResponse[];
  total: number;
  offset: number;
  limit: number;
}

// Threshold convention: the *_pct kinds carry { pct: N } in PERCENT units
// (15 = 15%); abnormal_orderbook is free-form. Backend currently accepts
// global scope only (account/strategy scoping deferred — see ADR-0019).
export interface RiskRuleCreate {
  kind: RiskRuleKind;
  threshold: Record<string, unknown>;
  action: RiskAction;
  scope?: RiskScope;
  scope_target_id?: string | null;
  active?: boolean;
}

// kind / scope are immutable post-creation; only these three are patchable.
export interface RiskRuleUpdate {
  threshold?: Record<string, unknown>;
  action?: RiskAction;
  active?: boolean;
}

export type RiskSeverity = "low" | "medium" | "high" | "critical";

export interface RiskEventResponse {
  id: string;
  risk_rule_id: string;
  strategy_run_id?: string | null;
  severity: RiskSeverity;
  trigger: string;
  context: Record<string, unknown>;
  explanation_llm?: string | null;
  acknowledged: boolean;
  created_at: string;
  updated_at: string;
}

export interface RiskEventListResponse {
  items: RiskEventResponse[];
  total: number;
  offset: number;
  limit: number;
}

export const riskApi = {
  /** GET /risk-rules — list the user's configured risk rules. */
  list: (params?: { offset?: number; limit?: number }) =>
    api.get<RiskRuleListResponse>("/risk-rules", { params }),
  /** GET /risk-events — list the user's fired risk events (运行事件 feed). */
  listEvents: (params?: { offset?: number; limit?: number }) =>
    api.get<RiskEventListResponse>("/risk-events", { params }),
  /** POST /risk-rules — create a rule owned by the caller (global scope). */
  create: (data: RiskRuleCreate) => api.post<RiskRuleResponse>("/risk-rules", data),
  /** PATCH /risk-rules/{id} — update threshold / action / active. */
  update: (id: string, data: RiskRuleUpdate) =>
    api.patch<RiskRuleResponse>(`/risk-rules/${id}`, data),
  /** DELETE /risk-rules/{id} — soft deactivate (active=false; preserves audit). */
  remove: (id: string) => api.delete<RiskRuleResponse>(`/risk-rules/${id}`),
};

// ── Strategy runtime (S7-5 / PR #57 + S8 approvals / PR #60) ─────

export type RunnerState =
  | "created"
  | "starting"
  | "running"
  | "stopping"
  | "stopped"
  | "failed";

export interface StartRuntimeRequest {
  symbol?: string;
  timeframe?: string;
  qty?: number | string;
  initial_capital?: number | string;
  candles?: number;
  max_position_usd?: number | string | null;
  max_drawdown_pct?: number | string | null;
}

export interface StartRuntimeResponse {
  run_id: string;
  state: RunnerState;
  started_at: string | null;
  symbol: string;
  timeframe: string;
}

export interface RuntimeHealthResponse {
  run_id: string;
  state: RunnerState;
  started_at: string | null;
  last_event_at: string | null;
  last_error: string | null;
  restart_count: number;
  candles_processed: number;
  intents_emitted: number;
  fills: number;
  rejected: number;
  equity: string;
  kill_switch_tripped: boolean;
}

export interface ListRuntimeResponse {
  run_ids: string[];
  count: number;
}

export interface KillSwitchRequest {
  reason: string;
}

export interface KillSwitchResponse {
  run_id: string;
  tripped: boolean;
  tripped_reason: string;
}

export type ApprovalAction = "deploy_live" | "change_threshold" | "halt_all";

export type ApprovalState =
  | "pending"
  | "approved"
  | "rejected"
  | "expired"
  | "executed"
  | "execution_failed";

export interface CreateApprovalRequest {
  action: ApprovalAction;
  reason: string;
  payload?: Record<string, unknown>;
}

export interface ApprovalResponse {
  request_id: string;
  action: ApprovalAction;
  target: string;
  requested_by: string;
  reason: string;
  state: ApprovalState;
  created_at: string;
  expires_at: string;
  payload: Record<string, unknown>;
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string;
  execution_error: string | null;
}

export interface DecisionRequest {
  note?: string;
}

export interface ListApprovalsResponse {
  approvals: ApprovalResponse[];
  count: number;
}

export const strategiesRuntimeApi = {
  start: (data: StartRuntimeRequest) =>
    api.post<StartRuntimeResponse>("/strategies/runtime/start", data),
  list: () => api.get<ListRuntimeResponse>("/strategies/runtime"),
  health: (runId: string) =>
    api.get<RuntimeHealthResponse>(`/strategies/runtime/${runId}/health`),
  stop: (runId: string, timeoutSeconds = 5.0) =>
    api.post<{ run_id: string; state: RunnerState }>(
      `/strategies/runtime/${runId}/stop`,
      { timeout_seconds: timeoutSeconds },
    ),
  tripKillSwitch: (runId: string, data: KillSwitchRequest) =>
    api.post<KillSwitchResponse>(
      `/strategies/runtime/${runId}/risk/kill-switch`,
      data,
    ),

  // Approval gate (PR #60)
  createApproval: (runId: string, data: CreateApprovalRequest) =>
    api.post<ApprovalResponse>(
      `/strategies/runtime/${runId}/approvals`,
      data,
    ),
  listApprovals: () =>
    api.get<ListApprovalsResponse>("/strategies/runtime/approvals"),
  getApproval: (requestId: string) =>
    api.get<ApprovalResponse>(`/strategies/runtime/approvals/${requestId}`),
  approve: (requestId: string, data: DecisionRequest = {}) =>
    api.post<ApprovalResponse>(
      `/strategies/runtime/approvals/${requestId}/approve`,
      data,
    ),
  reject: (requestId: string, data: DecisionRequest = {}) =>
    api.post<ApprovalResponse>(
      `/strategies/runtime/approvals/${requestId}/reject`,
      data,
    ),
};

export interface OnchainAddress {
  wallet_address: string | null;
  payout_method: string;
  usdc_balance: string | null;
  balance_pending?: boolean;
}

export const walletApi = {
  get: () => api.get<Wallet>("/wallet"),
  deposit: (amount: string, note?: string) => api.post<Wallet>("/wallet/deposit", { amount, note }),
  withdraw: (amount: string, note?: string) => api.post<Wallet>("/wallet/withdraw", { amount, note }),
  listTransactions: (params?: { offset?: number; limit?: number }) =>
    api.get<PaginatedResponse<WalletTransaction>>("/wallet/transactions", { params }),
  getEscrow: (contractId: string) => api.get("/wallet/escrow/" + contractId),
  listSettlements: (params?: { agent_instance_id?: string; contract_id?: string; offset?: number; limit?: number }) =>
    api.get<PaginatedResponse<Settlement>>("/wallet/settlements", { params }),
  listOnchainSettlements: (params?: { agent_instance_id?: string; task_id?: string; offset?: number; limit?: number }) =>
    api.get<PaginatedResponse<OnchainSettlement>>("/wallet/onchain-settlements", { params }),
  getOnchainAddress: (refreshBalance = false) =>
    api.get<OnchainAddress>("/wallet/onchain-address", { params: refreshBalance ? { refresh_balance: true } : undefined }),
  generateOnchainAddress: () => api.post<OnchainAddress>("/wallet/generate-onchain-address"),
  updatePayoutMethod: (payout_method: "credits" | "onchain") =>
    api.patch<OnchainAddress>("/wallet/payout-method", { payout_method }),
};

// ── Payment methods (收款方式) ──
export type PaymentMethodType = "alipay" | "wechat" | "bank_card";

export interface PaymentMethodResponse {
  id: string;
  method_type: PaymentMethodType;
  account: string; // masked on read
  holder_name: string;
  is_default: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface PaymentMethodCreateRequest {
  method_type: PaymentMethodType;
  account: string;
  holder_name: string;
}

export interface PaymentMethodListResponse {
  items: PaymentMethodResponse[];
  total: number;
}

export const paymentMethodApi = {
  list: () => api.get<PaymentMethodListResponse>("/payment-methods"),
  create: (data: PaymentMethodCreateRequest) =>
    api.post<PaymentMethodResponse>("/payment-methods", data),
  remove: (id: string) => api.delete(`/payment-methods/${id}`),
};

export interface UserProfile {
  id: string;
  org_id: string | null;
  username: string;
  email: string;
  display_name: string;
  roles: string[];
  is_active: boolean;
  active_role: string;
  created_at: string;
  updated_at: string;
}

export const userApi = {
  me: () => api.get<UserProfile>("/users/me"),
  list: (params?: { offset?: number; limit?: number }) =>
    api.get<PaginatedResponse<UserProfile>>("/users", { params }),
  updateRoles: (userId: string, roles: string[]) =>
    api.patch<UserProfile>(`/users/${userId}/roles`, { roles }),
};

export interface ApiKeyRecord {
  id: string;
  name: string;
  description?: string;
  is_active: boolean;
  rate_limit_rpm?: number;
  expires_at?: string;
  created_at: string;
  key_prefix: string;
  key?: string; // only returned on create
}

export const apiKeyApi = {
  list: () => api.get<{ items: ApiKeyRecord[]; total: number }>("/a2a/api-keys"),
  create: (data: { name: string; description?: string; rate_limit_rpm?: number }) =>
    api.post<ApiKeyRecord>("/a2a/api-keys", data),
  update: (id: string, data: { name?: string; description?: string; is_active?: boolean; rate_limit_rpm?: number }) =>
    api.patch<ApiKeyRecord>(`/a2a/api-keys/${id}`, data),
  delete: (id: string) => api.delete(`/a2a/api-keys/${id}`),
};

// ── Platform Assistant (Johnny) ──
export interface AssistantMessage {
  content: string;
  tool_calls_made: string[];
}

export interface AssistantHistoryMessage {
  role: string;
  content: string;
}

export interface AssistantConfig {
  personality: string;
  model: string | null;
  temperature: number;
  role_tools: Record<string, string[]>;
}

// ── Organizations ──
export const organizationApi = {
  list: () => api.get("/organizations"),
  create: (data: Record<string, unknown>) => api.post("/organizations", data),
  get: (id: string) => api.get(`/organizations/${id}`),
  update: (id: string, data: Record<string, unknown>) => api.patch(`/organizations/${id}`, data),
  listMembers: (id: string) => api.get(`/organizations/${id}/members`),
  join: (id: string) => api.post(`/organizations/${id}/join`),
  approveMember: (orgId: string, membershipId: string) =>
    api.post(`/organizations/${orgId}/members/${membershipId}/approve`),
  leave: (orgId: string) => api.post(`/organizations/${orgId}/leave`),
  myInvitations: () => api.get("/organizations/my-invitations"),
  acceptInvite: (orgId: string, membershipId: string) =>
    api.post(`/organizations/${orgId}/members/${membershipId}/accept`),
  rejectInvite: (orgId: string, membershipId: string) =>
    api.post(`/organizations/${orgId}/members/${membershipId}/reject`),
};

// ── Workflows ──
export const workflowApi = {
  list: (params?: { status?: string; org_id?: string; trigger_type?: string; created_after?: string; created_before?: string }) => api.get("/workflows", { params }),
  create: (data: Record<string, unknown>) => api.post("/workflows", data),
  get: (id: string) => api.get(`/workflows/${id}`),
  update: (id: string, data: Record<string, unknown>) => api.patch(`/workflows/${id}`, data),
  delete: (id: string) => api.delete(`/workflows/${id}`),
  execute: (id: string, mode?: string, body?: { file_inputs?: Record<string, Array<{ name: string; content: string }>> }) =>
    api.post(`/workflows/${id}/execute`, body ?? null, { params: mode ? { mode } : undefined }),
  listExecutions: (id: string) => api.get(`/workflows/${id}/executions`),
  aiGenerate: (data: { workflow_name: string; workflow_description?: string; org_id?: string; reference_docs?: string[] }) =>
    api.post("/workflows/ai-generate", data),
  // Deliverable review chain
  submitDeliverable: (execId: string, nodeExecId: string, data: { content: string; files?: string[] }) =>
    api.post(`/workflows/executions/${execId}/nodes/${nodeExecId}/submit-deliverable`, data),
  ownerReview: (execId: string, nodeExecId: string, data: { action: "approve" | "reject"; comment?: string }) =>
    api.post(`/workflows/executions/${execId}/nodes/${nodeExecId}/owner-review`, data),
  employerReview: (execId: string, nodeExecId: string, data: { action: "approve" | "reject"; comment?: string }) =>
    api.post(`/workflows/executions/${execId}/nodes/${nodeExecId}/employer-review`, data),
  getNodeReviewStatus: (execId: string, nodeExecId: string) =>
    api.get(`/workflows/executions/${execId}/nodes/${nodeExecId}/review-status`),
  getExecutionStatusSummary: (execId: string) =>
    api.get(`/workflows/executions/${execId}/status-summary`),
  getNodeStatuses: (execId: string) =>
    api.get<{ nodes: Array<{ node_id: string; status: string; review_status?: string; has_deliverable?: boolean; started_at: string | null; completed_at: string | null }> }>(
      `/workflows/executions/${execId}/node-statuses`
    ),
  cancelExecution: (workflowId: string, execId: string) =>
    api.post(`/workflows/${workflowId}/executions/${execId}/cancel`),
  advanceExecution: (execId: string) =>
    api.post(`/workflows/executions/${execId}/advance`),
  restartWorkflow: (workflowId: string, mode?: string) =>
    api.post(`/workflows/${workflowId}/restart`, null, { params: { mode: mode || "auto" } }),
  retryNodeExecution: (execId: string, nodeExecId: string) =>
    api.post(`/workflows/executions/${execId}/nodes/${nodeExecId}/retry`),
  resumeFromNode: (execId: string, nodeId: string) =>
    api.post(`/workflows/executions/${execId}/nodes/${nodeId}/resume`),
  resumeExecution: (workflowId: string, execId: string) =>
    api.post(`/workflows/${workflowId}/executions/${execId}/resume`),
};

// ── Marketplace ──
export const marketplaceApi = {
  // Skills
  listSkills: (params?: { category?: string }) => api.get("/marketplace/skills", { params }),
  purchaseSkill: (id: string) => api.post(`/marketplace/skills/${id}/purchase`),
  purchasedSkills: () => api.get("/marketplace/skills/purchased"),
  // Models
  listModels: () => api.get("/marketplace/models"),
  subscribeModel: (id: string) => api.post(`/marketplace/models/${id}/subscribe`),
  subscribedModels: () => api.get("/marketplace/models/subscribed"),
  // Tools
  listTools: () => api.get("/marketplace/tools"),
  purchaseTool: (id: string) => api.post(`/marketplace/tools/${id}/purchase`),
  purchasedTools: () => api.get("/marketplace/tools/purchased"),
  // Knowledge
  listKnowledge: () => api.get("/marketplace/knowledge"),
  purchaseKnowledge: (id: string) => api.post(`/marketplace/knowledge/${id}/purchase`),
  purchasedKnowledge: () => api.get("/marketplace/knowledge/purchased"),
};

export const resourceApi = {
  list: (params?: { category?: string; source_type?: string }) => api.get("/resources", { params }),
  create: (data: Record<string, unknown>) => api.post("/resources", data),
  get: (id: string) => api.get(`/resources/${id}`),
  update: (id: string, data: { title?: string; description?: string; category?: string; source_type?: string; visibility?: string }) =>
    api.patch(`/resources/${id}`, data),
  listAccess: (id: string) => api.get(`/resources/${id}/access`),
  delete: (id: string) => api.delete(`/resources/${id}`),
};

export const assistantApi = {
  chat: (message: string) =>
    api.post<AssistantMessage>("/assistant/chat", { message }),
  history: (params?: { limit?: number; offset?: number }) =>
    api.get<{ messages: AssistantHistoryMessage[] }>("/assistant/history", { params }),
  clearHistory: () => api.delete("/assistant/history"),
  getAgent: () => api.get<Record<string, unknown>>("/assistant/agent"),
  getAgentCard: () => api.get<Record<string, unknown>>("/assistant/agent-card"),
  getConfig: () => api.get<AssistantConfig>("/assistant/config"),
  updateConfig: (data: Partial<AssistantConfig>) =>
    api.patch<AssistantConfig>("/assistant/config", data),
};

// ── Coding Agent (RFC 0002) ──
import type {
  CodingAgentEventList,
  CodingMessageDispatchResponse,
  CodingMode,
  CodingNonTerminalStatus,
  CodingSession,
  CodingSessionStatus,
  CodingTerminalStatus,
} from "../types";

export interface CreateCodingSessionPayload {
  title?: string;
  mode?: CodingMode;
  model_name?: string;
  provider?: string;
  budget_cents?: number | null;
  agent_instance_id?: string | null;
  workflow_node_execution_id?: string | null;
  metadata?: Record<string, unknown>;
}

export const codingAgentApi = {
  list: (params?: {
    status?: CodingSessionStatus;
    include_deleted?: boolean;
    offset?: number;
    limit?: number;
  }) =>
    api.get<PaginatedResponse<CodingSession>>("/coding/sessions", { params }),
  get: (id: string) => api.get<CodingSession>(`/coding/sessions/${id}`),
  create: (data: CreateCodingSessionPayload) =>
    api.post<CodingSession>("/coding/sessions", data),
  delete: (id: string) => api.delete(`/coding/sessions/${id}`),
  resume: (id: string) =>
    api.post<CodingSession>(`/coding/sessions/${id}/resume`),
  fork: (id: string, data: { title?: string; mode?: CodingMode; metadata?: Record<string, unknown> }) =>
    api.post<CodingSession>(`/coding/sessions/${id}/fork`, data),
  updateStatus: (id: string, status: CodingNonTerminalStatus) =>
    api.patch<CodingSession>(`/coding/sessions/${id}/status`, { status }),
  terminate: (id: string, status: CodingTerminalStatus) =>
    api.post<CodingSession>(`/coding/sessions/${id}/terminate`, { status }),
  postMessage: (id: string, data: { text: string; max_turns?: number }) =>
    api.post<CodingMessageDispatchResponse>(
      `/coding/sessions/${id}/messages`,
      data,
    ),
  listEvents: (
    id: string,
    params?: { after_seq?: number; limit?: number },
  ) => api.get<CodingAgentEventList>(`/coding/sessions/${id}/events`, { params }),
  submitToolApproval: (
    id: string,
    data: { tool_call_id: string; decision: "approve" | "reject"; comment?: string },
  ) =>
    api.post<{
      session_id: string;
      tool_call_id: string;
      decision: "approve" | "reject";
      seq: number;
      decided_at: string;
    }>(`/coding/sessions/${id}/tool-approval`, data),
  submitUserAnswer: (
    id: string,
    data: { question_id: string; answer: string },
  ) =>
    api.post<{
      session_id: string;
      question_id: string;
      answer: string;
      seq: number;
      answered_at: string;
    }>(`/coding/sessions/${id}/answer`, data),
};

// ── RFC0007 Coordination (read-only catalogs/health/quota) ──

export type TradeOffLevel = "low" | "medium" | "high";
export type CoordinationPatternId =
  | "orchestrator_subagent"
  | "agent_teams"
  | "generator_verifier"
  | "shared_state"
  | "message_bus";

export type HealthBand = "healthy" | "degraded" | "unhealthy" | "unknown";

export interface PatternTradeOffs {
  cost: TradeOffLevel;
  latency: TradeOffLevel;
  parallelism: TradeOffLevel;
  debuggability: TradeOffLevel;
  robustness: TradeOffLevel;
}

export interface CoordinationPatternEntry {
  id: CoordinationPatternId;
  display_name: { en: string; zh: string } | string;
  one_liner: { en: string; zh: string } | string;
  when_to_use: string[];
  anti_patterns: string[];
  trade_offs: PatternTradeOffs;
  example_brief: { en: string; zh: string } | string;
  docs_url: string;
  related_patterns: CoordinationPatternId[];
}

export interface PatternHealthSnapshot {
  pattern: CoordinationPatternId;
  sample_count: number;
  success_rate: number;
  avg_cost_usd_cents: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
  freshness_score: number;
  band: HealthBand;
}

export interface PatternSelectPreviewResponse {
  pattern: CoordinationPatternId;
  confidence: number;
  reasoning: string;
  profile: {
    work_item_count: number;
    quality_critical: boolean;
    long_running_minutes: number;
    parallel_specialists: number;
    needs_consensus: boolean;
    has_event_stream: boolean;
    requires_shared_state: boolean;
  };
}

export interface QuotaStatsResponse {
  stats: {
    user_today_pct: number;
    org_today_pct: number;
    global_inflight_pct: number;
    nearest_cap: string | null;
    nearest_cap_pct: number;
  };
  health: "ok" | "warn" | "alert";
  config: {
    per_user_daily: number;
    per_org_daily: number;
    global_concurrent: number;
  };
  next_spawn: {
    allowed: boolean;
    blocking_scope: string | null;
    reason: string;
  };
}

export const coordinationApi = {
  listPatterns: (locale?: "en" | "zh") =>
    api.get<{ items: CoordinationPatternEntry[]; count: number }>(
      "/coordination/patterns",
      { params: locale ? { locale } : undefined },
    ),
  getPattern: (id: CoordinationPatternId) =>
    api.get<CoordinationPatternEntry>(`/coordination/patterns/${id}`),
  previewSelection: (data: {
    brief: string;
    config?: Record<string, unknown>;
  }) =>
    api.post<PatternSelectPreviewResponse>(
      "/coordination/patterns/select-preview",
      data,
    ),
  listTools: () =>
    api.get<{ items: unknown[]; count: number; names: string[] }>(
      "/coordination/tools",
    ),
  getHealth: () =>
    api.get<{
      items: PatternHealthSnapshot[];
      count: number;
      config: {
        min_samples: number;
        degraded_success_rate: number;
        unhealthy_success_rate: number;
        freshness_window_hours: number;
      };
    }>("/coordination/health"),
  getQuota: (params?: {
    user_today?: number;
    org_today?: number;
    global_inflight?: number;
  }) =>
    api.get<QuotaStatsResponse>("/coordination/quota", { params }),
  getAnomalyThresholds: () =>
    api.get<{
      spawn_in_run_pct: number;
      run_in_workflow_pct: number;
      workflow_in_org_pct: number;
    }>("/coordination/anomaly-thresholds"),
  getRunTraceTree: (runId: string) =>
    api.get<TraceTreeResponse>(
      `/coordination/runs/${runId}/tree`,
    ),
  listRunInboxes: (runId: string, limit = 100) =>
    api.get<RunInboxesResponse>(
      `/coordination/runs/${runId}/inboxes`,
      { params: { limit } },
    ),
  peekRunAgentInbox: (runId: string, agentId: string, limit = 50) =>
    api.get<InboxPeekResponse>(
      `/coordination/runs/${runId}/inboxes/${agentId}`,
      { params: { limit } },
    ),
  listRunScratchpads: (runId: string, limit = 100) =>
    api.get<RunScratchpadsResponse>(
      `/coordination/runs/${runId}/scratchpad`,
      { params: { limit } },
    ),
  peekRunScratchpad: (runId: string, namespace: string, limit = 200) =>
    api.get<ScratchpadPeekResponse>(
      `/coordination/runs/${runId}/scratchpad/${namespace}`,
      { params: { limit } },
    ),
  listBusTopics: (orgId?: string) =>
    api.get<BusTopicsResponse>(
      "/coordination/topics",
      { params: orgId ? { org_id: orgId } : undefined },
    ),
  peekBusTopic: (topic: string, orgId?: string, limit = 50) =>
    api.get<TopicPeekResponse>(
      `/coordination/topics/${topic}`,
      { params: { ...(orgId ? { org_id: orgId } : {}), limit } },
    ),
  // ── RFC 0007 Slice D10 — Bulk operator ops ──
  // Two-phase: omit `confirm` (or pass false) for the read-only
  // assessment; pass `confirm: true` to actually destroy.
  killRunTree: (runId: string, opts?: { confirm?: boolean; reason?: string }) =>
    api.post<KillTreeResponse>(
      `/coordination/runs/${runId}/kill-tree`,
      undefined,
      {
        params: {
          ...(opts?.confirm ? { confirm: true } : {}),
          ...(opts?.reason ? { reason: opts.reason } : {}),
        },
      },
    ),
  drainBusTopic: (
    topic: string,
    opts?: { orgId?: string; confirm?: boolean; reason?: string },
  ) =>
    api.post<DrainTopicResponse>(
      `/coordination/topics/${topic}/drain`,
      undefined,
      {
        params: {
          ...(opts?.orgId ? { org_id: opts.orgId } : {}),
          ...(opts?.confirm ? { confirm: true } : {}),
          ...(opts?.reason ? { reason: opts.reason } : {}),
        },
      },
    ),
  resetAgentInbox: (
    runId: string,
    agentId: string,
    opts?: { confirm?: boolean; reason?: string },
  ) =>
    api.post<ResetInboxResponse>(
      `/coordination/runs/${runId}/inbox/${agentId}/reset`,
      undefined,
      {
        params: {
          ...(opts?.confirm ? { confirm: true } : {}),
          ...(opts?.reason ? { reason: opts.reason } : {}),
        },
      },
    ),
};

// ── RFC 0007 Slice D10 — Bulk operator op DTOs ───────────────

/** Response from POST /coordination/runs/{run_id}/kill-tree.
 *
 * The same endpoint serves two shapes depending on `?confirm=true`:
 *  • dry-run (default): assessment of what WOULD be cancelled
 *  • confirm=true: actual cancellation result
 *
 * `dry_run` discriminates between the two so the caller can branch.
 */
export interface KillTreeResponse {
  dry_run: boolean;
  target_run_id: string;
  // Dry-run fields
  target_path?: string;
  affected_count?: number;
  matched_run_ids?: string[];
  // Both
  skipped_terminal: number;
  hint?: string;
  // Confirm fields
  cancelled_count?: number;
  cancelled_run_ids?: string[];
}

export interface DrainTopicResponse {
  dry_run: boolean;
  topic: string;
  org_id: string | null;
  key: string;
  // Dry-run
  depth?: number;
  hint?: string;
  // Confirm
  before_depth?: number;
  after_depth?: number;
  removed_count?: number;
}

export interface ResetInboxResponse {
  dry_run: boolean;
  run_id: string;
  agent_id: string;
  key: string;
  // Dry-run
  current_count?: number;
  hint?: string;
  // Confirm
  removed_count?: number;
}

// ── RFC 0007 Slice B1 — TraceTree DTOs ───────────────

export interface TraceTreeNode {
  run_id: string;
  parent_run_id: string | null;
  root_run_id: string | null;
  depth: number;
  path: string;
  role_key: string;
  status: string;
  agent_instance_id: string | null;
  children: TraceTreeNode[];
}

export interface TraceTreeResponse {
  root_run_id: string;
  node_count: number;
  roots: TraceTreeNode[];
}

// ── RFC 0007 Slice B2 — InboxPanel DTOs ──────────────────

export interface InboxSummary {
  agent_id: string;
  depth: number;
  raw_depth: number;
}

export interface RunInboxesResponse {
  items: InboxSummary[];
  count: number;
  limit: number;
  redis_available: boolean;
}

export interface InboxMessageDTO {
  message_id: string;
  from_agent: string;
  to_agent: string;
  message_type: "request" | "response" | "fyi" | "broadcast";
  content: string;
  sent_at: string;
  ttl_sec: number;
  correlation_id: string;
}

export interface InboxPeekResponse {
  agent_id: string;
  expired_count: number;
  poison_count: number;
  count: number;
  messages: InboxMessageDTO[];
}

// ── RFC 0007 Slice B3 — Scratchpad DTOs ──────────────────

export interface ScratchpadNamespaceSummary {
  namespace: string;
  field_count: number;
}

export interface RunScratchpadsResponse {
  items: ScratchpadNamespaceSummary[];
  count: number;
  limit: number;
  redis_available: boolean;
}

export interface ScratchpadFieldDTO {
  field: string;
  value_type: string;
  value: unknown;
  raw_value: string;
}

export interface ScratchpadPeekResponse {
  namespace: string;
  poison_count: number;
  count: number;
  fields: ScratchpadFieldDTO[];
}

// ── RFC 0007 Slice B4 — MessageBus DTOs ──────────────────

export interface BusTopicInfo {
  name: string;
  description: string;
  delivery: string;
  backpressure_policy: string;
  backpressure_threshold: number;
  org_scoped: boolean;
  depth: number;
}

export interface BusTopicsResponse {
  items: BusTopicInfo[];
  count: number;
  org_id: string | null;
  redis_available: boolean;
}

export interface TopicEntryDTO {
  stream_id: string;
  payload: unknown;
  raw_payload: string;
}

export interface TopicPeekResponse {
  topic: string;
  org_id: string | null;
  depth: number;
  poison_count: number;
  count: number;
  entries: TopicEntryDTO[];
}

// ── RFC0003 Creative Agent Family (read-only) ──

export type CreativeRoleId =
  | "creative_image_designer"
  | "creative_motion_designer"
  | "creative_video_director"
  | "creative_audio_composer"
  | "creative_3d_artist";

export interface CreativeRoleProfile {
  role: CreativeRoleId;
  display_name: { en: string; zh: string };
  main_battlefield: string;
  primary_media_types: string[];
  default_models: string[];
  allowed_tools: string[];
  sandbox_image: string;
  session_kind: string;
}

export interface CreativeSkillEntry {
  slug: string;
  display_name: { en: string; zh: string };
  style_prompt?: string;
  negative_prompt?: string;
  description?: string;
  reference_count?: number;
  target_duration_sec?: number;
  pacing?: string;
  shot_count_target?: number;
  tags: string[];
}

export interface VideoCostEstimateResponse {
  estimated_cents: number;
  estimated_usd: number;
  provider: string;
  duration_sec: number;
  resolution: string;
  requires_explicit_approval: boolean;
  reason: string;
}

export interface ThreeDCostEstimateResponse {
  estimated_cents: number;
  estimated_usd: number;
  provider: string;
  quality: string;
  target_face_count: number;
  requires_explicit_approval: boolean;
  reason: string;
  quality_hint: {
    expected_face_cap: number;
    expected_file_size_kb: number;
    suitable_for: string[];
  } | null;
}

export interface ModerationResultResponse {
  verdict: "allow" | "flag" | "block";
  matched_categories: string[];
  matched_terms: string[];
  reason: string;
  confidence: number;
}

export const creativeApi = {
  listRoles: () =>
    api.get<{ items: CreativeRoleProfile[]; count: number }>(
      "/creative/roles",
    ),
  getRole: (id: CreativeRoleId) =>
    api.get<CreativeRoleProfile>(`/creative/roles/${id}`),
  getRoleTools: (id: CreativeRoleId) =>
    api.get<{
      role: CreativeRoleId;
      allowed_tools: { name: string; requires_approval: boolean }[];
      count: number;
    }>(`/creative/roles/${id}/tools`),
  listAllTools: () =>
    api.get<{
      image: unknown[];
      motion_audio: unknown[];
      video: unknown[];
      three_d: unknown[];
      approval_required: string[];
      total: number;
    }>("/creative/tools"),
  toolRequiresApproval: (toolName: string) =>
    api.get<{ tool: string; requires_approval: boolean }>(
      `/creative/tools/${toolName}/requires-approval`,
    ),
  listImageStyles: () =>
    api.get<{ items: CreativeSkillEntry[]; count: number }>(
      "/creative/skills/image-styles",
    ),
  listMotionTemplates: () =>
    api.get<{ items: CreativeSkillEntry[]; count: number }>(
      "/creative/skills/motion-templates",
    ),
  listAudioVoices: () =>
    api.get<{ items: CreativeSkillEntry[]; count: number }>(
      "/creative/skills/audio-voices",
    ),
  listVideoFormats: () =>
    api.get<{ items: CreativeSkillEntry[]; count: number }>(
      "/creative/skills/video-formats",
    ),
  estimateVideo: (data: {
    prompt: string;
    duration_sec?: number;
    provider?: string;
    resolution?: string;
    fps?: number;
  }) =>
    api.post<VideoCostEstimateResponse>("/creative/estimate/video", data),
  estimate3D: (data: {
    prompt: string;
    provider?: string;
    quality?: string;
    output_format?: string;
  }) => api.post<ThreeDCostEstimateResponse>("/creative/estimate/3d", data),
  moderate: (data: { text: string }) =>
    api.post<ModerationResultResponse>("/creative/moderate", data),
};

// ── Strategy Marketplace (MM1 Phase 0) ──────────────────────────
//
// Backend endpoints from S15 PR-7 (HTTP gateway). The shapes mirror
// the S14 ORM rows; Decimal values arrive as strings (FastAPI default).
// See `docs/architecture/14a-strategy-marketplace-milestones.md` §MM1.

import type {
  CreateEmploymentRequest,
  CreateListingRequest,
  EmploymentContract,
  EmploymentDetail,
  EmploymentRole,
  MarketplaceSearchParams,
  PerformanceReport,
  SettlementEvent,
  StrategyListing,
  StrategyListingDetail,
} from "../types";

/**
 * The strategy marketplace (S16, MM1 Phase 0) — separate namespace
 * from the WorkDAO baseline `marketplaceApi` (Skill/Model/Tool/
 * Knowledge purchases) defined above. Both will coexist for as long
 * as the baseline UI surface remains in the codebase; consumers
 * should reach for `strategyMarketplaceApi` for any trading-product
 * marketplace work.
 */
export const strategyMarketplaceApi = {
  /**
   * Public search — ACTIVE listings, joined with provider reputation
   * + strategy metadata. Defaults: sort=newest, limit=20, offset=0.
   */
  search: (params?: MarketplaceSearchParams) =>
    api.get<{ items: StrategyListingDetail[]; total: number }>(
      "/marketplace/strategies",
      { params },
    ),

  /** Single listing detail (public read). */
  get: (listingId: string) =>
    api.get<StrategyListingDetail>(`/marketplace/strategies/${listingId}`),

  /**
   * Provider lists their own strategy version. Returns a DRAFT row —
   * caller (provider UI) must call `activate` after the listing
   * signature is collected.
   */
  list: (data: CreateListingRequest) =>
    api.post<StrategyListing>("/marketplace/strategies", data),

  /** Soft-delete: status → DELISTED. Terminal; re-listing is a new row. */
  unlist: (listingId: string) =>
    api.delete<void>(`/marketplace/strategies/${listingId}`),

  pause: (listingId: string) =>
    api.post<void>(`/marketplace/strategies/${listingId}/pause`),

  resume: (listingId: string) =>
    api.post<void>(`/marketplace/strategies/${listingId}/resume`),
};

export const employmentApi = {
  /**
   * List the caller's active employments under one role.
   * Returns PENDING + ACTIVE + PAUSED rows (TERMINATED excluded).
   */
  listActive: (role: EmploymentRole) =>
    api.get<{ items: EmploymentContract[]; total: number }>(
      "/employment/active",
      { params: { role } },
    ),

  /** Single contract with PerformanceReport + SettlementEvent history. */
  get: (employmentId: string) =>
    api.get<EmploymentDetail>(`/employment/${employmentId}`),

  /**
   * Employer creates a PENDING EmploymentContract by hiring a listing.
   * MM1: caller calls `activate` after off-chain deposit is verified.
   */
  create: (data: CreateEmploymentRequest) =>
    api.post<EmploymentContract>("/employment", data),

  activate: (employmentId: string) =>
    api.post<void>(`/employment/${employmentId}/activate`),

  /** Pause / resume — employer-only. */
  pause: (employmentId: string) =>
    api.post<void>(`/employment/${employmentId}/pause`),

  resume: (employmentId: string) =>
    api.post<void>(`/employment/${employmentId}/resume`),

  /** Either party may terminate; final-settle is server-side. */
  terminate: (employmentId: string) =>
    api.post<{ final_settlement: SettlementEvent | null }>(
      `/employment/${employmentId}/terminate`,
    ),

  /** Sub-resources for the detail page chart + ledger. */
  reports: (employmentId: string) =>
    api.get<{ items: PerformanceReport[] }>(
      `/employment/${employmentId}/reports`,
    ),

  settlements: (employmentId: string) =>
    api.get<{ items: SettlementEvent[] }>(
      `/employment/${employmentId}/settlements`,
    ),
};

// ── Internal: Marketplace PMF dashboard (S17 PR-2) ───────────
//
// Admin-only — surfaces the 6-metric PMF snapshot. Frontend page
// /internal/marketplace-pmf renders the response inline.

import type { MarketplacePmfResponse } from "../types";

export const marketplacePmfApi = {
  get: () => api.get<MarketplacePmfResponse>("/internal/marketplace-pmf"),
};
