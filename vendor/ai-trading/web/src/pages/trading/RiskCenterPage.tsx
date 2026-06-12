import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  EditOutlined,
  PlusOutlined,
  PoweroffOutlined,
  ReloadOutlined,
  SafetyOutlined,
  StopOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useState } from "react";

import {
  type ApprovalAction,
  type ApprovalResponse,
  type ApprovalState,
  type ListApprovalsResponse,
  type RiskAction,
  type RiskRuleCreate,
  type RiskRuleKind,
  type RiskRuleResponse,
  type RiskRuleUpdate,
  riskApi,
  strategiesRuntimeApi,
} from "../../api/services";
import {
  MetricTile,
  QuantGlowCard,
  SectionHeader,
  StatusPill,
  TradingPageShell,
} from "./TradingPageShell";
import {
  RISK_ACTION_LABEL,
  RISK_ACTION_TONE as ACTION_TONE,
  RISK_KIND_LABEL as KIND_LABEL,
  isPctKind,
  type RiskTone,
} from "./riskLabels";
import { riskRules } from "./tradingData";

// ── Approval state → tag colour ────────────────────────────────


function approvalStateColor(state: ApprovalState): string {
  switch (state) {
    case "pending":
      return "blue";
    case "approved":
      return "cyan";
    case "executed":
      return "green";
    case "execution_failed":
      return "red";
    case "rejected":
      return "default";
    case "expired":
      return "orange";
  }
}

function actionLabel(action: ApprovalAction): string {
  switch (action) {
    case "deploy_live":
      return "切实盘";
    case "change_threshold":
      return "改阈值";
    case "halt_all":
      return "全员熔断";
  }
}

// ── Risk-rule reference table (real rules ← /risk-rules, fixture fallback) ──

interface RuleRow {
  key: string;
  name: string;
  threshold: string;
  state: string;
  level: RiskTone;
  raw?: RiskRuleResponse; // present for API rows (enables edit/deactivate); absent for fixtures
}

interface RuleFormValues {
  kind: RiskRuleKind;
  pct?: number;
  action: RiskAction;
  active: boolean;
}

/** Pull a backend `detail` (422 validation / 429 rate-limit) out of an axios error. */
function errMsg(err: unknown): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  return err instanceof Error ? err.message : "未知错误";
}


export default function RiskCenterPage() {
  const queryClient = useQueryClient();
  const [haltModalOpen, setHaltModalOpen] = useState(false);
  const [haltReason, setHaltReason] = useState("");
  const [haltRunId, setHaltRunId] = useState("");

  // ── Risk-rule create / edit modal ───────────────────────────
  const [ruleModalOpen, setRuleModalOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<RiskRuleResponse | null>(null);
  const [ruleForm] = Form.useForm<RuleFormValues>();
  const watchedKind = Form.useWatch("kind", ruleForm);

  // ── List active runtimes (needed for halt_all target picker) ─
  const runtimesQuery = useQuery({
    queryKey: ["runtime-list"],
    queryFn: () => strategiesRuntimeApi.list().then((res) => res.data),
    refetchInterval: 10_000,
  });

  // ── Pending approvals ──────────────────────────────────────
  const approvalsQuery = useQuery({
    queryKey: ["runtime-approvals"],
    queryFn: () =>
      strategiesRuntimeApi
        .listApprovals()
        .then((res) => res.data as ListApprovalsResponse),
    refetchInterval: 5_000,
  });

  // ── Risk rules (read-only reference table) ─────────────────
  const riskRulesQuery = useQuery({
    queryKey: ["risk-rules"],
    queryFn: () => riskApi.list({ limit: 100 }).then((res) => res.data),
  });
  const apiRules = riskRulesQuery.data?.items ?? [];
  const usingApiRules = apiRules.length > 0;
  const ruleRows: RuleRow[] = usingApiRules
    ? apiRules.map((r) => ({
        key: r.id,
        name: KIND_LABEL[r.kind] ?? r.kind,
        threshold: JSON.stringify(r.threshold),
        state: r.active ? "启用" : "停用",
        level: ACTION_TONE[r.action] ?? "neutral",
        raw: r,
      }))
    : riskRules.map((r) => ({
        key: r.name,
        name: r.name,
        threshold: r.threshold,
        state: r.state,
        level: r.level,
      }));

  // ── Mutations ───────────────────────────────────────────────
  const createHaltMutation = useMutation({
    mutationFn: ({ runId, reason }: { runId: string; reason: string }) =>
      strategiesRuntimeApi
        .createApproval(runId, {
          action: "halt_all",
          reason,
          payload: {},
        })
        .then((res) => res.data),
    onSuccess: (data) => {
      message.success(
        `已开 halt_all 审批: ${data.request_id.slice(0, 8)}… (等待第二人批准)`,
      );
      setHaltModalOpen(false);
      setHaltReason("");
      setHaltRunId("");
      queryClient.invalidateQueries({ queryKey: ["runtime-approvals"] });
    },
    onError: (err: unknown) => {
      const detail = err instanceof Error ? err.message : "Unknown error";
      message.error(`开审批失败: ${detail}`);
    },
  });

  const approveMutation = useMutation({
    mutationFn: ({ requestId, note }: { requestId: string; note: string }) =>
      strategiesRuntimeApi
        .approve(requestId, { note })
        .then((res) => res.data as ApprovalResponse),
    onSuccess: (data) => {
      if (data.state === "executed") {
        message.success(`审批通过并已执行: ${data.action}`);
      } else if (data.state === "execution_failed") {
        message.warning(
          `审批通过但执行失败: ${data.execution_error ?? "未知错误"}`,
        );
      }
      queryClient.invalidateQueries({ queryKey: ["runtime-approvals"] });
    },
    onError: (err: unknown) => {
      const detail = err instanceof Error ? err.message : "Unknown error";
      // 409 = two-person rule violation OR terminal state.
      message.error(`审批失败: ${detail}`);
    },
  });

  const rejectMutation = useMutation({
    mutationFn: ({ requestId, note }: { requestId: string; note: string }) =>
      strategiesRuntimeApi
        .reject(requestId, { note })
        .then((res) => res.data),
    onSuccess: () => {
      message.info("审批已驳回");
      queryClient.invalidateQueries({ queryKey: ["runtime-approvals"] });
    },
  });

  // ── Risk-rule CRUD mutations ────────────────────────────────
  const invalidateRules = () =>
    queryClient.invalidateQueries({ queryKey: ["risk-rules"] });

  const createRuleMutation = useMutation({
    mutationFn: (data: RiskRuleCreate) => riskApi.create(data).then((r) => r.data),
    onSuccess: () => {
      message.success("规则已创建");
      setRuleModalOpen(false);
      invalidateRules();
    },
    onError: (err: unknown) => message.error(`创建失败: ${errMsg(err)}`),
  });

  const updateRuleMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: RiskRuleUpdate }) =>
      riskApi.update(id, data).then((r) => r.data),
    onSuccess: () => {
      message.success("规则已更新");
      setRuleModalOpen(false);
      invalidateRules();
    },
    onError: (err: unknown) => message.error(`更新失败: ${errMsg(err)}`),
  });

  const deactivateRuleMutation = useMutation({
    mutationFn: (id: string) => riskApi.remove(id).then((r) => r.data),
    onSuccess: () => {
      message.success("规则已停用");
      invalidateRules();
    },
    onError: (err: unknown) => message.error(`停用失败: ${errMsg(err)}`),
  });

  const openCreateRule = () => {
    setEditingRule(null);
    ruleForm.setFieldsValue({
      kind: "hard_daily_loss_pct",
      pct: 15,
      action: "auto_halt",
      active: true,
    });
    setRuleModalOpen(true);
  };

  const openEditRule = (r: RiskRuleResponse) => {
    setEditingRule(r);
    const pct = typeof r.threshold?.pct === "number" ? (r.threshold.pct as number) : undefined;
    ruleForm.setFieldsValue({ kind: r.kind, pct, action: r.action, active: r.active });
    setRuleModalOpen(true);
  };

  const submitRule = () => {
    ruleForm
      .validateFields()
      .then((v) => {
        const pctKind = isPctKind(v.kind);
        if (editingRule) {
          const data: RiskRuleUpdate = { action: v.action, active: v.active };
          if (pctKind) data.threshold = { pct: v.pct };
          updateRuleMutation.mutate({ id: editingRule.id, data });
        } else {
          createRuleMutation.mutate({
            kind: v.kind,
            action: v.action,
            active: v.active,
            threshold: pctKind ? { pct: v.pct } : {},
          });
        }
      })
      .catch(() => {
        /* field-level validation errors are shown inline by the Form */
      });
  };

  // ── Risk-rule reference table ─────────────────────────────
  const ruleColumns: ColumnsType<RuleRow> = [
    {
      title: "规则",
      dataIndex: "name",
      render: (_, row) => (
        <Space direction="vertical" size={2}>
          <strong>{row.name}</strong>
          <span style={{ color: "var(--qa-text-2)", fontSize: 12 }}>阈值 {row.threshold}</span>
        </Space>
      ),
    },
    { title: "状态", dataIndex: "state" },
    {
      title: "等级",
      dataIndex: "level",
      render: (value: RiskTone) => <StatusPill tone={value}>{value}</StatusPill>,
    },
    {
      title: "操作",
      width: 150,
      render: (_, row) =>
        // Fixture rows (no backing API rule) can't be edited.
        row.raw ? (
          <Space>
            <Button size="small" icon={<EditOutlined />} onClick={() => openEditRule(row.raw!)}>
              编辑
            </Button>
            {row.raw.active ? (
              <Popconfirm
                title="停用此规则?"
                description="软停用（保留审计），可重新启用。"
                okText="停用"
                cancelText="取消"
                okButtonProps={{ danger: true }}
                onConfirm={() => deactivateRuleMutation.mutate(row.raw!.id)}
              >
                <Button size="small" danger icon={<StopOutlined />} loading={deactivateRuleMutation.isPending}>
                  停用
                </Button>
              </Popconfirm>
            ) : null}
          </Space>
        ) : null,
    },
  ];

  // ── Approval table ────────────────────────────────────────
  const approvalColumns: ColumnsType<ApprovalResponse> = [
    {
      title: "类型",
      dataIndex: "action",
      width: 100,
      render: (action: ApprovalAction) => (
        <Tag color="purple">{actionLabel(action)}</Tag>
      ),
    },
    {
      title: "目标",
      dataIndex: "target",
      width: 120,
      ellipsis: true,
    },
    {
      title: "申请人",
      dataIndex: "requested_by",
      width: 100,
    },
    {
      title: "原因",
      dataIndex: "reason",
      ellipsis: true,
    },
    {
      title: "状态",
      dataIndex: "state",
      width: 120,
      render: (state: ApprovalState) => (
        <Tag color={approvalStateColor(state)}>{state}</Tag>
      ),
    },
    {
      title: "操作",
      width: 200,
      render: (_, row) => {
        if (row.state !== "pending") {
          return null;
        }
        return (
          <Space>
            <Button
              size="small"
              type="primary"
              icon={<CheckCircleOutlined />}
              loading={approveMutation.isPending}
              onClick={() => {
                Modal.confirm({
                  title: `批准 ${actionLabel(row.action)} ?`,
                  content: (
                    <Form layout="vertical">
                      <Form.Item label="审批备注">
                        <Input.TextArea
                          rows={3}
                          id="approve-note-input"
                          placeholder="可选 — 进入审计链"
                        />
                      </Form.Item>
                    </Form>
                  ),
                  okText: "确认批准",
                  cancelText: "取消",
                  onOk: () => {
                    const noteEl = document.getElementById(
                      "approve-note-input",
                    ) as HTMLTextAreaElement | null;
                    approveMutation.mutate({
                      requestId: row.request_id,
                      note: noteEl?.value ?? "",
                    });
                  },
                });
              }}
            >
              批准
            </Button>
            <Button
              size="small"
              danger
              icon={<CloseCircleOutlined />}
              loading={rejectMutation.isPending}
              onClick={() => {
                Modal.confirm({
                  title: `驳回 ${actionLabel(row.action)} ?`,
                  content: (
                    <Form layout="vertical">
                      <Form.Item label="驳回原因">
                        <Input.TextArea
                          rows={3}
                          id="reject-note-input"
                          placeholder="可选 — 进入审计链"
                        />
                      </Form.Item>
                    </Form>
                  ),
                  okText: "确认驳回",
                  cancelText: "取消",
                  okButtonProps: { danger: true },
                  onOk: () => {
                    const noteEl = document.getElementById(
                      "reject-note-input",
                    ) as HTMLTextAreaElement | null;
                    rejectMutation.mutate({
                      requestId: row.request_id,
                      note: noteEl?.value ?? "",
                    });
                  },
                });
              }}
            >
              驳回
            </Button>
          </Space>
        );
      },
    },
  ];

  const ruleCount = usingApiRules ? apiRules.length : riskRules.length;
  const activeCount = usingApiRules ? apiRules.filter((r) => r.active).length : riskRules.length;
  const criticalCount = usingApiRules
    ? apiRules.filter((r) => r.action === "auto_halt").length
    : riskRules.filter((r) => r.level === "loss").length;
  const coveragePct = usingApiRules
    ? ruleCount > 0
      ? Math.round((activeCount / ruleCount) * 100)
      : 0
    : Math.round(riskRules.reduce((sum, item) => sum + item.coverage, 0) / riskRules.length);
  const pendingCount = approvalsQuery.data?.count ?? 0;

  return (
    <TradingPageShell
      eyebrow="Risk Center"
      title="风控中心"
      description="5 条 MVP 风控规则 + 二人审批门 + 实时全员熔断。每个动作进入 SHA-256 审计链。"
      actions={
        <>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => {
              queryClient.invalidateQueries({ queryKey: ["runtime-approvals"] });
              queryClient.invalidateQueries({ queryKey: ["risk-rules"] });
            }}
          >
            刷新
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreateRule}>
            新建规则
          </Button>
          <Button
            danger
            icon={<PoweroffOutlined />}
            disabled={(runtimesQuery.data?.count ?? 0) === 0}
            onClick={() => setHaltModalOpen(true)}
          >
            发起 halt_all
          </Button>
        </>
      }
      aside={
        <QuantGlowCard
          variant={pendingCount > 0 ? "live" : "default"}
          title={
            <SectionHeader
              title="待审批"
              description={`${pendingCount} 个 pending 请求`}
            />
          }
          badge={
            <StatusPill tone={pendingCount > 0 ? "ai" : "neutral"}>
              {pendingCount > 0 ? "Action" : "Idle"}
            </StatusPill>
          }
        >
          <Alert
            type="info"
            showIcon
            message="二人审批门"
            description="申请人 ≠ 审批人。驳回或 5min TTL 过期都会自动结算。"
          />
        </QuantGlowCard>
      }
    >
      <section className="trading-grid">
        <QuantGlowCard className="trading-span-12">
          <div className="trading-metric-grid">
            <MetricTile
              label="规则覆盖率"
              value={coveragePct}
              kind="pct"
              tone={coveragePct > 80 ? "profit" : "neutral"}
              subtle={`${activeCount}/${ruleCount} 启用`}
            />
            <MetricTile
              label="待审批"
              value={pendingCount}
              kind="qty"
              tone={pendingCount > 0 ? "ai" : "neutral"}
            />
            <MetricTile
              label="活跃 Runner"
              value={runtimesQuery.data?.count ?? 0}
              kind="qty"
              subtle="all"
            />
            <MetricTile
              label="规则等级"
              value={
                <Space size={4}>
                  <SafetyOutlined />
                  Critical: {criticalCount}
                </Space>
              }
              tone="loss"
            />
          </div>
        </QuantGlowCard>

        {/* ── Approvals table ────────────────────────────── */}
        <QuantGlowCard
          className="trading-span-12"
          title={
            <SectionHeader
              title="审批队列"
              description="所有 pending 二人审批请求"
            />
          }
        >
          {approvalsQuery.error ? (
            <Alert
              type="error"
              showIcon
              message="无法获取审批列表"
              description="检查后端 /api/v1/strategies/runtime/approvals 是否可达"
              style={{ marginBottom: 16 }}
            />
          ) : null}
          {pendingCount === 0 ? (
            <Empty description="当前无待审批请求" />
          ) : (
            <Table<ApprovalResponse>
              dataSource={approvalsQuery.data?.approvals ?? []}
              columns={approvalColumns}
              rowKey="request_id"
              pagination={false}
              size="small"
              data-testid="approvals-table"
            />
          )}
        </QuantGlowCard>

        {/* ── Static risk-rule reference ─────────────────── */}
        <QuantGlowCard
          className="trading-span-12"
          title={
            <SectionHeader
              title="风控规则"
              description={
                usingApiRules ? "后端 /risk-rules 实时" : "持仓 / PnL / 滑点 / 异常订单簿 / 紧急熔断（占位）"
              }
            />
          }
        >
          <Table
            dataSource={ruleRows}
            columns={ruleColumns}
            rowKey="key"
            loading={riskRulesQuery.isLoading}
            pagination={false}
            size="small"
          />
        </QuantGlowCard>
      </section>

      {/* ── Halt all modal ───────────────────────────────── */}
      <Modal
        title="发起 halt_all 审批"
        open={haltModalOpen}
        onOk={() => {
          if (!haltReason.trim()) {
            message.error("必须填写发起原因");
            return;
          }
          // halt_all targets all runners — path id is one of them
          // (any will do; backend ignores for halt_all). Default to
          // the first available run_id.
          const targetRunId =
            haltRunId ||
            (runtimesQuery.data?.run_ids ?? [])[0] ||
            "";
          if (!targetRunId) {
            message.error("没有活跃的 runner 可作为申请目标");
            return;
          }
          createHaltMutation.mutate({
            runId: targetRunId,
            reason: haltReason,
          });
        }}
        onCancel={() => {
          setHaltModalOpen(false);
          setHaltReason("");
          setHaltRunId("");
        }}
        confirmLoading={createHaltMutation.isPending}
        okText="提交审批"
        cancelText="取消"
        okButtonProps={{ danger: true }}
      >
        <Alert
          type="warning"
          showIcon
          message="halt_all 是全员熔断"
          description="审批通过后将触发所有运行中策略的 KillSwitch。仍需二人确认 — 申请人 ≠ 审批人,5min TTL。"
          style={{ marginBottom: 16 }}
        />
        <Form layout="vertical">
          <Form.Item label="发起原因 (必填,进入审计链)">
            <Input.TextArea
              rows={4}
              placeholder="说明触发原因 — 价格异常 / 新闻事件 / 系统故障 / 多策略相关亏损 ..."
              value={haltReason}
              onChange={(e) => setHaltReason(e.target.value)}
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* ── Create / edit risk-rule modal ────────────────── */}
      <Modal
        title={editingRule ? "编辑风控规则" : "新建风控规则"}
        open={ruleModalOpen}
        onOk={submitRule}
        onCancel={() => setRuleModalOpen(false)}
        confirmLoading={createRuleMutation.isPending || updateRuleMutation.isPending}
        okText={editingRule ? "保存" : "创建"}
        cancelText="取消"
        forceRender
      >
        <Form form={ruleForm} layout="vertical" initialValues={{ active: true }}>
          <Form.Item
            name="kind"
            label="规则类型"
            rules={[{ required: true, message: "请选择规则类型" }]}
          >
            <Select
              disabled={!!editingRule}
              data-testid="rule-kind-select"
              options={(Object.keys(KIND_LABEL) as RiskRuleKind[]).map((k) => ({
                value: k,
                label: KIND_LABEL[k],
              }))}
            />
          </Form.Item>
          {isPctKind((watchedKind ?? "hard_daily_loss_pct") as RiskRuleKind) ? (
            <Form.Item
              name="pct"
              label="阈值 (%)"
              tooltip="百分比，例如 15 = 15%"
              rules={[
                { required: true, message: "请输入阈值百分比" },
                { type: "number", min: 0.01, max: 100, message: "阈值需在 0–100 之间" },
              ]}
            >
              <InputNumber min={0.01} max={100} step={0.5} style={{ width: "100%" }} addonAfter="%" />
            </Form.Item>
          ) : (
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 24 }}
              message="异常订单簿使用默认启发式参数，无需阈值。"
            />
          )}
          <Form.Item
            name="action"
            label="触发动作"
            rules={[{ required: true, message: "请选择触发动作" }]}
          >
            <Select
              options={(Object.keys(RISK_ACTION_LABEL) as RiskAction[]).map((a) => ({
                value: a,
                label: RISK_ACTION_LABEL[a],
              }))}
            />
          </Form.Item>
          <Form.Item name="active" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </TradingPageShell>
  );
}
