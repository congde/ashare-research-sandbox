import { ReloadOutlined, SafetyOutlined } from "@ant-design/icons";
import { Alert, Button, Input, InputNumber, Select, Table } from "antd";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { fetchAiPicks, fetchSignalAnalysis, fetchTickerStats } from "../../api";
import { useReport } from "../../contexts/ReportContext";
import type { SignalAnalysisPayload } from "../../types";
import {
  MetricTile,
  QuantGlowCard,
  SectionHeader,
  SignalRow,
  StatusPill,
  TradingPageShell,
} from "./TradingPageShell";
import "./live-trading.css";

const CONFIRM_TOKEN = "CONFIRM";
const MAX_USD_DEFAULT = 2;

function baseFromPair(pair: string) {
  return pair.split(/[-/]/)[0]?.toUpperCase() || "BTC";
}

export default function LiveTradingPage() {
  const navigate = useNavigate();
  const { report, loading: reportLoading } = useReport();
  const [symbol, setSymbol] = useState("BTC-USDT");
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [usdAmount, setUsdAmount] = useState(1);
  const [maxUsd, setMaxUsd] = useState(MAX_USD_DEFAULT);
  const [confirmText, setConfirmText] = useState("");
  const [orderResult, setOrderResult] = useState<string>("");
  const [signal, setSignal] = useState<SignalAnalysisPayload | null>(null);
  const [signalLoading, setSignalLoading] = useState(false);
  const [pickSummary, setPickSummary] = useState("-");
  const [lastPrice, setLastPrice] = useState<number | null>(null);

  const riskRules = report?.fusion.risk_rules ?? report?.backtest.risk_rules ?? [];
  const rejections = report?.backtest.risk_rejections ?? [];
  const metrics = report?.backtest.metrics;

  const loadContext = useCallback(async () => {
    setSignalLoading(true);
    try {
      const base = baseFromPair(symbol);
      const [analysis, picks, ticker] = await Promise.all([
        fetchSignalAnalysis(base),
        fetchAiPicks(),
        fetchTickerStats(symbol.includes("-") ? symbol : `${base}-USDT`),
      ]);
      setSignal(analysis.ok ? analysis : null);
      setLastPrice(ticker.ticker?.last ?? analysis.market?.price ?? null);
      const chance = picks.chance?.length ?? 0;
      const funds = picks.funds?.length ?? 0;
      const risk = picks.risk?.length ?? 0;
      setPickSummary(`机会 ${chance} · 资金 ${funds} · 风险 ${risk}`);
    } catch (error) {
      setSignal(null);
      setOrderResult(error instanceof Error ? error.message : "加载信号失败");
    } finally {
      setSignalLoading(false);
    }
  }, [symbol]);

  useEffect(() => {
    void loadContext();
  }, [loadContext]);

  function submitDryRun() {
    if (confirmText.trim().toUpperCase() !== CONFIRM_TOKEN) {
      setOrderResult(`请输入确认词 ${CONFIRM_TOKEN} 后才会模拟提交（对齐 web3-trading 实盘保护）。`);
      return;
    }
    if (usdAmount <= 0) {
      setOrderResult("金额须大于 0。");
      return;
    }
    if (usdAmount > maxUsd) {
      setOrderResult(`超过硬上限 ${maxUsd} USDT，已拒绝（MAX_POSITION_PCT 模拟）。`);
      return;
    }

    const plan = signal?.tradePlan;
    const gate =
      signal?.signal && ["BUY", "SELL"].includes(signal.signal) && side === signal.signal.toLowerCase()
        ? "信号方向一致"
        : "信号未对齐 · 仅 dry-run";

    setOrderResult(
      [
        `[DRY-RUN] ${side.toUpperCase()} ${symbol} ≈ ${usdAmount} USDT`,
        lastPrice ? `参考价 ${lastPrice}` : "无实时报价",
        `门禁: ${gate}`,
        plan?.stopLoss ? `计划止损 ${plan.stopLoss}` : "无 tradePlan 止损",
        "未连接交易所 · 订单未送出",
      ].join(" · "),
    );
  }

  return (
    <TradingPageShell
      eyebrow="Live Trading Console"
      title="模拟交易控制台"
      description="布局参考 web3-trading /live-trading：信号门禁、CONFIRM 保护与 RiskManager 规则栈；本页仅 dry-run，不会提交真实订单。"
      actions={
        <>
          <Button icon={<ReloadOutlined />} onClick={() => void loadContext()} loading={signalLoading}>
            刷新
          </Button>
          <Button icon={<SafetyOutlined />} onClick={() => navigate("/risk")}>
            风控中心
          </Button>
        </>
      }
    >
      <Alert
        className="live-trading-warning"
        type="warning"
        showIcon
        message="模拟交易保护"
        description="教学沙箱不接 web3交易所 写接口。CONFIRM 仅用于演练 web3-trading 实盘流程；真实下单需独立部署上游并补齐 RiskState 持久化。"
      />

      <section className="trading-grid">
        <QuantGlowCard className="trading-span-8">
          <SectionHeader title="信号门禁" description="ValueScan + 沙箱多周期分析" />
          <div className="live-trading-toolbar">
            <div className="live-trading-field">
              <label>币种</label>
              <Select
                value={symbol}
                onChange={setSymbol}
                options={[
                  { value: "BTC-USDT", label: "BTC-USDT" },
                  { value: "ETH-USDT", label: "ETH-USDT" },
                  { value: "WEB3-DEMO/USDT", label: "WEB3-DEMO (样本)" },
                ]}
                style={{ minWidth: 160 }}
              />
            </div>
            <div className="live-trading-field">
              <label>VS 追踪</label>
              <span className="live-trading-meta">{pickSummary}</span>
            </div>
          </div>
          {signal ? (
            <div className="trading-list" style={{ marginTop: 16 }}>
              <SignalRow
                title={signal.signalLabel || signal.signal || "HOLD"}
                meta={signal.summary || "暂无摘要"}
                badge={
                  <StatusPill tone={signal.signal === "BUY" ? "profit" : signal.signal === "SELL" ? "loss" : "ai"}>
                    {signal.confidence != null ? `${signal.confidence}%` : "—"}
                  </StatusPill>
                }
              />
              {signal.tradePlan && (
                <div className="live-trading-plan">
                  入场 {signal.tradePlan.entryLow}–{signal.tradePlan.entryHigh} · 止损 {signal.tradePlan.stopLoss} ·
                  R:R {signal.tradePlan.rr1}
                </div>
              )}
            </div>
          ) : (
            <div className="live-trading-meta" style={{ marginTop: 16 }}>
              {signalLoading ? "加载信号中…" : "暂无信号数据"}
            </div>
          )}
        </QuantGlowCard>

        <QuantGlowCard className="trading-span-4">
          <SectionHeader title="回测账本" description="离线 MA 策略样本" />
          <div className="trading-metric-grid">
            <MetricTile label="策略收益" value={metrics?.strategy_return_pct ?? 0} kind="pct" tone="profit" showSign />
            <MetricTile label="最终权益" value={metrics?.final_equity ?? 0} kind="usd" />
            <MetricTile label="成交笔数" value={metrics?.trade_count ?? 0} />
            <MetricTile label="运行时拦截" value={rejections.length} tone="loss" />
          </div>
        </QuantGlowCard>

        <QuantGlowCard className="trading-span-6">
          <SectionHeader title="现货 dry-run" description="对齐 web3-trading 小额实盘表单" />
          <div className="live-trading-form">
            <div className="live-trading-field">
              <label>交易对</label>
              <Input value={symbol} onChange={(e) => setSymbol(e.target.value)} />
            </div>
            <div className="live-trading-field">
              <label>方向</label>
              <Select
                value={side}
                onChange={setSide}
                options={[
                  { value: "buy", label: "buy" },
                  { value: "sell", label: "sell" },
                ]}
              />
            </div>
            <div className="live-trading-field">
              <label>约 USDT</label>
              <InputNumber min={0.1} step={0.1} value={usdAmount} onChange={(v) => setUsdAmount(Number(v) || 0)} />
            </div>
            <div className="live-trading-field">
              <label>硬上限 USDT</label>
              <InputNumber min={0.1} step={0.1} value={maxUsd} onChange={(v) => setMaxUsd(Number(v) || MAX_USD_DEFAULT)} />
            </div>
            <div className="live-trading-field live-trading-field--wide">
              <label>确认词</label>
              <Input placeholder={CONFIRM_TOKEN} value={confirmText} onChange={(e) => setConfirmText(e.target.value)} />
            </div>
          </div>
          <div className="live-trading-actions">
            <Button type="primary" className="btn-gradient" onClick={submitDryRun}>
              模拟提交
            </Button>
          </div>
          {orderResult && <div className="live-trading-output">{orderResult}</div>}
        </QuantGlowCard>

        <QuantGlowCard className="trading-span-6">
          <SectionHeader title="RiskManager 规则栈" description="ai-trading MVP · 首条命中短路" />
          <div className="trading-list">
            {riskRules.map((ruleId) => (
              <SignalRow
                key={ruleId}
                title={ruleId}
                meta="回测引擎 pre-trade 检查"
                badge={<StatusPill tone="ai">active</StatusPill>}
              />
            ))}
          </div>
        </QuantGlowCard>

        <QuantGlowCard className="trading-span-12" title={<SectionHeader title="最近回测成交" />}>
          <Table
            className="trading-ant-table"
            pagination={false}
            rowKey={(row) => `${row.date}-${row.action}-${row.price}`}
            dataSource={report?.backtest.trades ?? []}
            loading={reportLoading}
            locale={{ emptyText: "暂无成交" }}
            columns={[
              { title: "日期", dataIndex: "date" },
              { title: "动作", dataIndex: "action" },
              { title: "价格", dataIndex: "price" },
            ]}
          />
        </QuantGlowCard>
      </section>
    </TradingPageShell>
  );
}
