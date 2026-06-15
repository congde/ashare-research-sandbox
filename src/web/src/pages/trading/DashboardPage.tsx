import { ArrowRightOutlined, RadarChartOutlined, ReloadOutlined, SafetyOutlined } from "@ant-design/icons";
import { Button, Progress } from "antd";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  fetchAiPicks,
  fetchMarketCandles,
  fetchOnchain,
  fetchRuntimeConfig,
  fetchSectorFund,
} from "../../api";
import TradingChart from "../../components/charts/TradingChart";
import { useReport } from "../../contexts/ReportContext";
import type { CurvePoint } from "../../types";
import {
  MetricTile,
  QuantGlowCard,
  SectionHeader,
  SignalRow,
  StatusPill,
  TradingPageShell,
} from "./TradingPageShell";

function formatDataMode(source?: string) {
  if (source === "web3-trading-upstream") {
    return "上游代理";
  }
  if (source === "live") {
    return "直连 API";
  }
  if (source === "fixture" || source === "snapshot") {
    return "离线样本";
  }
  return source || "离线样本";
}

export default function DashboardPage() {
  const navigate = useNavigate();
  const { report, loading, short, long } = useReport();
  const [fearGreed, setFearGreed] = useState("-");
  const [sectorLead, setSectorLead] = useState("-");
  const [pickCount, setPickCount] = useState(0);
  const [dataMode, setDataMode] = useState("离线样本");
  const [liveCurve, setLiveCurve] = useState<CurvePoint[]>([]);
  const [liveSymbol, setLiveSymbol] = useState("");

  useEffect(() => {
    void (async () => {
      try {
        const cfg = await fetchRuntimeConfig();
        const pair = cfg.symbols?.primary_pair;
        const [onchain, sector, picks, candles] = await Promise.all([
          fetchOnchain("BTC"),
          fetchSectorFund(1),
          fetchAiPicks(),
          fetchMarketCandles(short, long, pair),
        ]);

        const fg = onchain.marketSentiment?.fearGreed;
        if (fg?.value != null) {
          setFearGreed(`${fg.value}${fg.label ? ` · ${fg.label}` : ""}`);
        }

        const sectors = sector.sectors || [];
        const top = [...sectors].sort((a, b) => {
          const inflow = (item: typeof a) =>
            Number((item.categoriesTradeDataList || []).find((x) => x.timeRange === "h1")?.tradeInflow || 0);
          return inflow(b) - inflow(a);
        })[0];
        setSectorLead(top?.tagsSimplified || top?.tag || "-");
        setPickCount((picks.chance?.length || 0) + (picks.funds?.length || 0) + (picks.risk?.length || 0));

        const marketSource = candles.source || picks.source;
        setDataMode(formatDataMode(marketSource));
        if (candles.curve?.length) {
          setLiveCurve(candles.curve);
          setLiveSymbol(candles.symbol || pair || "");
        }
      } catch {
        /* optional dashboard widgets */
      }
    })();
  }, [long, short]);

  const metrics = report?.backtest.metrics;
  const backtestCurve = report?.backtest.curve ?? [];
  const trades = report?.backtest.trades ?? [];
  const riskChecks = report?.risk_checks ?? [];

  const chartCurve = liveCurve.length ? liveCurve : backtestCurve;
  const chartTrades = liveCurve.length ? [] : trades;
  const chartDescription = liveCurve.length
    ? `${liveSymbol || "web3交易所"} · Lightweight Charts`
    : "WEB3-DEMO 固定样本回测";
  const chartLive = liveCurve.length > 0;

  return (
    <TradingPageShell
      eyebrow="Quant Trading Workspace"
      title="量化交易工作台"
      description="教学沙箱负责回测、DSL 验收与内置机会雷达；数据来自 web3交易所 直连、ValueScan 或离线样本，无需单独启动 web3-trading。"
      actions={
        <>
          <Button className="btn-gradient" type="primary" icon={<RadarChartOutlined />} onClick={() => navigate("/radar")}>
            机会雷达
          </Button>
          <Button className="btn-gradient" type="primary" onClick={() => navigate("/live-trading")}>
            模拟交易
          </Button>
          <Button className="btn-gradient" type="primary" onClick={() => navigate("/backtests")}>
            打开回测 <ArrowRightOutlined />
          </Button>
          <Button icon={<ReloadOutlined />} onClick={() => navigate("/data-sources")}>
            数据源
          </Button>
          <Button onClick={() => navigate("/risk")}>查看风控</Button>
        </>
      }
      aside={
        <QuantGlowCard
          variant="live"
          title={<SectionHeader title="行情 / 回测" description={chartDescription} />}
          badge={
            <StatusPill tone={chartLive ? "profit" : "ai"}>
              {loading ? "Loading" : chartLive ? "Live" : "Sandbox"}
            </StatusPill>
          }
        >
          <TradingChart curve={chartCurve} trades={chartTrades} variant="compact" />
          <div className="trading-chart-legend">
            <span>
              <i style={{ background: "#22d3ee" }} /> MA 短
            </span>
            <span>
              <i style={{ background: "#f59e0b" }} /> MA 长
            </span>
            {!liveCurve.length ? (
              <span>
                <i style={{ background: "#00ffa3" }} /> 回测买卖点
              </span>
            ) : null}
          </div>
          <div className="trading-kv">
            <div>
              <span>图表数据</span>
              <strong>{dataMode}</strong>
            </div>
            <div>
              <span>Sharpe</span>
              <strong>{metrics?.sharpe_ratio?.toFixed(2) ?? "—"}</strong>
            </div>
            <div>
              <span>回测引擎</span>
              <strong>{report?.backtest.engine ?? "—"}</strong>
            </div>
            <div>
              <span>研究资产</span>
              <strong>{report?.research.company ?? "—"}</strong>
            </div>
          </div>
        </QuantGlowCard>
      }
    >
      <section className="trading-grid">
        <QuantGlowCard className="trading-span-12">
          <SectionHeader title="市场背景" description="内置 dashboard API · 直连或离线 fallback" />
          <div className="ds-context-row">
            <div className="ds-context-chip">
              <span className="ds-context-label">恐贪指数</span>
              <span className="ds-context-value">{fearGreed}</span>
            </div>
            <div className="ds-context-chip">
              <span className="ds-context-label">领涨板块</span>
              <span className="ds-context-value">{sectorLead}</span>
            </div>
            <div className="ds-context-chip">
              <span className="ds-context-label">ValueScan 智选</span>
              <span className="ds-context-value">{pickCount} 条</span>
            </div>
          </div>
        </QuantGlowCard>

        <QuantGlowCard className="trading-span-12">
          <div className="trading-metric-grid">
            <MetricTile
              label="策略收益率"
              value={metrics?.strategy_return_pct ?? 0}
              kind="pct"
              tone="profit"
              showSign
              subtle="双均线 · 固定样本"
            />
            <MetricTile
              label="买入持有"
              value={metrics?.buy_hold_return_pct ?? 0}
              kind="pct"
              tone="neutral"
              showSign
            />
            <MetricTile
              label="最大回撤"
              value={metrics?.maximum_drawdown_pct ?? 0}
              kind="pct"
              tone="loss"
              showSign
            />
            <MetricTile label="Sharpe" value={metrics?.sharpe_ratio ?? 0} tone="neutral" precision={2} />
          </div>
        </QuantGlowCard>

        <QuantGlowCard
          className="trading-span-7"
          title={<SectionHeader title="教学入口" description="对齐 ai-trading 工作台分区" />}
        >
          <div className="trading-list">
            <SignalRow
              title="机会雷达"
              meta="规则扫描高流动性标的 · 左侧菜单「雷达」"
              badge={
                <Button size="small" type="primary" onClick={() => navigate("/radar")}>
                  打开
                </Button>
              }
            />
            <SignalRow
              title="数据源"
              meta="web3交易所 / ValueScan / DexScan 或离线 fixture"
              badge={
                <Button size="small" onClick={() => navigate("/data-sources")}>
                  打开
                </Button>
              }
            />
            <SignalRow
              title="回测详情"
              meta="双均线参数、权益曲线、交易记录"
              badge={
                <Button size="small" onClick={() => navigate("/backtests")}>
                  回测
                </Button>
              }
            />
            <SignalRow
              title="策略 DSL"
              meta="import 安全与前视偏差校验"
              badge={
                <Button size="small" onClick={() => navigate("/strategy")}>
                  校验
                </Button>
              }
            />
          </div>
        </QuantGlowCard>

        <QuantGlowCard
          className="trading-span-5"
          title={<SectionHeader title="风险覆盖" description="RiskManager 运行时 + 回测后复核" />}
          badge={<SafetyOutlined style={{ color: "var(--qa-neutral)" }} />}
        >
          <div className="trading-list">
            {riskChecks.length ? (
              riskChecks.map((item) => (
                <div key={item.rule_id}>
                  <SignalRow
                    title={item.rule_id}
                    meta={item.message}
                    badge={
                      <StatusPill tone={item.severity === "warning" ? "ai" : "loss"}>
                        {item.severity}
                      </StatusPill>
                    }
                  />
                  <Progress
                    percent={100}
                    showInfo={false}
                    strokeColor="var(--qa-neutral)"
                    trailColor="rgba(255,255,255,0.08)"
                  />
                </div>
              ))
            ) : (
              <SignalRow
                title="未触发规则"
                meta="当前参数组合通过模拟风控"
                badge={<StatusPill tone="profit">通过</StatusPill>}
              />
            )}
          </div>
        </QuantGlowCard>

        <QuantGlowCard className="trading-span-12">
          <SectionHeader title="运行边界" description="教学项目，不构成投资建议" />
          <div className="trading-list">
            {(report?.warnings ?? []).map((warning) => (
              <SignalRow key={warning} title={warning} meta="固定离线样本" />
            ))}
          </div>
        </QuantGlowCard>
      </section>
    </TradingPageShell>
  );
}
