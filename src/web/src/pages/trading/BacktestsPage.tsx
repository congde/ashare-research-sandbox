import { ReloadOutlined } from "@ant-design/icons";
import { Alert, Button, Checkbox, InputNumber, Select, Space, Table, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { fetchBacktestCompare, fetchBacktestCpcv, fetchBacktestPortfolio, fetchBacktestRobustness, fetchBacktestStrategies, fetchBacktestWalkForward, fetchBacktestWindows, fetchFactorMine, runMinedFactorBacktest, runRollingBacktest } from "../../api";
import BacktestComboChart from "../../components/charts/BacktestComboChart";
import TradingChart from "../../components/charts/TradingChart";
import { mergeTradeTimesIntoCurve } from "../../components/charts/series";
import { tsToChartDay } from "../../components/charts/chartTime";
import { MonoNumber } from "../../quant-atelier";
import type { BacktestComparePayload, BacktestCpcvPayload, BacktestPortfolioPayload, BacktestRobustnessPayload, BacktestWalkForwardPayload, BacktestWindowsPayload, CurvePoint, FactorMiningPayload, RollingBacktestPayload, RollingTrade, Trade } from "../../types";
import {
  MetricTile,
  QuantGlowCard,
  SectionHeader,
  SignalRow,
  StatusPill,
  TradingPageShell,
} from "./TradingPageShell";

const SYMBOL_OPTIONS = [
  { label: "WEB3-DEMO/USDT · 教学样本（固定至 2026-02-20）", value: "WEB3-DEMO/USDT" },
  { label: "BTC-USDT · 离线快照 / 可拉最新", value: "BTC-USDT" },
];

const LIMIT_OPTIONS = [
  { label: "60 根", value: 60 },
  { label: "120 根", value: 120 },
  { label: "300 根", value: 300 },
];

const COST_PRESET_OPTIONS = [
  { label: "教学（零滑点）", value: "teaching" },
  { label: "现实（5bps+动态滑点）", value: "realistic" },
  { label: "永续（+资金费率）", value: "perp" },
];

function tsToDate(ts: number): string {
  return tsToChartDay(ts);
}

function chartCandlesToCurve(payload: RollingBacktestPayload | null): CurvePoint[] {
  if (payload?.chart_candles?.length) {
    return payload.chart_candles.map((candle) => ({
      date: candle.date ?? tsToChartDay(candle.ts),
      ts: candle.ts,
      open: candle.open,
      high: candle.high,
      low: candle.low,
      close: candle.close,
      equity: 100,
    }));
  }
  return equityToCurve(payload);
}

function equityToCurve(payload: RollingBacktestPayload | null): CurvePoint[] {
  if (!payload?.equity_curve?.length) {
    return [];
  }
  const curve = payload.equity_curve.map((point) => ({
    date: tsToDate(point.ts),
    ts: point.ts,
    close: point.close,
    equity: point.equity,
  }));
  return mergeTradeTimesIntoCurve(curve, payload.trades ?? []);
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
  const [strategy, setStrategy] = useState("ma_crossover");
  const [symbol, setSymbol] = useState("BTC-USDT");
  const [refreshLive, setRefreshLive] = useState(false);
  const [stopLoss, setStopLoss] = useState(3);
  const [takeProfit, setTakeProfit] = useState(5);
  const [trailingStop, setTrailingStop] = useState(0);
  const [maxHoldBars, setMaxHoldBars] = useState(0);
  const [barLimit, setBarLimit] = useState(120);
  const [result, setResult] = useState<RollingBacktestPayload | null>(null);
  const [compare, setCompare] = useState<BacktestComparePayload | null>(null);
  const [windows, setWindows] = useState<BacktestWindowsPayload | null>(null);
  const [walkForward, setWalkForward] = useState<BacktestWalkForwardPayload | null>(null);
  const [robustness, setRobustness] = useState<BacktestRobustnessPayload | null>(null);
  const [cpcv, setCpcv] = useState<BacktestCpcvPayload | null>(null);
  const [portfolio, setPortfolio] = useState<BacktestPortfolioPayload | null>(null);
  const [costPreset, setCostPreset] = useState<"teaching" | "realistic" | "perp">("teaching");
  const [wfoLoading, setWfoLoading] = useState(false);
  const [auditLoading, setAuditLoading] = useState(false);
  const [portfolioLoading, setPortfolioLoading] = useState(false);
  const [wfoWindows, setWfoWindows] = useState(3);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [factorMine, setFactorMine] = useState<FactorMiningPayload | null>(null);
  const [factorLoading, setFactorLoading] = useState(false);
  const [factorError, setFactorError] = useState<string | null>(null);
  const [mineHorizon, setMineHorizon] = useState(1);
  const [mineMode, setMineMode] = useState<"gp" | "ml" | "both">("both");
  const [mineTarget, setMineTarget] = useState<"return" | "risk">("return");
  const [mineRiskKind, setMineRiskKind] = useState<"abs_ret" | "realized_vol">("abs_ret");

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
        limit: barLimit,
        costPreset,
        refresh: refreshLive && symbol !== "WEB3-DEMO/USDT",
      });
      const [comparePayload, windowPayload] = await Promise.all([
        fetchBacktestCompare({
          symbol,
          stopLoss,
          takeProfit,
          trailingStop,
          maxHoldBars,
          limit: barLimit,
          costPreset,
        }),
        fetchBacktestWindows({
          strategy,
          symbol,
          stopLoss,
          takeProfit,
          windows: 3,
          limit: barLimit,
          costPreset,
        }),
      ]);
      setResult(payload);
      setCompare(comparePayload);
      setWindows(windowPayload);
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
  }, [barLimit, costPreset, maxHoldBars, refreshLive, stopLoss, strategy, symbol, takeProfit, trailingStop]);

  const runWalkForward = useCallback(async () => {
    setWfoLoading(true);
    try {
      const payload = await fetchBacktestWalkForward({
        strategy,
        symbol,
        stopLoss,
        takeProfit,
        limit: barLimit,
        windows: wfoWindows,
        costPreset,
      });
      setWalkForward(payload);
      message.success(
        `Walk-forward 完成 · OOS Sharpe ${payload.out_of_sample_sharpe.toFixed(2)} · DSR ${(payload.dsr ?? 0).toFixed(2)}${payload.overfit_warning ? " · 过拟合警告" : ""}`,
      );
    } catch (err) {
      message.error(err instanceof Error ? err.message : "Walk-forward 失败");
    } finally {
      setWfoLoading(false);
    }
  }, [barLimit, costPreset, stopLoss, strategy, symbol, takeProfit, wfoWindows]);

  const runAuditSuite = useCallback(async () => {
    setAuditLoading(true);
    try {
      const [robustnessPayload, cpcvPayload] = await Promise.all([
        fetchBacktestRobustness({
          strategy,
          symbol,
          stopLoss,
          takeProfit,
          limit: barLimit,
          costPreset,
        }),
        fetchBacktestCpcv({
          strategy,
          symbol,
          stopLoss,
          takeProfit,
          limit: barLimit,
          costPreset,
        }),
      ]);
      setRobustness(robustnessPayload);
      setCpcv(cpcvPayload);
      message.success(
        `审计完成 · 稳定性 ${(robustnessPayload.parameter_sensitivity.stability_score * 100).toFixed(0)}% · PBO ${(robustnessPayload.pbo.pbo * 100).toFixed(0)}%`,
      );
    } catch (err) {
      message.error(err instanceof Error ? err.message : "稳健性审计失败");
    } finally {
      setAuditLoading(false);
    }
  }, [barLimit, costPreset, stopLoss, strategy, symbol, takeProfit]);

  const runPortfolio = useCallback(async () => {
    setPortfolioLoading(true);
    try {
      const payload = await fetchBacktestPortfolio({
        strategy,
        stopLoss,
        takeProfit,
        limit: barLimit,
      });
      setPortfolio(payload);
      message.success(
        `组合回测完成 · 等权均收益 ${payload.equal_weight_leg_avg_return_pct.toFixed(2)}%`,
      );
    } catch (err) {
      message.error(err instanceof Error ? err.message : "组合回测失败");
    } finally {
      setPortfolioLoading(false);
    }
  }, [barLimit, stopLoss, strategy, takeProfit]);

  const runFactorMine = useCallback(async () => {
    setFactorLoading(true);
    setFactorError(null);
    try {
      const payload = await fetchFactorMine({
        mode: mineMode,
        target: mineTarget,
        riskKind: mineRiskKind,
        symbol,
        limit: barLimit,
        horizon: mineHorizon,
        gpGenerations: 10,
        gpPopulation: 20,
        refresh: refreshLive && symbol !== "WEB3-DEMO/USDT",
      });
      setFactorMine(payload);
      const metric = payload.metric_name ?? "IC";
      message.success(
        `${mineTarget === "risk" ? "风险" : "收益"}因子挖掘完成 · 测试 ${metric} ${(payload.leader?.test_ic ?? 0).toFixed(3)}`,
      );
    } catch (err) {
      const detail = err instanceof Error ? err.message : "因子挖掘失败";
      setFactorError(detail);
      message.error(detail);
    } finally {
      setFactorLoading(false);
    }
  }, [barLimit, mineHorizon, mineMode, mineRiskKind, mineTarget, refreshLive, symbol]);

  const runMinedBacktest = useCallback(async () => {
    const spec = factorMine?.leader?.backtest_spec;
    if (!spec) {
      message.warning("请先运行因子挖掘");
      return;
    }
    setLoading(true);
    setLoadError(null);
    try {
      const payload = await runMinedFactorBacktest({
        backtestSpec: spec,
        symbol,
        limit: barLimit,
        stopLoss,
        takeProfit,
        trailingStop,
        maxHoldBars,
        refresh: refreshLive && symbol !== "WEB3-DEMO/USDT",
      });
      setResult(payload);
      setStrategy("mined_factor");
      message.success(`挖掘因子回测：${payload.total_return_pct.toFixed(2)}%`);
    } catch (err) {
      const detail = err instanceof Error ? err.message : "挖掘因子回测失败";
      setLoadError(detail);
      message.error(detail);
    } finally {
      setLoading(false);
    }
  }, [barLimit, factorMine, maxHoldBars, refreshLive, stopLoss, symbol, takeProfit, trailingStop]);

  useEffect(() => {
    void runBacktest();
    // Initial load only; parameter changes rerun via the action button.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const priceCurve = useMemo(() => chartCandlesToCurve(result), [result]);
  const asideCurve = useMemo(() => equityToCurve(result), [result]);
  const rollingTrades = useMemo(() => result?.trades ?? [], [result]);
  const chartTrades = useMemo(() => rollingTradesToChartTrades(rollingTrades), [rollingTrades]);
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
    ? `${result.symbol} · ${result.kline_type} · ${result.total_candles} 根日K`
    : "—";

  const chartRangeLabel = useMemo(() => {
    if (!result) {
      return windowLabel;
    }
    const from = result.data_from ?? result.chart_candles?.[0]?.date;
    const through = result.data_through ?? result.chart_candles?.at(-1)?.date;
    const source = result.data_source ?? "—";
    const saved = result.data_saved_at?.slice(0, 10) ?? "";
    const warmup = result.warmup_bars ?? 0;
    const sourceLabel =
      source === "live"
        ? "实时拉取"
        : source === "teaching_sample"
          ? "教学 CSV"
          : source === "snapshot"
            ? "离线快照"
            : source;
    return `${from ?? "—"} → ${through ?? "—"} · ${sourceLabel}${saved ? ` · ${saved}` : ""} · 前 ${warmup} 根预热`;
  }, [result, windowLabel]);

  return (
    <TradingPageShell
      eyebrow="Backtest Lab"
      title="策略回测"
      description="对齐 web3-trading 滚动窗口回测：策略注册表、止损止盈、权益曲线与交易明细；数据来自教学样本或离线 K 线。回测是历史模拟，不是真实下单。"
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
          <Select
            value={barLimit}
            onChange={setBarLimit}
            style={{ minWidth: 100 }}
            options={LIMIT_OPTIONS}
            disabled={loading}
          />
          <Select
            value={costPreset}
            onChange={(value) => setCostPreset(value as "teaching" | "realistic" | "perp")}
            style={{ minWidth: 180 }}
            options={COST_PRESET_OPTIONS}
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
          <Checkbox
            checked={refreshLive}
            onChange={(event) => setRefreshLive(event.target.checked)}
            disabled={loading || symbol === "WEB3-DEMO/USDT"}
          >
            拉取最新 K 线
          </Checkbox>
          <Button className="btn-gradient" type="primary" loading={loading} onClick={() => void runBacktest()}>
            <ReloadOutlined /> 运行回测
          </Button>
          <Space>
            <span style={{ color: "var(--qa-text-2)", fontSize: 12 }}>WFO 窗</span>
            <InputNumber min={2} max={5} value={wfoWindows} onChange={(v) => setWfoWindows(Number(v ?? 3))} />
          </Space>
          <Button loading={wfoLoading} onClick={() => void runWalkForward()}>
            Walk-forward
          </Button>
          <Button loading={auditLoading} onClick={() => void runAuditSuite()}>
            稳健性审计
          </Button>
          <Button loading={portfolioLoading} onClick={() => void runPortfolio()}>
            组合回测
          </Button>
        </>
      }
      aside={
        <QuantGlowCard
          title={<SectionHeader title="当前回测" description={windowLabel} />}
          badge={<StatusPill tone="profit">{loading ? "running" : "done"}</StatusPill>}
        >
          <TradingChart
            curve={asideCurve}
            rollingTrades={rollingTrades}
            trades={chartTrades}
            variant="compact"
          />
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
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="回测是什么？"
        description={
          <>
            用历史 K 线按规则模拟交易，留下成交与指标证据；不连接真实账户。
            教学样本固定至 2026-02-20；选 BTC-USDT 可用离线快照（约至今日）或勾选「拉取最新 K 线」。
            完整导读见 docs/samples/backtest-teaching-guide.md。
            事件驱动轨迹与风控拒绝见 <Link to="/risk">风控中心</Link>。
          </>
        }
      />
      <QuantGlowCard
        className="trading-span-12"
        style={{ marginBottom: 16 }}
        title={
          <SectionHeader
            title="GP / ML 因子挖掘"
            description="收益因子（IC→方向回测）· 风险因子（RIC→仓位缩放预览）· 训练/测试切分与过拟合提示"
          />
        }
        badge={
          factorMine?.leader ? (
            <StatusPill tone={Math.abs(factorMine.leader.test_ic ?? 0) >= 0.2 ? "profit" : "neutral"}>
              {factorMine.leader.method?.toUpperCase()}
            </StatusPill>
          ) : undefined
        }
      >
        <Space wrap style={{ marginBottom: 12 }}>
          <Select
            value={mineTarget}
            onChange={setMineTarget}
            style={{ minWidth: 120 }}
            options={[
              { label: "收益因子", value: "return" },
              { label: "风险因子", value: "risk" },
            ]}
            disabled={factorLoading || loading}
          />
          {mineTarget === "risk" && (
            <Select
              value={mineRiskKind}
              onChange={setMineRiskKind}
              style={{ minWidth: 140 }}
              options={[
                { label: "前瞻 |收益|", value: "abs_ret" },
                { label: "前瞻实现波动", value: "realized_vol" },
              ]}
              disabled={factorLoading || loading}
            />
          )}
          <Select
            value={mineMode}
            onChange={setMineMode}
            style={{ minWidth: 120 }}
            options={[
              { label: "GP + ML", value: "both" },
              { label: "仅 GP", value: "gp" },
              { label: "仅 ML", value: "ml" },
            ]}
            disabled={factorLoading || loading}
          />
          <Space>
            <span style={{ color: "var(--qa-text-2)", fontSize: 12 }}>前瞻 bar</span>
            <InputNumber min={1} max={10} value={mineHorizon} onChange={(v) => setMineHorizon(Number(v ?? 1))} />
          </Space>
          <Button loading={factorLoading} onClick={() => void runFactorMine()}>
            运行挖掘
          </Button>
          <Button
            className="btn-gradient"
            type="primary"
            loading={loading}
            disabled={mineTarget === "risk" || !factorMine?.leader?.backtest_spec}
            onClick={() => void runMinedBacktest()}
          >
            用领先因子回测
          </Button>
        </Space>
        {factorError && <Alert type="error" message={factorError} showIcon style={{ marginBottom: 12 }} />}
        {factorMine ? (
          <>
            <div className="trading-metric-grid" style={{ marginBottom: 12 }}>
              <MetricTile
                label="领先因子"
                value={factorMine.leader?.label?.slice(0, 24) ?? "—"}
                subtle={`${factorMine.leader?.method?.toUpperCase() ?? "—"} · 测试 ${factorMine.metric_name ?? "IC"} ${(factorMine.leader?.test_ic ?? 0).toFixed(3)}`}
              />
              <MetricTile
                label={`GP 测试 ${factorMine.metric_name ?? "IC"}`}
                value={factorMine.gp?.test?.ic_mean ?? 0}
                tone="neutral"
                precision={3}
              />
              <MetricTile
                label={`ML 测试 ${factorMine.metric_name ?? "IC"}`}
                value={factorMine.ml?.test?.ic_mean ?? 0}
                tone="neutral"
                precision={3}
              />
              <MetricTile label="训练 bar" value={factorMine.train_bars} kind="qty" tone="neutral" />
              <MetricTile label="测试 bar" value={factorMine.test_bars} kind="qty" tone="neutral" />
            </div>
            {factorMine.mining_target === "risk" && factorMine.risk_application?.sample_tail?.length ? (
              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 10 }}
                message="仓位缩放预览（教学演示）"
                description={
                  <>
                    均值 scale {factorMine.risk_application.mean_position_scale?.toFixed(3) ?? "—"} ·
                    最近 {factorMine.risk_application.sample_tail.length} 根：
                    {factorMine.risk_application.sample_tail.map((row) => (
                      <span key={row.idx} style={{ marginLeft: 8 }}>
                        z={row.risk_z.toFixed(2)}→{row.position_scale.toFixed(2)}
                      </span>
                    ))}
                    <div style={{ marginTop: 6, fontSize: 12, opacity: 0.85 }}>
                      {factorMine.risk_application.note}
                    </div>
                  </>
                }
              />
            ) : null}
            {(factorMine.gp?.expression || factorMine.ml?.formula) && (
              <div className="trading-kv" style={{ marginBottom: 10, fontSize: 12 }}>
                {factorMine.gp?.expression && (
                  <div>
                    <span style={{ color: "var(--qa-text-2)" }}>GP </span>
                    <code>{factorMine.gp.expression}</code>
                  </div>
                )}
                {factorMine.ml?.formula && (
                  <div style={{ marginTop: 6 }}>
                    <span style={{ color: "var(--qa-text-2)" }}>ML </span>
                    <code>{factorMine.ml.formula}</code>
                  </div>
                )}
              </div>
            )}
            {(factorMine.warnings ?? []).map((item) => (
              <Alert key={item} type="warning" message={item} showIcon style={{ marginBottom: 8 }} />
            ))}
            {factorMine.leader?.validation ? (
              <div className="trading-metric-grid" style={{ marginBottom: 8 }}>
                <MetricTile
                  label="五分位 spread"
                  value={factorMine.leader.validation.quintile_spread}
                  tone="neutral"
                  precision={4}
                />
                <MetricTile
                  label="换手 proxy"
                  value={factorMine.leader.validation.turnover_rate}
                  tone="neutral"
                  precision={3}
                />
                <MetricTile
                  label="IC 衰减"
                  value={factorMine.leader.validation.ic_decay}
                  tone="neutral"
                  precision={4}
                />
              </div>
            ) : null}
          </>
        ) : (
          <Alert
            type="info"
            showIcon
            message="尚未运行挖掘"
            description="与上方回测共用标的与 K 线数量。挖掘完成后可一键把领先因子送入滚动回测引擎。"
          />
        )}
      </QuantGlowCard>
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
              title="回测图表"
              description={chartRangeLabel}
            />
          }
        >
          {loadError && <Alert type="warning" message={loadError} showIcon style={{ marginBottom: 14 }} />}
          <div className="trading-kv" style={{ marginBottom: 10, fontSize: 12, color: "var(--qa-text-2)" }}>
            <span>日 K · 左轴权益 / 右轴价格</span>
            <span style={{ marginLeft: 16 }}>▲ 买 / ● 平仓 · 滚轮缩放 · 拖动平移</span>
          </div>
          <BacktestComboChart
            curve={priceCurve}
            equityCurve={result?.equity_curve ?? []}
            trades={rollingTrades}
            height={420}
          />
        </QuantGlowCard>

        <QuantGlowCard
          className="trading-span-12"
          title={
            <SectionHeader
              title="多策略比较"
              description={`统一样本 · 领先 ${compare?.leader ?? "—"} · 落后 ${compare?.laggard ?? "—"}`}
            />
          }
        >
          <Table
            className="trading-ant-table"
            loading={loading}
            pagination={false}
            size="small"
            rowKey="strategy_key"
            dataSource={compare?.strategies ?? []}
            columns={[
              { title: "策略", dataIndex: "strategy" },
              {
                title: "收益",
                dataIndex: "total_return_pct",
                render: (value: number) => (
                  <MonoNumber value={value} kind="pct" tone={value >= 0 ? "profit" : "loss"} showSign />
                ),
              },
              {
                title: "回撤",
                dataIndex: "max_drawdown_pct",
                render: (value: number) => (
                  <MonoNumber value={-value} kind="pct" tone="loss" showSign />
                ),
              },
              { title: "Sharpe", dataIndex: "sharpe_ratio", render: (v: number) => v.toFixed(2) },
              { title: "交易数", dataIndex: "total_trades", width: 80 },
            ]}
          />
        </QuantGlowCard>

        <QuantGlowCard
          className="trading-span-12"
          title={
            <SectionHeader
              title="窗口稳定性"
              description={`${windows?.strategy ?? "—"} · ${windows?.positive_windows ?? 0}/${windows?.num_windows ?? 0} 窗口为正 · ${windows?.stable ? "相对稳定" : "不稳定"}`}
            />
          }
        >
          <Table
            className="trading-ant-table"
            loading={loading}
            pagination={false}
            size="small"
            rowKey="window"
            dataSource={windows?.windows ?? []}
            columns={[
              { title: "窗口", dataIndex: "window", width: 72 },
              { title: "K 数", dataIndex: "bars", width: 72, render: (v: number | undefined, row) => v ?? row.candles ?? "—" },
              {
                title: "收益",
                dataIndex: "total_return_pct",
                render: (value: number) => (
                  <MonoNumber value={value} kind="pct" tone={value >= 0 ? "profit" : "loss"} showSign />
                ),
              },
              {
                title: "回撤",
                dataIndex: "max_drawdown_pct",
                render: (value: number) => (
                  <MonoNumber value={-value} kind="pct" tone="loss" showSign />
                ),
              },
              { title: "交易数", dataIndex: "total_trades", width: 80 },
            ]}
          />
        </QuantGlowCard>

        <QuantGlowCard
          className="trading-span-12"
          title={
            <SectionHeader
              title="Walk-forward 参数优化"
              description={
                walkForward
                  ? `样本内 Sharpe ${walkForward.in_sample_sharpe.toFixed(2)} · 样本外 ${walkForward.out_of_sample_sharpe.toFixed(2)} · DSR ${(walkForward.dsr ?? 0).toFixed(2)} · 试验 ${walkForward.num_trials ?? 0} 次`
                  : "训练窗网格搜参 → 样本外验证 · 点击顶部 Walk-forward 运行"
              }
            />
          }
          badge={
            walkForward?.overfit_warning ? (
              <StatusPill tone="loss">过拟合风险</StatusPill>
            ) : walkForward ? (
              <StatusPill tone="profit">OOS OK</StatusPill>
            ) : undefined
          }
        >
          {walkForward ? (
            <>
              <div className="trading-kv" style={{ marginBottom: 10, fontSize: 12 }}>
                <div>
                  <span style={{ color: "var(--qa-text-2)" }}>最优参数 </span>
                  <code>{JSON.stringify(walkForward.best_params)}</code>
                </div>
              </div>
              <Table
                className="trading-ant-table"
                loading={wfoLoading}
                pagination={false}
                size="small"
                rowKey="window"
                dataSource={walkForward.windows ?? []}
                columns={[
                  { title: "窗", dataIndex: "window", width: 56 },
                  { title: "训练", dataIndex: "trainSize", width: 72 },
                  { title: "OOS", dataIndex: "testSize", width: 72 },
                  { title: "IS Sharpe", dataIndex: "inSampleSharpe", render: (v: number) => v.toFixed(2) },
                  { title: "OOS Sharpe", dataIndex: "outOfSampleSharpe", render: (v: number) => v.toFixed(2) },
                  {
                    title: "OOS 收益",
                    dataIndex: "outOfSampleReturn",
                    render: (value: number) => (
                      <MonoNumber value={value} kind="pct" tone={value >= 0 ? "profit" : "loss"} showSign />
                    ),
                  },
                ]}
              />
            </>
          ) : (
            <Alert type="info" showIcon message="尚未运行 Walk-forward" description="与窗口稳定性不同：此处会在训练段搜索 param_grid 最优 Sharpe，再在样本外段检验。" />
          )}
        </QuantGlowCard>

        <QuantGlowCard
          className="trading-span-12"
          title={
            <SectionHeader
              title="稳健性审计（PBO + 参数敏感性 + CPCV）"
              description={
                robustness
                  ? `稳定性 ${(robustness.parameter_sensitivity.stability_score * 100).toFixed(0)}% · PBO ${(robustness.pbo.pbo * 100).toFixed(0)}% · CPCV 盈利路径 ${(cpcv?.cpcv.profitable_paths_pct ?? 0).toFixed(0)}%`
                  : "点击顶部「稳健性审计」运行参数扰动、过拟合概率与组合 OOS 路径"
              }
            />
          }
          badge={
            robustness?.verdict === "pass" ? (
              <StatusPill tone="profit">PASS</StatusPill>
            ) : robustness ? (
              <StatusPill tone="loss">WARN</StatusPill>
            ) : undefined
          }
        >
          {robustness ? (
            <div className="trading-kv" style={{ fontSize: 12 }}>
              <div>
                <span>参数稳定性</span>
                <strong>{(robustness.parameter_sensitivity.stability_score * 100).toFixed(1)}%</strong>
              </div>
              <div>
                <span>PBO</span>
                <strong>{(robustness.pbo.pbo * 100).toFixed(1)}%</strong>
              </div>
              <div>
                <span>CPCV 中位 Sharpe</span>
                <strong>{(cpcv?.cpcv.sharpe_p50 ?? 0).toFixed(2)}</strong>
              </div>
              <div>
                <span>成本预设</span>
                <strong>{robustness.cost_preset ?? costPreset}</strong>
              </div>
            </div>
          ) : (
            <Alert type="info" showIcon message="尚未运行稳健性审计" description="包含 ±20% 参数扰动、块级 PBO 与教学版 CPCV 分布。" />
          )}
        </QuantGlowCard>

        <QuantGlowCard
          className="trading-span-12"
          title={
            <SectionHeader
              title="等权组合（教学三 leg）"
              description={
                portfolio
                  ? `均收益 ${portfolio.equal_weight_leg_avg_return_pct.toFixed(2)}% · 日收益加总 ${portfolio.equal_weight_daily_return_sum_pct.toFixed(2)}%`
                  : "基于 data/prices.csv 派生三 leg · 点击顶部「组合回测」"
              }
            />
          }
        >
          {portfolio ? (
            <>
              <Table
                className="trading-ant-table"
                loading={portfolioLoading}
                pagination={false}
                size="small"
                rowKey="symbol"
                dataSource={portfolio.legs ?? []}
                columns={[
                  { title: "Leg", dataIndex: "symbol" },
                  {
                    title: "权重",
                    dataIndex: "weight",
                    width: 72,
                    render: (v: number) => `${(v * 100).toFixed(0)}%`,
                  },
                  {
                    title: "收益",
                    dataIndex: "total_return_pct",
                    render: (value: number) => (
                      <MonoNumber value={value} kind="pct" tone={value >= 0 ? "profit" : "loss"} showSign />
                    ),
                  },
                  {
                    title: "回撤",
                    dataIndex: "max_drawdown_pct",
                    render: (value: number) => (
                      <MonoNumber value={-value} kind="pct" tone="loss" showSign />
                    ),
                  },
                  { title: "Sharpe", dataIndex: "sharpe_ratio", render: (v: number) => v.toFixed(2) },
                  { title: "交易", dataIndex: "total_trades", width: 72 },
                ]}
              />
              <Table
                className="trading-ant-table"
                style={{ marginTop: 12 }}
                pagination={false}
                size="small"
                rowKey={(row) => `${row.a}-${row.b}`}
                dataSource={portfolio.pair_correlations ?? []}
                columns={[
                  { title: "A", dataIndex: "a" },
                  { title: "B", dataIndex: "b" },
                  { title: "相关性", dataIndex: "correlation", render: (v: number) => v.toFixed(3) },
                ]}
              />
              {portfolio.diversification_hint ? (
                <Alert type="info" showIcon style={{ marginTop: 10 }} message={portfolio.diversification_hint} />
              ) : null}
            </>
          ) : (
            <Alert type="info" showIcon message="尚未运行组合回测" description="组合层与上方单标的回测独立；使用固定教学 CSV 三 leg，不依赖标的下拉框。" />
          )}
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
