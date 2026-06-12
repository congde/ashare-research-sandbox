import { BarChartOutlined, ReloadOutlined } from "@ant-design/icons";
import { Alert, Button, Select, Space, Table, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  backtestApi,
  type BacktestResponse,
  type BacktestState,
  strategiesApi,
  type StrategyResponse,
} from "../../api/services";
import { MonoNumber } from "../../quant-atelier";
import {
  MetricTile,
  QuantGlowCard,
  SectionHeader,
  SignalRow,
  Sparkline,
  StatusPill,
  type Tone,
  TradingPageShell,
} from "./TradingPageShell";
import { backtestRows } from "./tradingData";

// Symbols the public Binance OHLCV endpoint can backtest. A run is keyed on
// symbol + timeframe, plus an optional strategy version: pick a saved strategy
// to backtest its compiled code, or leave it on the buy-and-hold baseline.
const SYMBOL_OPTIONS = [
  { label: "BTC/USDT", value: "BTC/USDT" },
  { label: "ETH/USDT", value: "ETH/USDT" },
  { label: "SOL/USDT", value: "SOL/USDT" },
  { label: "BNB/USDT", value: "BNB/USDT" },
  { label: "XRP/USDT", value: "XRP/USDT" },
];
const DEFAULT_TIMEFRAME = "1h";

interface DisplayRow {
  id: string;
  title: string;
  market: string;
  window: string;
  statusLabel: string;
  statusTone: Tone;
  pnl: number;
  sharpe: number;
  maxDrawdown: number;
  trades: number;
  equity: number[];
  source: "api" | "placeholder";
}

const API_STATUS: Record<BacktestState, { label: string; tone: Tone }> = {
  queued: { label: "排队", tone: "neutral" },
  running: { label: "运行中", tone: "ai" },
  done: { label: "已完成", tone: "profit" },
  failed: { label: "失败", tone: "loss" },
};

const FIXTURE_STATUS: Record<
  (typeof backtestRows)[number]["status"],
  { label: string; tone: Tone }
> = {
  ready: { label: "已完成", tone: "profit" },
  running: { label: "运行中", tone: "ai" },
  review: { label: "待复核", tone: "neutral" },
};

function num(value: number | undefined, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function apiToRow(bt: BacktestResponse): DisplayRow {
  const status = API_STATUS[bt.state];
  const start = bt.period_start?.slice(0, 10) ?? "";
  const end = bt.period_end?.slice(0, 10) ?? "";
  const initial = Number(bt.initial_capital) || 0;
  const finalEquity = Number(bt.metrics.final_equity) || initial;
  return {
    id: bt.id,
    title: bt.symbol,
    market: `${bt.symbol} · ${bt.timeframe}`,
    window: start && end ? `${start} 至 ${end}` : "—",
    statusLabel: status.label,
    statusTone: status.tone,
    pnl: num(bt.metrics.pnl_pct),
    sharpe: num(bt.metrics.sharpe),
    maxDrawdown: -Math.abs(num(bt.metrics.max_drawdown_pct)),
    trades: bt.trades_count,
    equity: [initial, finalEquity],
    source: "api",
  };
}

function fixtureToRow(row: (typeof backtestRows)[number]): DisplayRow {
  const status = FIXTURE_STATUS[row.status];
  return {
    id: row.id,
    title: row.strategy,
    market: row.market,
    window: row.window,
    statusLabel: status.label,
    statusTone: status.tone,
    pnl: row.pnl,
    sharpe: row.sharpe,
    maxDrawdown: row.maxDrawdown,
    trades: row.trades,
    equity: row.equity,
    source: "placeholder",
  };
}

export default function BacktestsPage() {
  const [symbol, setSymbol] = useState<string>(SYMBOL_OPTIONS[0].value);
  const [backtests, setBacktests] = useState<BacktestResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [strategies, setStrategies] = useState<StrategyResponse[]>([]);
  // null = buy-and-hold baseline (the harness); a UUID targets a saved version.
  const [strategyVersionId, setStrategyVersionId] = useState<string | null>(null);

  const loadBacktests = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const response = await backtestApi.list({ limit: 50 });
      setBacktests(response.data.items);
    } catch {
      setLoadError("回测接口暂不可用，当前显示本地占位回测。");
      setBacktests([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadBacktests();
  }, [loadBacktests]);

  // Load saved strategies to populate the picker. Non-fatal: on failure the
  // picker just stays on the buy-and-hold baseline.
  useEffect(() => {
    let active = true;
    strategiesApi
      .list({ limit: 100 })
      .then((res) => {
        if (active) setStrategies(res.data.items);
      })
      .catch(() => {
        /* picker stays empty → baseline only */
      });
    return () => {
      active = false;
    };
  }, []);

  // "" is the baseline sentinel; every other option carries a version UUID.
  const strategyOptions = useMemo(
    () => [
      { label: "买入持有基准", value: "" },
      ...strategies
        .filter((s) => s.current_version_id)
        .map((s) => ({
          label: `${s.name} · v${s.current_version}`,
          value: s.current_version_id as string,
        })),
    ],
    [strategies],
  );

  const handleRerun = useCallback(async () => {
    setRunning(true);
    try {
      const response = await backtestApi.create({
        symbol,
        timeframe: DEFAULT_TIMEFRAME,
        strategy_version_id: strategyVersionId ?? undefined,
      });
      const bt = response.data;
      const stratName = strategyVersionId
        ? strategies.find((s) => s.current_version_id === strategyVersionId)?.name
        : null;
      const prefix = stratName ? `「${stratName}」 ` : "";
      if (bt.state === "failed") {
        message.warning(
          `回测完成但标记为失败：${bt.error_message ?? "未知原因"}`,
        );
      } else {
        message.success(
          `已完成 ${prefix}${bt.symbol} 回测：收益 ${num(bt.metrics.pnl_pct).toFixed(2)}%`,
        );
      }
      await loadBacktests();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      message.error(detail || "回测触发失败，请稍后重试。");
    } finally {
      setRunning(false);
    }
  }, [symbol, strategyVersionId, strategies, loadBacktests]);

  const usingApi = backtests.length > 0;
  const rows: DisplayRow[] = useMemo(
    () =>
      usingApi
        ? backtests.map(apiToRow)
        : backtestRows.map(fixtureToRow),
    [usingApi, backtests],
  );

  const selected = rows[0];
  const bestSharpe = rows.reduce((acc, row) => Math.max(acc, row.sharpe), 0);
  const bestPnl = rows.reduce((acc, row) => Math.max(acc, row.pnl), 0);
  const deepestDd = rows.reduce(
    (acc, row) => Math.min(acc, row.maxDrawdown),
    0,
  );
  const deepestDdRow = rows.find((row) => row.maxDrawdown === deepestDd);

  const columns: ColumnsType<DisplayRow> = [
    {
      title: "回测任务",
      dataIndex: "title",
      render: (_, row) => (
        <Space direction="vertical" size={2}>
          <strong>{row.title}</strong>
          <span style={{ color: "var(--qa-text-2)", fontSize: 12 }}>
            {row.market} · {row.window}
          </span>
        </Space>
      ),
    },
    {
      title: "状态",
      dataIndex: "statusLabel",
      render: (_, row) => <StatusPill tone={row.statusTone}>{row.statusLabel}</StatusPill>,
    },
    {
      title: "PnL",
      dataIndex: "pnl",
      render: (value: number) => <MonoNumber value={value} kind="pct" tone="profit" showSign />,
    },
    {
      title: "Sharpe",
      dataIndex: "sharpe",
      render: (value: number) => <MonoNumber value={value} tone="neutral" precision={2} />,
    },
    {
      title: "Max DD",
      dataIndex: "maxDrawdown",
      render: (value: number) => <MonoNumber value={value} kind="pct" tone="loss" showSign />,
    },
    {
      title: "交易数",
      dataIndex: "trades",
      render: (value: number) => <MonoNumber value={value} kind="qty" tone="neutral" />,
    },
    {
      title: "权益曲线",
      dataIndex: "equity",
      width: 180,
      render: (value: number[]) => <Sparkline values={value} tone="profit" />,
    },
  ];

  return (
    <TradingPageShell
      eyebrow="Backtest Lab"
      title="回测详情"
      description="将策略候选转成可比较的回测任务，统一展示收益、回撤、交易数、权益曲线和复核状态。"
      actions={
        <>
          <Select
            value={strategyVersionId ?? ""}
            onChange={(value) => setStrategyVersionId(value || null)}
            style={{ minWidth: 220 }}
            options={strategyOptions}
            disabled={running}
            popupMatchSelectWidth={false}
          />
          <Select
            value={symbol}
            onChange={setSymbol}
            style={{ minWidth: 160 }}
            options={SYMBOL_OPTIONS}
            disabled={running}
          />
          <Button
            className="btn-gradient"
            type="primary"
            onClick={handleRerun}
            loading={running}
          >
            <ReloadOutlined /> 重新回测
          </Button>
        </>
      }
      aside={
        <QuantGlowCard
          title={<SectionHeader title="当前回测" description={selected?.window ?? "—"} />}
          badge={
            <StatusPill tone={selected?.statusTone ?? "neutral"}>
              {selected?.statusLabel ?? "无数据"}
            </StatusPill>
          }
        >
          <Sparkline values={selected?.equity ?? [100, 100]} tone="profit" />
          <div className="trading-kv">
            <div>
              <span>收益</span>
              <strong>{(selected?.pnl ?? 0).toFixed(1)}%</strong>
            </div>
            <div>
              <span>最大回撤</span>
              <strong>{(selected?.maxDrawdown ?? 0).toFixed(1)}%</strong>
            </div>
          </div>
        </QuantGlowCard>
      }
    >
      <section className="trading-grid">
        <QuantGlowCard className="trading-span-12">
          <div className="trading-metric-grid">
            <MetricTile label="回测任务" value={rows.length} subtle={usingApi ? "实时数据" : "本地占位"} />
            <MetricTile label="最佳 Sharpe" value={bestSharpe} tone="neutral" precision={2} />
            <MetricTile label="最大收益" value={bestPnl} kind="pct" tone="profit" showSign />
            <MetricTile
              label="最深回撤"
              value={deepestDd}
              kind="pct"
              tone="loss"
              showSign
              subtle={deepestDdRow?.title}
            />
          </div>
        </QuantGlowCard>

        <QuantGlowCard
          className="trading-span-8"
          title={
            <SectionHeader
              title="回测列表"
              description={usingApi ? "后端 backtest run API 实时数据" : "后端无数据，显示本地占位"}
            />
          }
        >
          {loadError && <Alert type="warning" message={loadError} showIcon style={{ marginBottom: 14 }} />}
          <Table
            className="trading-ant-table"
            columns={columns}
            dataSource={rows}
            loading={loading}
            pagination={false}
            rowKey="id"
            scroll={{ x: 980 }}
          />
        </QuantGlowCard>

        <QuantGlowCard
          className="trading-span-4"
          title={<SectionHeader title="复核清单" description="上线前必须满足" />}
          badge={<BarChartOutlined style={{ color: "var(--qa-neutral)" }} />}
        >
          <div className="trading-list">
            <SignalRow title="样本外窗口" meta="至少 20% 时间窗口保留" badge={<StatusPill tone="profit">通过</StatusPill>} />
            <SignalRow title="交易成本模型" meta="滑点、手续费、资金费率" badge={<StatusPill tone="neutral">待实测</StatusPill>} />
            <SignalRow title="异常行情样本" meta="插针、低流动性、交易所维护" badge={<StatusPill tone="ai">排队</StatusPill>} />
          </div>
        </QuantGlowCard>
      </section>
    </TradingPageShell>
  );
}
