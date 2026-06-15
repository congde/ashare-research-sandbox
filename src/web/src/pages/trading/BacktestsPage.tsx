import { ReloadOutlined } from "@ant-design/icons";
import { Alert, Button, InputNumber, Select, Space, Table, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchBacktestStrategies, runRollingBacktest } from "../../api";
import TradingChart from "../../components/charts/TradingChart";
import { MonoNumber } from "../../quant-atelier";
import type { CurvePoint, RollingBacktestPayload, RollingTrade, Trade } from "../../types";
import {
  MetricTile,
  QuantGlowCard,
  SectionHeader,
  SignalRow,
  StatusPill,
  TradingPageShell,
} from "./TradingPageShell";

const SYMBOL_OPTIONS = [
  { label: "WEB3-DEMO/USDT · 教学样本", value: "WEB3-DEMO/USDT" },
  { label: "BTC-USDT · 离线 K 线", value: "BTC-USDT" },
];

function tsToDate(ts: number): string {
  return new Date(ts * 1000).toISOString().slice(0, 10);
}

function equityToCurve(payload: RollingBacktestPayload | null): CurvePoint[] {
  if (!payload?.equity_curve?.length) {
    return [];
  }
  return payload.equity_curve.map((point) => ({
    date: tsToDate(point.ts),
    close: point.close,
    equity: point.equity,
  }));
}

function rollingTradesToChartTrades(trades: RollingTrade[]): Trade[] {
  return trades.flatMap((trade) => {
    const entryAction = trade.direction === "LONG" ? "BUY" : "SELL";
    const exitAction = trade.direction === "LONG" ? "SELL" : "BUY";
    return [
      { date: tsToDate(trade.entryTs), action: entryAction, price: trade.entryPrice },
      { date: tsToDate(trade.exitTs), action: exitAction, price: trade.exitPrice },
    ];
  });
}

interface TradeRow {
  key: string;
  direction: string;
  entry: string;
  exit: string;
  pnl: number;
  reason: string;
  bars: number;
}

function toTradeRows(trades: RollingTrade[]): TradeRow[] {
  return trades.map((trade, index) => ({
    key: String(index),
    direction: trade.direction,
    entry: `${tsToDate(trade.entryTs)} @ ${trade.entryPrice.toFixed(4)}`,
    exit: `${tsToDate(trade.exitTs)} @ ${trade.exitPrice.toFixed(4)}`,
    pnl: trade.pnlPct,
    reason: trade.exitReason,
    bars: trade.barsHeld,
  }));
}

export default function BacktestsPage() {
  const [strategies, setStrategies] = useState<{ label: string; value: string }[]>([]);
  const [strategy, setStrategy] = useState("technical_signal");
  const [symbol, setSymbol] = useState(SYMBOL_OPTIONS[0].value);
  const [stopLoss, setStopLoss] = useState(3);
  const [takeProfit, setTakeProfit] = useState(5);
  const [trailingStop, setTrailingStop] = useState(0);
  const [maxHoldBars, setMaxHoldBars] = useState(0);
  const [result, setResult] = useState<RollingBacktestPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    fetchBacktestStrategies()
      .then((items) => {
        setStrategies(items.map((item) => ({ label: item.displayName, value: item.name })));
      })
      .catch(() => {
        setStrategies([
          { label: "技术信号策略", value: "technical_signal" },
          { label: "均线交叉策略", value: "ma_crossover" },
          { label: "买入持有基准", value: "buy_and_hold" },
        ]);
      });
  }, []);

  const runBacktest = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const payload = await runRollingBacktest({
        strategy,
        symbol,
        stopLoss,
        takeProfit,
        trailingStop,
        maxHoldBars,
        limit: 120,
      });
      setResult(payload);
      message.success(
        `回测完成：${payload.strategy} · 收益 ${payload.total_return_pct.toFixed(2)}%`,
      );
    } catch (err) {
      const detail = err instanceof Error ? err.message : "回测失败";
      setLoadError(detail);
      message.error(detail);
    } finally {
      setLoading(false);
    }
  }, [maxHoldBars, stopLoss, strategy, symbol, takeProfit, trailingStop]);

  useEffect(() => {
    void runBacktest();
    // Initial load only; parameter changes rerun via the action button.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const curve = useMemo(() => equityToCurve(result), [result]);
  const chartTrades = useMemo(() => rollingTradesToChartTrades(result?.trades ?? []), [result]);
  const tradeRows = useMemo(() => toTradeRows(result?.trades ?? []), [result]);

  const tradeColumns: ColumnsType<TradeRow> = [
    { title: "方向", dataIndex: "direction", width: 72 },
    { title: "入场", dataIndex: "entry" },
    { title: "出场", dataIndex: "exit" },
    {
      title: "PnL",
      dataIndex: "pnl",
      width: 90,
      render: (value: number) => (
        <MonoNumber value={value} kind="pct" tone={value >= 0 ? "profit" : "loss"} showSign />
      ),
    },
    { title: "原因", dataIndex: "reason", width: 100 },
    { title: "持仓K", dataIndex: "bars", width: 72 },
  ];

  const windowLabel = result
    ? `${result.symbol} · ${result.kline_type} · ${result.total_candles} bars`
    : "—";

  return (
    <TradingPageShell
      eyebrow="Backtest Lab"
      title="策略回测"
      description="对齐 web3-trading 滚动窗口回测：策略注册表、止损止盈、权益曲线与交易明细；数据来自教学样本或离线 K 线。"
      actions={
        <>
          <Select
            value={strategy}
            onChange={setStrategy}
            style={{ minWidth: 180 }}
            options={strategies}
            disabled={loading}
          />
          <Select
            value={symbol}
            onChange={setSymbol}
            style={{ minWidth: 220 }}
            options={SYMBOL_OPTIONS}
            disabled={loading}
          />
          <Space>
            <span style={{ color: "var(--qa-text-2)", fontSize: 12 }}>止损%</span>
            <InputNumber min={0.5} max={20} step={0.5} value={stopLoss} onChange={(v) => setStopLoss(Number(v ?? 3))} />
          </Space>
          <Space>
            <span style={{ color: "var(--qa-text-2)", fontSize: 12 }}>止盈%</span>
            <InputNumber min={0.5} max={50} step={0.5} value={takeProfit} onChange={(v) => setTakeProfit(Number(v ?? 5))} />
          </Space>
          <Space>
            <span style={{ color: "var(--qa-text-2)", fontSize: 12 }}>移动止损%</span>
            <InputNumber min={0} max={20} step={0.5} value={trailingStop} onChange={(v) => setTrailingStop(Number(v ?? 0))} />
          </Space>
          <Space>
            <span style={{ color: "var(--qa-text-2)", fontSize: 12 }}>最长持仓</span>
            <InputNumber min={0} max={500} step={1} value={maxHoldBars} onChange={(v) => setMaxHoldBars(Number(v ?? 0))} />
          </Space>
          <Button className="btn-gradient" type="primary" loading={loading} onClick={() => void runBacktest()}>
            <ReloadOutlined /> 运行回测
          </Button>
        </>
      }
      aside={
        <QuantGlowCard
          title={<SectionHeader title="当前回测" description={windowLabel} />}
          badge={<StatusPill tone="profit">{loading ? "running" : "done"}</StatusPill>}
        >
          <TradingChart curve={curve} trades={chartTrades} variant="compact" showEquity />
          <div className="trading-kv">
            <div>
              <span>收益</span>
              <strong>{(result?.total_return_pct ?? 0).toFixed(1)}%</strong>
            </div>
            <div>
              <span>最大回撤</span>
              <strong>{-(result?.max_drawdown_pct ?? 0).toFixed(1)}%</strong>
            </div>
          </div>
        </QuantGlowCard>
      }
    >
      <section className="trading-grid">
        <QuantGlowCard className="trading-span-12">
          <div className="trading-metric-grid">
            <MetricTile label="策略" value={result?.strategy ?? "—"} subtle={result?.engine ?? "web3-trading"} />
            <MetricTile label="Sharpe" value={result?.sharpe_ratio ?? 0} tone="neutral" precision={2} />
            <MetricTile label="胜率" value={result?.win_rate ?? 0} kind="plain" tone="neutral" subtle="%" />
            <MetricTile
              label="总收益"
              value={result?.total_return_pct ?? 0}
              kind="pct"
              tone="profit"
              showSign
            />
            <MetricTile
              label="最大回撤"
              value={-(result?.max_drawdown_pct ?? 0)}
              kind="pct"
              tone="loss"
              showSign
            />
            <MetricTile label="交易数" value={result?.total_trades ?? 0} kind="qty" tone="neutral" />
            <MetricTile label="Calmar" value={result?.calmar_ratio ?? 0} tone="neutral" precision={2} />
            <MetricTile label="盈亏比" value={result?.profit_factor ?? 0} tone="neutral" precision={2} />
          </div>
        </QuantGlowCard>

        <QuantGlowCard
          className="trading-span-12"
          title={
            <SectionHeader
              title="权益曲线"
              description="/api/dashboard/backtest · web3-trading rolling engine"
            />
          }
        >
          {loadError && <Alert type="warning" message={loadError} showIcon style={{ marginBottom: 14 }} />}
          <TradingChart curve={curve} trades={chartTrades} variant="standard" showEquity height={340} />
        </QuantGlowCard>

        <QuantGlowCard
          className="trading-span-8"
          title={<SectionHeader title="成交明细" description={`${tradeRows.length} 笔 · SL ${stopLoss}% / TP ${takeProfit}%`} />}
        >
          <Table
            className="trading-ant-table"
            columns={tradeColumns}
            dataSource={tradeRows}
            loading={loading}
            pagination={false}
            rowKey="key"
            scroll={{ x: 760 }}
            size="small"
          />
        </QuantGlowCard>

        <QuantGlowCard
          className="trading-span-4"
          title={<SectionHeader title="假设与限制" description="教学沙箱边界" />}
        >
          <div className="trading-list">
            {(result?.assumptions ?? ["加载中..."]).map((item) => (
              <SignalRow key={item} title={item} meta="web3-trading 回测" />
            ))}
          </div>
        </QuantGlowCard>
      </section>
    </TradingPageShell>
  );
}
