import { ReloadOutlined, SearchOutlined } from "@ant-design/icons";
import { Button, Input, Select, Switch } from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { fetchKlineAnalysis, fetchMarketTickers, pollLlmSignalAnalysis, submitLlmSignalAnalysis } from "../../api";
import { KlineAnalysisChart } from "../../components/charts/KlineAnalysisChart";
import { useReport } from "../../contexts/ReportContext";
import type { KlineAnalysisPayload, SignalAnalysisPayload } from "../../types";
import { QuantGlowCard, SectionHeader, SignalRow, StatusPill, TradingPageShell } from "../trading/TradingPageShell";
import "./research.css";

const KLINE_TYPES = [
  { value: "15min", label: "15 分钟" },
  { value: "1hour", label: "1 小时" },
  { value: "4hour", label: "4 小时" },
  { value: "1day", label: "日线" },
];

const TF_LABELS: Record<string, string> = {
  "15min": "15min",
  "1hour": "1h",
  "4hour": "4h",
  "1day": "1day",
};

const LLM_MODELS = [
  { value: "deepseek/deepseek-v4-pro", label: "DeepSeek V4 Pro" },
  { value: "deepseek/deepseek-v4-flash", label: "DeepSeek V4 Flash" },
  { value: "deepseek/deepseek-reasoner", label: "DeepSeek Reasoner" },
];

function baseSymbol(raw: string) {
  const value = raw.trim().toUpperCase().replace(/\//g, "-");
  return value.includes("-") ? value.split("-")[0] : value.replace(/-.*/, "");
}

function formatPrice(value?: number | null) {
  if (value == null || Number.isNaN(value)) return "—";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(2)}K`;
  return value.toFixed(2);
}

function formatPct(value?: number | null, scale = 1) {
  if (value == null || Number.isNaN(value)) return "—";
  const pct = value * scale;
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
}

function signalTone(signal?: string) {
  const value = String(signal || "").toUpperCase();
  if (value.includes("BUY")) return "profit" as const;
  if (value.includes("SELL")) return "loss" as const;
  return "neutral" as const;
}

function trendTone(trendKey?: string) {
  if (!trendKey) return "neutral";
  if (trendKey.includes("bull")) return "bullish";
  if (trendKey.includes("bear")) return "bearish";
  return "neutral";
}

export default function ResearchPage() {
  const { report, loading } = useReport();
  const research = report?.research;
  const [searchParams, setSearchParams] = useSearchParams();

  const [symbolInput, setSymbolInput] = useState(searchParams.get("symbol") || "BTC");
  const [symbol, setSymbol] = useState(baseSymbol(searchParams.get("symbol") || "BTC"));
  const [klineType, setKlineType] = useState(searchParams.get("type") || "1hour");
  const [showMa20, setShowMa20] = useState(true);
  const [showMa60, setShowMa60] = useState(true);
  const [showVolume, setShowVolume] = useState(true);
  const [showPriceLines, setShowPriceLines] = useState(true);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [llmModel, setLlmModel] = useState(searchParams.get("model") || "deepseek/deepseek-v4-pro");

  const [kline, setKline] = useState<KlineAnalysisPayload | null>(null);
  const [signal, setSignal] = useState<SignalAnalysisPayload | null>(null);
  const [tickerMeta, setTickerMeta] = useState<{
    price?: number;
    changeRate?: number;
    high?: number;
    low?: number;
    volValue?: number;
  } | null>(null);
  const [klineBusy, setKlineBusy] = useState(false);
  const [signalBusy, setSignalBusy] = useState(false);
  const [signalStatus, setSignalStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [signalError, setSignalError] = useState<string | null>(null);
  const pollTimerRef = useRef<number | null>(null);

  const pair = `${symbol}-USDT`;

  const stopSignalPoll = useCallback(() => {
    if (pollTimerRef.current != null) {
      window.clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const loadKline = useCallback(async () => {
    setKlineBusy(true);
    setError(null);
    try {
      const [klinePayload, tickersPayload] = await Promise.all([
        fetchKlineAnalysis(pair, klineType),
        fetchMarketTickers(300),
      ]);
      setKline(klinePayload);
      const row = (tickersPayload.tickers || []).find(
        (item) => String((item as { symbol?: string }).symbol || "").toUpperCase() === pair,
      ) as { last?: number; changeRate?: number; high?: number; low?: number; volValue?: number } | undefined;
      setTickerMeta(
        row
          ? {
              price: Number(row.last),
              changeRate: Number(row.changeRate),
              high: Number(row.high),
              low: Number(row.low),
              volValue: Number(row.volValue),
            }
          : {
              price: klinePayload.metrics?.latestClose,
              changeRate: (klinePayload.metrics?.candleChangeRatePct ?? 0) / 100,
            },
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载 K 线失败");
    } finally {
      setKlineBusy(false);
    }
  }, [pair, klineType]);

  const loadLlmSignal = useCallback(async () => {
    stopSignalPoll();
    setSignalBusy(true);
    setSignalError(null);
    setSignalStatus(`正在提交 ${symbol} LLM 信号分析任务...`);
    try {
      const submit = await submitLlmSignalAnalysis(symbol, llmModel);
      if (submit.taskId) {
        let polls = 0;
        const runPoll = async () => {
          polls += 1;
          if (polls > 200) {
            stopSignalPoll();
            setSignalBusy(false);
            setSignalStatus(null);
            setSignalError("LLM 分析超时，请重试");
            return;
          }
          if (polls % 2 === 0) {
            setSignalStatus(`LLM 信号分析进行中（约 ${polls * 3}s）…`);
          }
          const result = await pollLlmSignalAnalysis(submit.taskId!);
          if (result.status === "done" && result.data) {
            stopSignalPoll();
            setSignal(result.data);
            setSignalBusy(false);
            setSignalStatus(null);
            return;
          }
          if (result.status === "failed") {
            stopSignalPoll();
            setSignalBusy(false);
            setSignalStatus(null);
            setSignalError(result.message || "LLM 分析失败");
          }
        };
        await runPoll();
        pollTimerRef.current = window.setInterval(() => {
          void runPoll();
        }, 3000);
        return;
      }
      if (submit.signal || submit.signalLabel) {
        setSignal(submit);
        setSignalStatus(null);
        setSignalBusy(false);
        return;
      }
      throw new Error(submit.message || "未收到 LLM 信号结果");
    } catch (err) {
      setSignalBusy(false);
      setSignalStatus(null);
      setSignalError(err instanceof Error ? err.message : "LLM 信号分析失败");
    }
  }, [llmModel, stopSignalPoll, symbol]);

  const applySymbol = useCallback(() => {
    const next = baseSymbol(symbolInput || "BTC");
    setSymbol(next);
    const params = new URLSearchParams(searchParams);
    params.set("symbol", next);
    params.set("type", klineType);
    params.set("model", llmModel);
    setSearchParams(params, { replace: true });
  }, [symbolInput, klineType, llmModel, searchParams, setSearchParams]);

  useEffect(() => {
    void loadKline();
  }, [loadKline]);

  useEffect(() => {
    void loadLlmSignal();
    return () => stopSignalPoll();
  }, [loadLlmSignal, stopSignalPoll]);

  useEffect(() => {
    if (!autoRefresh) return undefined;
    const timer = window.setInterval(() => {
      void loadLlmSignal();
    }, 120_000);
    return () => window.clearInterval(timer);
  }, [autoRefresh, loadLlmSignal]);

  const metrics = kline?.metrics;
  const verdict = kline?.verdict;
  const price = tickerMeta?.price ?? metrics?.latestClose;

  const trendBadges = useMemo(() => {
    const bundle = signal?.kline || {};
    return Object.entries(bundle).map(([tf, row]) => ({
      tf,
      label: TF_LABELS[tf] || tf,
      trend: row.trend,
      tone: trendTone(row.trendKey),
    }));
  }, [signal?.kline]);

  return (
    <TradingPageShell
      eyebrow="Research / Analysis"
      title="市场情报与分析"
      description="币种 K 线分析 + 规则信号引擎（教学沙箱）。离线模式下使用快照数据，不代表真实交易建议。"
      actions={
        <div className="research-signal-actions">
          <Input
            value={symbolInput}
            onChange={(event) => setSymbolInput(event.target.value)}
            onPressEnter={applySymbol}
            prefix={<SearchOutlined />}
            style={{ width: 120 }}
            placeholder="BTC"
          />
          <Button type="primary" onClick={applySymbol}>
            应用
          </Button>
          <Button
            icon={<ReloadOutlined />}
            loading={klineBusy || signalBusy}
            onClick={() => {
              void loadKline();
              void loadLlmSignal();
            }}
          >
            刷新
          </Button>
        </div>
      }
    >
      {error && (
        <QuantGlowCard className="trading-span-12" title={<SectionHeader title="加载错误" />}>
          <p>{error}</p>
        </QuantGlowCard>
      )}

      <section className="trading-grid">
        <QuantGlowCard
          className="trading-span-12"
          title={<SectionHeader title="币种 K 线" description={`${pair} · ${kline?.trend ?? "加载中"}`} />}
          badge={<StatusPill tone="neutral">{kline?.source ?? "—"}</StatusPill>}
        >
          <div className="research-analysis-toolbar">
            <Select
              value={klineType}
              style={{ width: 120 }}
              options={KLINE_TYPES}
              onChange={(value) => {
                setKlineType(value);
                const params = new URLSearchParams(searchParams);
                params.set("type", value);
                setSearchParams(params, { replace: true });
              }}
            />
            <label>
              <input type="checkbox" checked={showMa20} onChange={(e) => setShowMa20(e.target.checked)} />
              MA20
            </label>
            <label>
              <input type="checkbox" checked={showMa60} onChange={(e) => setShowMa60(e.target.checked)} />
              MA60
            </label>
            <label>
              <input type="checkbox" checked={showVolume} onChange={(e) => setShowVolume(e.target.checked)} />
              成交量
            </label>
            <label>
              <input type="checkbox" checked={showPriceLines} onChange={(e) => setShowPriceLines(e.target.checked)} />
              显示价位线
            </label>
          </div>

          <div className="research-stat-row">
            <div className="research-stat-card">
              <div className="label">当前币种</div>
              <div className="value">{symbol}</div>
            </div>
            <div className="research-stat-card">
              <div className="label">最新价格</div>
              <div className="value">{formatPrice(price)}</div>
            </div>
            <div className="research-stat-card">
              <div className="label">24h 涨跌</div>
              <div className="value" style={{ color: (tickerMeta?.changeRate ?? 0) >= 0 ? "#16a34a" : "#dc2626" }}>
                {formatPct(tickerMeta?.changeRate)}
              </div>
            </div>
            <div className="research-stat-card">
              <div className="label">24h 高低</div>
              <div className="value">
                {formatPrice(tickerMeta?.high)} / {formatPrice(tickerMeta?.low)}
              </div>
            </div>
            <div className="research-stat-card">
              <div className="label">24h 成交额</div>
              <div className="value">{formatPrice(tickerMeta?.volValue)}</div>
            </div>
            <div className="research-stat-card">
              <div className="label">交易对</div>
              <div className="value">{pair}</div>
            </div>
          </div>

          <KlineAnalysisChart
            candles={kline?.candles ?? []}
            tradePlan={showPriceLines ? signal?.tradePlan : null}
            showMa20={showMa20}
            showMa60={showMa60}
            showVolume={showVolume}
            showPriceLines={showPriceLines}
            height={440}
          />

          <dl className="research-kline-metrics">
            <div>
              <dt>RSI</dt>
              <dd>{metrics?.rsi ?? "—"}</dd>
            </div>
            <div>
              <dt>支撑(20)</dt>
              <dd>{formatPrice(metrics?.support20)}</dd>
            </div>
            <div>
              <dt>阻力(20)</dt>
              <dd>{formatPrice(metrics?.resistance20)}</dd>
            </div>
            <div>
              <dt>波动率</dt>
              <dd>{metrics?.volatilityPct != null ? `${metrics.volatilityPct.toFixed(2)}%` : "—"}</dd>
            </div>
            <div>
              <dt>区间位置</dt>
              <dd>{metrics?.rangePositionPct != null ? `${metrics.rangePositionPct.toFixed(1)}%` : "—"}</dd>
            </div>
            <div>
              <dt>行情状态</dt>
              <dd>{metrics?.regime ?? "—"}</dd>
            </div>
          </dl>

          {verdict && (
            <div className="research-verdict">
              <strong>
                {verdict.actionLabel} · 得分 {verdict.score} · 置信度 {verdict.confidence}%
              </strong>
              <ul>
                {(verdict.reasons || []).map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          )}
        </QuantGlowCard>

        <QuantGlowCard
          className="trading-span-12"
          title={<SectionHeader title="LLM 信号分析" description="与 web3-trading /analysis 对齐 · DeepSeek V4 Pro 异步分析" />}
          badge={
            <StatusPill tone={signalTone(signal?.signal)}>
              {signalBusy ? "分析中" : signal?.signalLabel ?? "未就绪"}
            </StatusPill>
          }
        >
          {signalStatus && (
            <div className="research-verdict" style={{ marginBottom: 12 }}>
              {signalStatus}
            </div>
          )}
          {signalError && (
            <div className="research-verdict" style={{ marginBottom: 12, color: "#b91c1c" }}>
              {signalError}
            </div>
          )}
          <div className="research-signal-hero">
            <div>
              <div className="research-signal-price">
                {formatPrice(signal?.market?.price ?? price)}
                <span style={{ fontSize: 14, marginLeft: 8, color: (signal?.market?.changeRate24h ?? 0) >= 0 ? "#16a34a" : "#dc2626" }}>
                  {signal?.market?.changeRate24h != null
                    ? `${signal.market.changeRate24h >= 0 ? "+" : ""}${signal.market.changeRate24h.toFixed(2)}%`
                    : ""}
                </span>
              </div>
              <div style={{ marginTop: 6, color: "#64748b", fontSize: 13 }}>
                置信度 {signal?.confidence?.toFixed(1) ?? "—"}% · 综合得分 {signal?.score != null ? `${signal.score >= 0 ? "+" : ""}${signal.score}` : "—"}
              </div>
            </div>
            <div className="research-signal-actions">
              <Select
                value={llmModel}
                style={{ width: 180 }}
                options={LLM_MODELS}
                onChange={(value) => {
                  setLlmModel(value);
                  const params = new URLSearchParams(searchParams);
                  params.set("model", value);
                  setSearchParams(params, { replace: true });
                }}
              />
              <Button type="primary" loading={signalBusy} onClick={() => void loadLlmSignal()}>
                生成信号
              </Button>
              <span>定时刷新</span>
              <Switch checked={autoRefresh} onChange={setAutoRefresh} />
            </div>
          </div>

          <div className="research-trend-badges">
            {trendBadges.map((item) => (
              <span key={item.tf} className={`research-trend-badge ${item.tone}`}>
                {item.label} · {item.trend}
              </span>
            ))}
          </div>

          {signal?.summary && (
            <div className="research-verdict">
              <strong>核心结论</strong>
              <p style={{ margin: "8px 0 0" }}>{signal.summary}</p>
            </div>
          )}

          <div className="research-logic-flow">
            {(signal?.logicFlow || []).map((step) => (
              <div key={step.step} className="research-logic-step">
                <h4>
                  {step.step}. {step.title}
                </h4>
                {step.status && <p>{step.status}</p>}
                {step.detail && <p>{step.detail}</p>}
                {step.note && <p>{step.note}</p>}
                {step.summary && <p>{step.summary}</p>}
                {step.dimensions && (
                  <div className="research-dimension-list">
                    {step.dimensions.map((dim) => (
                      <div key={dim.name} className="research-dimension-row">
                        <span>
                          {dim.name} · {dim.bias}
                        </span>
                        <span>{dim.score}</span>
                      </div>
                    ))}
                  </div>
                )}
                {step.badges && (
                  <div className="research-trend-badges" style={{ marginTop: 8 }}>
                    {step.badges.map((badge) => (
                      <span key={badge} className="research-trend-badge neutral">
                        {badge}
                      </span>
                    ))}
                  </div>
                )}
                {(step.rr1 != null || step.rr2 != null) && (
                  <p style={{ marginTop: 8 }}>
                    RR1 {step.rr1 ?? "—"} · RR2 {step.rr2 ?? "—"}
                  </p>
                )}
              </div>
            ))}
          </div>

          <div className="research-signal-footer">
            <span>市场状态 · {signal?.analysis?.marketState ?? "—"}</span>
            <span>执行准备度 · {signal?.analysis?.executionReadiness ?? "—"}</span>
            <span>模型 · {signal?.engineMeta?.displayModel ?? signal?.engineMeta?.model ?? "DeepSeek V4 Pro"}</span>
            <span>恐贪指数 · {signal?.onchainMetrics?.fearGreed ?? "—"}</span>
          </div>
        </QuantGlowCard>
      </section>

      <section className="trading-grid research-intel-section">
        <QuantGlowCard
          className="trading-span-7"
          title={
            <SectionHeader
              title={research?.company ?? "研究摘要"}
              description="Facts · Interpretation · Unknowns"
            />
          }
          badge={<StatusPill tone="neutral">{loading ? "Loading" : "Fixed sample"}</StatusPill>}
        >
          <div className="trading-list">
            {(research?.facts ?? []).map((item) => (
              <SignalRow
                key={item.source_id}
                title={item.claim}
                meta={`来源 ${item.source_id}`}
                badge={<StatusPill tone="neutral">{item.source_id}</StatusPill>}
              />
            ))}
            <SignalRow title="解释" meta={research?.interpretation ?? "加载中..."} />
            {(research?.unknowns ?? []).map((item) => (
              <SignalRow key={item} title="仍然未知" meta={item} />
            ))}
          </div>
        </QuantGlowCard>

        <QuantGlowCard
          className="trading-span-5"
          title={<SectionHeader title="来源卡" description="可追溯证据链" />}
        >
          <div className="trading-list">
            {(research?.sources ?? []).map((source) => (
              <SignalRow
                key={source.id}
                title={`${source.id} · ${source.title}`}
                meta={`${source.date} · ${source.evidence}`}
              />
            ))}
          </div>
        </QuantGlowCard>
      </section>
    </TradingPageShell>
  );
}
