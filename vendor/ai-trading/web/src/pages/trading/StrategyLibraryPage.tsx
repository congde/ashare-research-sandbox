import { ExperimentOutlined, PlayCircleOutlined } from "@ant-design/icons";
import { Alert, Button, Input, Segmented, Space, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useMemo, useState } from "react";
import { strategiesApi, type StrategyResponse, type StrategyStatus } from "../../api/services";
import { MonoNumber } from "../../quant-atelier";
import {
  MetricTile,
  QuantGlowCard,
  SectionHeader,
  StatusPill,
  TradingPageShell,
} from "./TradingPageShell";
import { strategyRows, type StrategyRow } from "./tradingData";

type Tone = "profit" | "loss" | "neutral" | "ai";

interface DisplayRow {
  id: string;
  name: string;
  market: string;
  statusLabel: string;
  statusTone: Tone;
  version: string;
  // Metrics come from each strategy's latest DONE backtest (API) or the demo
  // fixtures; null when a saved strategy hasn't been backtested yet.
  sharpe: number | null;
  pnl: number | null;
  maxDrawdown: number | null;
  source: "api" | "placeholder";
}

const API_STATUS: Record<StrategyStatus, { label: string; tone: Tone }> = {
  draft: { label: "草稿", tone: "neutral" },
  dry_run: { label: "Dry-run", tone: "ai" },
  live: { label: "Live", tone: "profit" },
  paused: { label: "暂停", tone: "neutral" },
  stopped: { label: "停止", tone: "loss" },
};

const FIXTURE_STATUS: Record<StrategyRow["status"], { label: string; tone: Tone }> = {
  draft: { label: "草稿", tone: "neutral" },
  backtesting: { label: "回测中", tone: "ai" },
  paper: { label: "Paper", tone: "profit" },
  live: { label: "Live", tone: "profit" },
};

function symbolOf(card: Record<string, unknown>): string {
  const symbol = card.symbol ?? card.market;
  return typeof symbol === "string" && symbol.length > 0 ? symbol : "—";
}

function apiToRow(s: StrategyResponse): DisplayRow {
  const status = API_STATUS[s.status] ?? { label: s.status, tone: "neutral" as Tone };
  const bt = s.latest_backtest;
  return {
    id: s.id,
    name: s.name,
    market: symbolOf(s.strategy_card),
    statusLabel: status.label,
    statusTone: status.tone,
    version: s.current_version,
    sharpe: bt?.sharpe ?? null,
    pnl: bt?.pnl_pct ?? null,
    // Engine reports drawdown as a positive magnitude; the column renders it
    // as a signed loss (matching the fixtures' negative convention), so negate.
    maxDrawdown: bt?.max_drawdown_pct != null ? -bt.max_drawdown_pct : null,
    source: "api",
  };
}

function fixtureToRow(row: StrategyRow): DisplayRow {
  const status = FIXTURE_STATUS[row.status];
  return {
    id: row.id,
    name: row.name,
    market: `${row.market} · ${row.horizon}`,
    statusLabel: status.label,
    statusTone: status.tone,
    version: "—",
    sharpe: row.sharpe,
    pnl: row.pnl30d,
    maxDrawdown: row.maxDrawdown,
    source: "placeholder",
  };
}

function metricCell(
  value: number | null,
  kind: "plain" | "pct",
  tone: "profit" | "loss" | "neutral",
  showSign = false,
) {
  if (value === null) return <span style={{ color: "var(--qa-text-3)" }}>—</span>;
  return kind === "pct" ? (
    <MonoNumber value={value} kind="pct" tone={tone} showSign={showSign} />
  ) : (
    <MonoNumber value={value} tone={tone} precision={2} />
  );
}

export default function StrategyLibraryPage() {
  const [strategies, setStrategies] = useState<StrategyResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | number>("全部");
  const [query, setQuery] = useState("");

  const loadStrategies = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const response = await strategiesApi.list({ limit: 50 });
      setStrategies(response.data.items);
    } catch {
      setLoadError("策略接口暂不可用，当前显示本地占位策略。");
      setStrategies([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadStrategies();
  }, [loadStrategies]);

  const usingApi = strategies.length > 0;

  const rows = useMemo<DisplayRow[]>(() => {
    const base = usingApi ? strategies.map(apiToRow) : strategyRows.map(fixtureToRow);
    return base.filter((row) => {
      const statusMatch = status === "全部" || row.statusLabel === status;
      const keyword = query.trim().toLowerCase();
      const queryMatch =
        !keyword ||
        row.name.toLowerCase().includes(keyword) ||
        row.market.toLowerCase().includes(keyword);
      return statusMatch && queryMatch;
    });
  }, [usingApi, strategies, status, query]);

  const columns: ColumnsType<DisplayRow> = [
    {
      title: "策略",
      dataIndex: "name",
      render: (_, row) => (
        <Space direction="vertical" size={2}>
          <strong>{row.name}</strong>
          <span style={{ color: "var(--qa-text-2)", fontSize: 12 }}>{row.market}</span>
        </Space>
      ),
    },
    {
      title: "状态",
      dataIndex: "statusLabel",
      render: (_, row) => <StatusPill tone={row.statusTone}>{row.statusLabel}</StatusPill>,
    },
    { title: "版本", dataIndex: "version" },
    {
      title: "Sharpe",
      dataIndex: "sharpe",
      render: (value: number | null) => metricCell(value, "plain", "neutral"),
    },
    {
      title: "PnL %",
      dataIndex: "pnl",
      render: (value: number | null) =>
        metricCell(value, "pct", value !== null && value < 0 ? "loss" : "profit", true),
    },
    {
      title: "Max DD",
      dataIndex: "maxDrawdown",
      render: (value: number | null) => metricCell(value, "pct", "loss", true),
    },
    {
      title: "操作",
      key: "actions",
      render: () => (
        <Space>
          <Button size="small" icon={<PlayCircleOutlined />} href="/backtests">
            回测
          </Button>
          <Button size="small" href="/copilot">
            改写
          </Button>
        </Space>
      ),
    },
  ];

  const liveCount = usingApi
    ? strategies.filter((s) => s.status === "live").length
    : strategyRows.filter((row) => row.status === "live").length;

  return (
    <TradingPageShell
      eyebrow="Strategy Library"
      title="策略库"
      description="所有策略候选以版本、证据和风险标签组织，先统一纳入回测与 paper trading 流程，再进入实盘审批。"
      actions={
        <>
          <Button className="btn-gradient" type="primary" href="/copilot">
            <ExperimentOutlined /> 新建策略
          </Button>
          <Button href="/backtests">批量回测</Button>
        </>
      }
      aside={
        <QuantGlowCard
          title={<SectionHeader title="策略摘要" description={usingApi ? "后端实时数据" : "本地占位"} />}
        >
          <div className="trading-metric-grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
            <MetricTile label="候选数" value={usingApi ? strategies.length : strategyRows.length} />
            <MetricTile label="Live" value={liveCount} tone="profit" />
            <MetricTile
              label="数据来源"
              value={usingApi ? "后端" : "占位"}
              tone={usingApi ? "profit" : "ai"}
            />
          </div>
        </QuantGlowCard>
      }
    >
      <QuantGlowCard>
        {loadError && (
          <Alert type="warning" message={loadError} showIcon style={{ marginBottom: 14 }} />
        )}
        <div className="trading-toolbar">
          <div className="trading-toolbar-left">
            <Segmented
              value={status}
              onChange={setStatus}
              options={["全部", "草稿", "Dry-run", "Live", "暂停", "停止"]}
            />
          </div>
          <div className="trading-toolbar-right">
            <Input.Search
              allowClear
              placeholder="搜索策略或市场"
              onSearch={setQuery}
              onChange={(event) => setQuery(event.target.value)}
              style={{ width: 260 }}
            />
          </div>
        </div>
        <Table
          className="trading-ant-table"
          columns={columns}
          dataSource={rows}
          loading={loading}
          pagination={false}
          rowKey="id"
          scroll={{ x: 920 }}
        />
      </QuantGlowCard>
    </TradingPageShell>
  );
}
