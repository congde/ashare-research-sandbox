import {
  ArrowRightOutlined,
  CheckCircleOutlined,
  RocketOutlined,
  SafetyOutlined,
} from "@ant-design/icons";
import { Button, Progress } from "antd";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  type BacktestResponse,
  backtestApi,
  type RiskEventResponse,
  type RiskRuleResponse,
  type RiskSeverity,
  riskApi,
  type StrategyResponse,
  strategiesApi,
} from "../../api/services";
import {
  MetricTile,
  QuantGlowCard,
  SectionHeader,
  SignalRow,
  StatusPill,
  TradingPageShell,
} from "./TradingPageShell";
import { RISK_ACTION_TONE, RISK_KIND_LABEL, type RiskTone } from "./riskLabels";
import { backtestRows, riskRules, runtimeEvents, strategyRows } from "./tradingData";

function median(values: number[]): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

interface RecentBacktest {
  id: string;
  title: string;
  meta: string;
  running: boolean;
}

interface RiskCardRow {
  key: string;
  name: string;
  meta: string;
  level: RiskTone;
  coverage: number;
}

interface EventRow {
  key: string;
  time: string;
  title: string;
  meta: string;
  tone: RiskTone;
}

const SEVERITY_TONE: Record<RiskSeverity, RiskTone> = {
  low: "neutral",
  medium: "ai",
  high: "loss",
  critical: "loss",
};

const FIXTURE_BEST_SHARPE = strategyRows.reduce((best, row) => (row.sharpe > best ? row.sharpe : best), 0);

export default function TradingDashboard() {
  const navigate = useNavigate();
  const [strategies, setStrategies] = useState<StrategyResponse[]>([]);
  const [backtests, setBacktests] = useState<BacktestResponse[]>([]);
  const [rules, setRules] = useState<RiskRuleResponse[]>([]);
  const [events, setEvents] = useState<RiskEventResponse[]>([]);

  // Load the lists in parallel; allSettled so one failing source still lets
  // the others render real data (the rest falls back to fixtures per card).
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const [s, b, r, e] = await Promise.allSettled([
        strategiesApi.list({ limit: 50 }),
        backtestApi.list({ limit: 50 }),
        riskApi.list({ limit: 100 }),
        riskApi.listEvents({ limit: 20 }),
      ]);
      if (cancelled) return;
      if (s.status === "fulfilled") setStrategies(s.value.data.items);
      if (b.status === "fulfilled") setBacktests(b.value.data.items);
      if (r.status === "fulfilled") setRules(r.value.data.items);
      if (e.status === "fulfilled") setEvents(e.value.data.items);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const usingRules = rules.length > 0;
  const riskCardRows: RiskCardRow[] = usingRules
    ? rules.map((r) => ({
        key: r.id,
        name: RISK_KIND_LABEL[r.kind] ?? r.kind,
        meta: `${r.active ? "启用" : "停用"} / ${JSON.stringify(r.threshold)}`,
        level: RISK_ACTION_TONE[r.action] ?? "neutral",
        coverage: r.active ? 100 : 0,
      }))
    : riskRules.map((r) => ({
        key: r.name,
        name: r.name,
        meta: `${r.state} / 阈值 ${r.threshold}`,
        level: r.level,
        coverage: r.coverage,
      }));

  const usingStrategies = strategies.length > 0;
  const usingBacktests = backtests.length > 0;
  const usingEvents = events.length > 0;
  // Any live source flips the page-level 后端/占位 indicator — a new user with
  // seeded risk rules but no strategies/backtests still gets a real backend.
  const usingAnyApi = usingStrategies || usingBacktests || usingRules || usingEvents;

  const eventRows: EventRow[] = usingEvents
    ? events.map((e) => ({
        key: e.id,
        time: e.created_at.slice(11, 16), // ISO → HH:MM (UTC)
        title: e.trigger,
        meta: e.explanation_llm ?? `severity ${e.severity}`,
        tone: SEVERITY_TONE[e.severity] ?? "neutral",
      }))
    : runtimeEvents.map((ev) => ({
        key: `${ev.time}-${ev.title}`,
        time: ev.time,
        title: ev.title,
        meta: ev.meta,
        tone: ev.tone,
      }));

  const strategyCount = usingStrategies ? strategies.length : strategyRows.length;
  const liveCount = usingStrategies
    ? strategies.filter((s) => s.status === "live").length
    : strategyRows.filter((r) => r.status === "live").length;
  const dryRunCount = usingStrategies
    ? strategies.filter((s) => s.status === "dry_run").length
    : strategyRows.filter((r) => r.status === "paper").length;

  const btMetrics = backtests.map((b) => b.metrics);
  const medianPnl = usingBacktests ? median(btMetrics.map((m) => m.pnl_pct ?? 0)) : 32.5;
  const maxDd = usingBacktests
    ? Math.max(0, ...btMetrics.map((m) => Math.abs(m.max_drawdown_pct ?? 0)))
    : 8.4;
  const bestSharpe = usingBacktests
    ? Math.max(0, ...btMetrics.map((m) => m.sharpe ?? 0))
    : FIXTURE_BEST_SHARPE;

  const recentBacktests: RecentBacktest[] = usingBacktests
    ? backtests.slice(0, 4).map((b) => ({
        id: b.id,
        title: b.symbol,
        meta: `${b.timeframe} · PnL ${(b.metrics.pnl_pct ?? 0).toFixed(1)}% · DD ${Math.abs(
          b.metrics.max_drawdown_pct ?? 0,
        ).toFixed(1)}%`,
        running: b.state === "running" || b.state === "queued",
      }))
    : backtestRows.map((r) => ({
        id: r.id,
        title: r.strategy,
        meta: `${r.market} · PnL ${r.pnl.toFixed(1)}% · DD ${r.maxDrawdown.toFixed(1)}%`,
        running: r.status === "running",
      }));

  return (
    <TradingPageShell
      eyebrow="Quant Trading Workspace"
      title="量化交易工作台"
      description="策略生成、市场情报、回测验证、交易账户和风险护栏集中在一个执行面板里，先从可审计的 paper trading 流程开始推进。"
      actions={
        <>
          <Button className="btn-gradient" type="primary" onClick={() => navigate("/copilot")}>
            打开 Co-pilot <ArrowRightOutlined />
          </Button>
          <Button onClick={() => navigate("/risk")}>查看风控</Button>
        </>
      }
      aside={
        <QuantGlowCard
          variant="live"
          title={
            <SectionHeader
              title="今日运行状态"
              description={usingAnyApi ? "后端实时数据" : "Paper/live guardrail 预览"}
            />
          }
          badge={<StatusPill tone="profit">Ready</StatusPill>}
        >
          <div className="trading-kv">
            <div>
              <span>策略池</span>
              <strong>{strategyCount} 条候选</strong>
            </div>
            <div>
              <span>上线层级</span>
              <strong>
                {dryRunCount} dry-run / {liveCount} live
              </strong>
            </div>
            <div>
              <span>最佳 Sharpe</span>
              <strong>{bestSharpe.toFixed(2)}</strong>
            </div>
            <div>
              <span>数据来源</span>
              <strong>{usingAnyApi ? "后端" : "占位"}</strong>
            </div>
          </div>
        </QuantGlowCard>
      }
    >
      <section className="trading-grid">
        <QuantGlowCard className="trading-span-12">
          <div className="trading-metric-grid">
            <MetricTile label="策略候选" value={strategyCount} subtle="含 draft / dry-run / live" />
            <MetricTile
              label="回测收益中位数"
              value={medianPnl}
              kind="pct"
              tone="profit"
              showSign
              subtle={usingBacktests ? "后端回测池实时" : "基于当前样例回测池"}
            />
            <MetricTile
              label="最大回撤警戒"
              value={-maxDd}
              kind="pct"
              tone="loss"
              showSign
              subtle="低于 12% 组合阈值"
            />
            <MetricTile label="ValueScan 状态" value="MCP/API/Skill" tone="ai" subtle="待接入 live 证据链" />
          </div>
        </QuantGlowCard>

        <QuantGlowCard
          className="trading-span-7"
          title={<SectionHeader title="开发泳道" description="按当前里程碑推进的交易前端入口" />}
        >
          <div className="trading-list">
            <SignalRow
              title="M3 · 策略生成与自我改进"
              meta="Co-pilot、策略库、证据 trace、候选参数版本"
              badge={
                <Button size="small" onClick={() => navigate("/strategies")}>
                  策略库
                </Button>
              }
            />
            <SignalRow
              title="M4 · Research / Risk / Portfolio 分层决策"
              meta="ValueScan 市场情报、风险预算、组合层审批"
              badge={
                <Button size="small" onClick={() => navigate("/risk")}>
                  风控
                </Button>
              }
            />
            <SignalRow
              title="M5 · Agent Workspace"
              meta="交易任务、回测详情、evidence trace、人工审批"
              badge={
                <Button size="small" onClick={() => navigate("/backtests")}>
                  回测
                </Button>
              }
            />
            <SignalRow
              title="M6 · Paper / Live Guardrail"
              meta="交易账户权限、实盘熔断、live-market eval"
              badge={
                <Button size="small" onClick={() => navigate("/live")}>
                  实盘
                </Button>
              }
            />
          </div>
        </QuantGlowCard>

        <QuantGlowCard
          className="trading-span-5"
          title={
            <SectionHeader
              title="风险覆盖"
              description={usingRules ? "后端 /risk-rules 实时" : "上线前护栏完成度"}
            />
          }
          badge={<SafetyOutlined style={{ color: "var(--qa-neutral)" }} />}
        >
          <div className="trading-list">
            {riskCardRows.map((rule) => (
              <div key={rule.key}>
                <SignalRow
                  title={rule.name}
                  meta={rule.meta}
                  badge={<StatusPill tone={rule.level}>{rule.coverage}%</StatusPill>}
                />
                <Progress
                  percent={rule.coverage}
                  showInfo={false}
                  strokeColor="var(--qa-neutral)"
                  trailColor="rgba(255,255,255,0.08)"
                />
              </div>
            ))}
          </div>
        </QuantGlowCard>

        <QuantGlowCard
          className="trading-span-6"
          title={
            <SectionHeader
              title="最新回测"
              description={usingBacktests ? "后端 backtest API 实时结果" : "候选策略的最近验证结果"}
            />
          }
        >
          <div className="trading-list">
            {recentBacktests.map((row) => (
              <SignalRow
                key={row.id}
                title={row.title}
                meta={row.meta}
                badge={<StatusPill tone={row.running ? "ai" : "profit"}>{row.running ? "running" : "done"}</StatusPill>}
              />
            ))}
          </div>
        </QuantGlowCard>

        <QuantGlowCard
          className="trading-span-6"
          title={
            <SectionHeader
              title="运行事件"
              description={usingEvents ? "后端 /risk-events 实时" : "Paper/live 执行链路的最新信号"}
            />
          }
          badge={<RocketOutlined style={{ color: "var(--qa-profit)" }} />}
        >
          <div className="trading-list">
            {eventRows.map((event) => (
              <SignalRow
                key={event.key}
                title={`${event.time} · ${event.title}`}
                meta={event.meta}
                badge={
                  <StatusPill tone={event.tone}>
                    <CheckCircleOutlined />
                    已记录
                  </StatusPill>
                }
              />
            ))}
          </div>
        </QuantGlowCard>
      </section>
    </TradingPageShell>
  );
}
