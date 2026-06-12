import { ReloadOutlined } from "@ant-design/icons";
import { Alert, Button, InputNumber, Space, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import TradingChart from "../../components/charts/TradingChart";
import { useMemo } from "react";
import { MonoNumber } from "../../quant-atelier";
import { useReport } from "../../contexts/ReportContext";
import type { CurvePoint, Trade } from "../../types";
import {
  MetricTile,
  QuantGlowCard,
  SectionHeader,
  SignalRow,
  StatusPill,
  TradingPageShell,
} from "./TradingPageShell";

interface BacktestRow {
  id: string;
  title: string;
  market: string;
  window: string;
  statusLabel: string;
  statusTone: "profit" | "loss" | "neutral" | "ai";
  pnl: number;
  sharpe: number;
  maxDrawdown: number;
  trades: number;
  equity: number[];
  curve: CurvePoint[];
  tradeRows: Trade[];
}

export default function BacktestsPage() {
  const { report, loading, error, short, long, setShort, setLong, refresh } = useReport();

  const row: BacktestRow | null = useMemo(() => {
    if (!report) {
      return null;
    }
    const metrics = report.backtest.metrics;
    return {
      id: "fixed-sample",
      title: report.research.company,
      market: `${report.research.company} · 1day`,
      window: `MA ${short}/${long} · ${report.backtest.curve.length} bars`,
      statusLabel: "已完成",
      statusTone: "profit",
      pnl: metrics.strategy_return_pct,
      sharpe: metrics.sharpe_ratio,
      maxDrawdown: metrics.maximum_drawdown_pct,
      trades: metrics.trade_count,
      equity: report.backtest.curve.map((point) => point.equity),
      curve: report.backtest.curve,
      tradeRows: report.backtest.trades,
    };
  }, [long, report, short]);

  const rows = row ? [row] : [];

  const columns: ColumnsType<BacktestRow> = [
    {
      title: "回测任务",
      dataIndex: "title",
      render: (_, item) => (
        <Space direction="vertical" size={2}>
          <strong>{item.title}</strong>
          <span style={{ color: "var(--qa-text-2)", fontSize: 12 }}>
            {item.market} · {item.window}
          </span>
        </Space>
      ),
    },
    {
      title: "状态",
      dataIndex: "statusLabel",
      render: (_, item) => <StatusPill tone={item.statusTone}>{item.statusLabel}</StatusPill>,
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
      render: (_, item) => <TradingChart curve={item.curve} variant="mini" height={48} />,
    },
  ];

  return (
    <TradingPageShell
      eyebrow="Backtest Lab"
      title="回测详情"
      description="将策略候选转成可比较的回测任务，统一展示收益、回撤、交易数、权益曲线和复核状态。"
      actions={
        <>
          <Space>
            <span style={{ color: "var(--qa-text-2)", fontSize: 12 }}>短均线</span>
            <InputNumber min={2} value={short} onChange={(value) => setShort(Number(value ?? 3))} />
          </Space>
          <Space>
            <span style={{ color: "var(--qa-text-2)", fontSize: 12 }}>长均线</span>
            <InputNumber min={3} value={long} onChange={(value) => setLong(Number(value ?? 7))} />
          </Space>
          <Button className="btn-gradient" type="primary" loading={loading} onClick={() => void refresh()}>
            <ReloadOutlined /> 重新回测
          </Button>
        </>
      }
      aside={
        <QuantGlowCard
          title={<SectionHeader title="当前回测" description={row?.window ?? "—"} />}
          badge={<StatusPill tone="profit">{loading ? "running" : "done"}</StatusPill>}
        >
          <TradingChart curve={row?.curve ?? []} trades={row?.tradeRows ?? []} variant="compact" />
          <div className="trading-kv">
            <div>
              <span>收益</span>
              <strong>{(row?.pnl ?? 0).toFixed(1)}%</strong>
            </div>
            <div>
              <span>最大回撤</span>
              <strong>{(row?.maxDrawdown ?? 0).toFixed(1)}%</strong>
            </div>
          </div>
        </QuantGlowCard>
      }
    >
      <section className="trading-grid">
        <QuantGlowCard className="trading-span-12">
          <div className="trading-metric-grid">
            <MetricTile label="回测任务" value={rows.length} subtle="固定样本" />
            <MetricTile label="Sharpe" value={row?.sharpe ?? 0} tone="neutral" precision={2} />
            <MetricTile label="策略收益" value={row?.pnl ?? 0} kind="pct" tone="profit" showSign />
            <MetricTile
              label="最大回撤"
              value={row?.maxDrawdown ?? 0}
              kind="pct"
              tone="loss"
              showSign
            />
          </div>
        </QuantGlowCard>

        <QuantGlowCard
          className="trading-span-12"
          title={<SectionHeader title="K 线与权益" description="TradingView Lightweight Charts · 固定样本" />}
        >
          <TradingChart
            curve={row?.curve ?? []}
            trades={row?.tradeRows ?? []}
            variant="standard"
            showEquity
            height={340}
          />
          <div className="trading-chart-legend">
            <span>
              <i style={{ background: "#00ffa3" }} /> 阳线
            </span>
            <span>
              <i style={{ background: "#ff2d75" }} /> 阴线
            </span>
            <span>
              <i style={{ background: "#22d3ee" }} /> MA 短 / 权益
            </span>
            <span>
              <i style={{ background: "#f59e0b" }} /> MA 长
            </span>
          </div>
        </QuantGlowCard>

        <QuantGlowCard
          className="trading-span-8"
          title={<SectionHeader title="回测列表" description="/api/report 实时计算" />}
        >
          {error && <Alert type="warning" message={error} showIcon style={{ marginBottom: 14 }} />}
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
          title={<SectionHeader title="假设与限制" description="教学沙箱边界" />}
        >
          <div className="trading-list">
            {(report?.backtest.assumptions ?? ["加载中..."]).map((item) => (
              <SignalRow key={item} title={item} meta="固定样本回测" />
            ))}
          </div>
        </QuantGlowCard>
      </section>
    </TradingPageShell>
  );
}
