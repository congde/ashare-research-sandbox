import {
  PauseCircleOutlined,
  PoweroffOutlined,
  ReloadOutlined,
  RocketOutlined,
} from "@ant-design/icons";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  message,
} from "antd";
import { useMemo, useState } from "react";

import {
  type ListRuntimeResponse,
  type RuntimeHealthResponse,
  type StartRuntimeRequest,
  strategiesRuntimeApi,
} from "../../api/services";
import {
  MetricTile,
  QuantGlowCard,
  SectionHeader,
  SignalRow,
  StatusPill,
  TradingPageShell,
} from "./TradingPageShell";

/**
 * Helper: parse a Decimal-as-string equity into a number for display.
 * Backend ships Decimal as string for precision; we accept a tiny
 * float-rounding cost at the UI boundary.
 */
function parseEquity(raw: string): number {
  const n = Number(raw);
  return Number.isFinite(n) ? n : 0;
}

function stateColor(state: string): "profit" | "loss" | "neutral" | "ai" {
  switch (state) {
    case "running":
      return "profit";
    case "failed":
      return "loss";
    case "starting":
    case "stopping":
      return "ai";
    default:
      return "neutral";
  }
}

interface KillSwitchModalState {
  runId: string;
  open: boolean;
}

export default function LiveRuntimePage() {
  const queryClient = useQueryClient();
  const [startOpen, setStartOpen] = useState(false);
  const [killState, setKillState] = useState<KillSwitchModalState>({
    runId: "",
    open: false,
  });
  const [killReason, setKillReason] = useState("");
  const [startForm] = Form.useForm<StartRuntimeRequest>();

  // ── List active runtimes ─────────────────────────────────────
  // Polls every 5 s. v1.5 will replace with WS push.
  const listQuery = useQuery({
    queryKey: ["runtime-list"],
    queryFn: () =>
      strategiesRuntimeApi.list().then((res) => res.data as ListRuntimeResponse),
    refetchInterval: 5_000,
  });

  // ── Per-runner health (poll each individually) ───────────────
  // useQueries handles a DYNAMIC array of queries with a SINGLE hook
  // call. Calling useQuery inside .map() violates the rules of hooks
  // and crashes the whole page the moment run_ids changes length
  // (e.g. the first runner appears: 0 → 1 hooks) → "Rendered more
  // hooks than during the previous render". useQueries is the correct
  // API for a variable number of parallel queries.
  const runIds = listQuery.data?.run_ids ?? [];
  const healthResults = useQueries({
    queries: runIds.map((runId) => ({
      queryKey: ["runtime-health", runId],
      queryFn: () =>
        strategiesRuntimeApi
          .health(runId)
          .then((res) => res.data as RuntimeHealthResponse),
      refetchInterval: 3_000,
    })),
  });

  // ── Start mutation ───────────────────────────────────────────
  const startMutation = useMutation({
    mutationFn: (req: StartRuntimeRequest) =>
      strategiesRuntimeApi.start(req).then((res) => res.data),
    onSuccess: (data) => {
      message.success(`运行已启动: ${data.run_id.slice(0, 8)}…`);
      setStartOpen(false);
      startForm.resetFields();
      queryClient.invalidateQueries({ queryKey: ["runtime-list"] });
    },
    onError: (err: unknown) => {
      const detail = err instanceof Error ? err.message : "Unknown error";
      message.error(`启动失败: ${detail}`);
    },
  });

  // ── Stop mutation ────────────────────────────────────────────
  const stopMutation = useMutation({
    mutationFn: (runId: string) =>
      strategiesRuntimeApi.stop(runId).then((res) => res.data),
    onSuccess: (data) => {
      message.success(`已停止 ${data.run_id.slice(0, 8)}…`);
      queryClient.invalidateQueries({ queryKey: ["runtime-list"] });
    },
  });

  // ── Kill switch mutation ────────────────────────────────────
  const killSwitchMutation = useMutation({
    mutationFn: ({ runId, reason }: { runId: string; reason: string }) =>
      strategiesRuntimeApi
        .tripKillSwitch(runId, { reason })
        .then((res) => res.data),
    onSuccess: (data) => {
      message.warning(`Kill Switch 已触发: ${data.run_id.slice(0, 8)}…`);
      setKillState({ runId: "", open: false });
      setKillReason("");
      queryClient.invalidateQueries({ queryKey: ["runtime-health", data.run_id] });
    },
  });

  // Aggregate KPIs across all runners.
  const aggregateKpi = useMemo(() => {
    const healths = healthResults
      .map((r) => r.data)
      .filter((d): d is RuntimeHealthResponse => Boolean(d));
    return {
      totalFills: healths.reduce((sum, h) => sum + h.fills, 0),
      totalRejected: healths.reduce((sum, h) => sum + h.rejected, 0),
      totalEquity: healths.reduce((sum, h) => sum + parseEquity(h.equity), 0),
      killSwitches: healths.filter((h) => h.kill_switch_tripped).length,
    };
  }, [healthResults]);

  const activeCount = listQuery.data?.count ?? 0;

  return (
    <TradingPageShell
      eyebrow="Paper / Live Runtime"
      title="实盘监控"
      description="实时跟踪所有运行中的策略 — 状态、订单、风控熔断。v1 仅 paper-first 路径,实盘需经审批门切换。"
      actions={
        <>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => {
              queryClient.invalidateQueries({ queryKey: ["runtime-list"] });
            }}
          >
            刷新
          </Button>
          <Button
            danger
            icon={<PauseCircleOutlined />}
            disabled={activeCount === 0}
            onClick={() => {
              Modal.confirm({
                title: "全局停止 — 当前所有运行中的策略",
                content: `将停止 ${activeCount} 个策略。此操作走 stop 路径(优雅停止),不触发熔断。`,
                okText: "确认停止",
                cancelText: "取消",
                onOk: async () => {
                  await Promise.allSettled(
                    runIds.map((id) => stopMutation.mutateAsync(id)),
                  );
                },
              });
            }}
          >
            全局停止
          </Button>
          <Button
            className="btn-gradient"
            type="primary"
            icon={<RocketOutlined />}
            onClick={() => setStartOpen(true)}
          >
            启动 Paper Run
          </Button>
        </>
      }
      aside={
        <QuantGlowCard
          variant={activeCount > 0 ? "live" : "default"}
          title={
            <SectionHeader
              title="运行状态"
              description={`当前活跃 ${activeCount} 个策略`}
            />
          }
          badge={
            <StatusPill tone={activeCount > 0 ? "profit" : "neutral"}>
              {activeCount > 0 ? "Live" : "Idle"}
            </StatusPill>
          }
        >
          <div className="trading-kv">
            <div>
              <span>订单通道</span>
              <strong>{activeCount > 0 ? "active" : "—"}</strong>
            </div>
            <div>
              <span>熔断已触发</span>
              <strong style={{ color: aggregateKpi.killSwitches > 0 ? "var(--qa-loss)" : undefined }}>
                {aggregateKpi.killSwitches}
              </strong>
            </div>
            <div>
              <span>累计成交</span>
              <strong>{aggregateKpi.totalFills}</strong>
            </div>
            <div>
              <span>累计拒绝</span>
              <strong>{aggregateKpi.totalRejected}</strong>
            </div>
          </div>
        </QuantGlowCard>
      }
    >
      {listQuery.error ? (
        <Alert
          type="error"
          showIcon
          message="无法获取运行中策略列表"
          description="检查后端 /api/v1/strategies/runtime 是否可达"
          style={{ marginBottom: 16 }}
        />
      ) : null}

      <section className="trading-grid">
        <QuantGlowCard className="trading-span-12">
          <div className="trading-metric-grid">
            <MetricTile
              label="活跃策略"
              value={activeCount}
              kind="qty"
              tone={activeCount > 0 ? "profit" : "neutral"}
              subtle="runners"
            />
            <MetricTile
              label="累计成交"
              value={aggregateKpi.totalFills}
              kind="qty"
              subtle="所有 runner"
            />
            <MetricTile
              label="累计 equity"
              value={aggregateKpi.totalEquity}
              kind="usd"
              tone="profit"
              showSign
            />
            <MetricTile
              label="熔断次数"
              value={aggregateKpi.killSwitches}
              kind="qty"
              tone={aggregateKpi.killSwitches > 0 ? "loss" : "profit"}
              subtle="当前"
            />
          </div>
        </QuantGlowCard>

        <QuantGlowCard
          className="trading-span-12"
          title={<SectionHeader title="活跃 Runner" description="每行一个运行中策略" />}
        >
          {activeCount === 0 ? (
            <Empty description="尚未启动任何策略 — 点击 '启动 Paper Run' 创建" />
          ) : (
            <div className="trading-list" data-testid="runner-list">
              {runIds.map((runId, i) => {
                const health = healthResults[i]?.data;
                if (!health) {
                  return (
                    <SignalRow
                      key={runId}
                      title={runId.slice(0, 12)}
                      meta="loading…"
                    />
                  );
                }
                return (
                  <SignalRow
                    key={runId}
                    title={`${runId.slice(0, 12)} · ${health.state}`}
                    meta={
                      `candles=${health.candles_processed}, ` +
                      `fills=${health.fills}, rejected=${health.rejected}, ` +
                      `equity=${health.equity}` +
                      (health.kill_switch_tripped ? " 🛑 KILL" : "")
                    }
                    badge={
                      <div style={{ display: "flex", gap: 8 }}>
                        <StatusPill tone={stateColor(health.state)}>
                          {health.state}
                        </StatusPill>
                        <Button
                          size="small"
                          danger
                          icon={<PoweroffOutlined />}
                          onClick={() =>
                            setKillState({ runId, open: true })
                          }
                          disabled={health.kill_switch_tripped}
                        >
                          熔断
                        </Button>
                        <Button
                          size="small"
                          onClick={() => stopMutation.mutate(runId)}
                          loading={stopMutation.isPending}
                        >
                          停止
                        </Button>
                      </div>
                    }
                  />
                );
              })}
            </div>
          )}
        </QuantGlowCard>
      </section>

      {/* ── Start runtime modal ───────────────────────────── */}
      <Modal
        title="启动 Paper Run"
        open={startOpen}
        onOk={() => startForm.submit()}
        onCancel={() => setStartOpen(false)}
        confirmLoading={startMutation.isPending}
        okText="启动"
        cancelText="取消"
      >
        <Form<StartRuntimeRequest>
          form={startForm}
          layout="vertical"
          initialValues={{
            symbol: "BTC/USDT",
            timeframe: "1m",
            qty: 0.001,
            initial_capital: 1000,
            candles: 5,
          }}
          onFinish={(values) => startMutation.mutate(values)}
        >
          <Form.Item label="Symbol" name="symbol" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item label="Timeframe" name="timeframe" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item label="单笔数量" name="qty">
            <InputNumber min={0} step={0.001} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item label="初始资金 (USDT)" name="initial_capital">
            <InputNumber min={0} step={100} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item label="预播 K 线数" name="candles">
            <InputNumber min={3} max={500} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item
            label="MaxPosition 上限 (USDT, 可选)"
            name="max_position_usd"
          >
            <InputNumber min={0} step={100} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item label="MaxDrawdown 比例 (0-1, 可选)" name="max_drawdown_pct">
            <InputNumber min={0} max={1} step={0.01} style={{ width: "100%" }} />
          </Form.Item>
        </Form>
      </Modal>

      {/* ── Kill switch modal ─────────────────────────────── */}
      <Modal
        title="触发紧急熔断"
        open={killState.open}
        onOk={() => {
          if (!killReason.trim()) {
            message.error("必须填写熔断原因");
            return;
          }
          killSwitchMutation.mutate({
            runId: killState.runId,
            reason: killReason,
          });
        }}
        onCancel={() => {
          setKillState({ runId: "", open: false });
          setKillReason("");
        }}
        confirmLoading={killSwitchMutation.isPending}
        okText="确认熔断"
        cancelText="取消"
        okButtonProps={{ danger: true }}
      >
        <Alert
          type="warning"
          showIcon
          message="熔断后该 Runner 将阻止所有后续订单"
          description="不会停止 Runner — 只阻订单提交。需要完全停止请用 '停止' 按钮。原因将进入审计链。"
          style={{ marginBottom: 16 }}
        />
        <Input.TextArea
          rows={4}
          placeholder="说明熔断原因(必填,进入审计链)"
          value={killReason}
          onChange={(e) => setKillReason(e.target.value)}
        />
      </Modal>
    </TradingPageShell>
  );
}
