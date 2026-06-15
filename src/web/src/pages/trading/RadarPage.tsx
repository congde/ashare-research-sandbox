import { ReloadOutlined } from "@ant-design/icons";
import { Button } from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  fetchMarketTickers,
  fetchOnchain,
  fetchOpportunityScan,
  fetchSectorFund,
  fetchTickerStats,
} from "../../api";
import type { OpportunityItem, OpportunityScanPayload } from "../../types";
import { StatusPill, TradingPageShell } from "./TradingPageShell";
import "./radar.css";

interface TickerRow {
  symbol?: string;
  changeRate?: number;
  last?: number;
}

function formatVolume(value: number) {
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)}B`;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value.toFixed(0);
}

function formatSource(source?: string, engine?: string) {
  if (source === "web3-trading-upstream") return "上游代理";
  if (source === "snapshot") return "离线样本";
  if (engine === "sandbox-rule-based") return "规则引擎 · 直连";
  if (source === "live") return "直连 API";
  return source || "沙箱";
}

function signalClass(signal?: string) {
  const value = String(signal || "").toUpperCase();
  if (value === "BUY") return "buy";
  if (value === "WEAK_BUY") return "weak-buy";
  if (value === "SELL") return "sell";
  if (value === "WEAK_SELL") return "weak-sell";
  return "neutral";
}

function baseSymbol(symbol: string) {
  return symbol.includes("-") ? symbol.split("-")[0] : symbol;
}

function findTickerRow(tickers: TickerRow[], base: string) {
  return tickers.find((item) => baseSymbol(String(item.symbol || "")) === base);
}

function formatPrice(value?: number) {
  if (value == null || Number.isNaN(value)) return "-";
  if (value >= 1000) {
    return value.toLocaleString("en-US", { maximumFractionDigits: 0 });
  }
  if (value >= 1) {
    return value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  return value.toLocaleString("en-US", { maximumFractionDigits: 4 });
}

async function ensureMajorTickers(tickers: TickerRow[]) {
  const merged = [...tickers];
  const missing = ["BTC", "ETH"].filter((base) => !findTickerRow(merged, base));
  if (!missing.length) return merged;
  const results = await Promise.allSettled(
    missing.map((base) => fetchTickerStats(`${base}-USDT`)),
  );
  for (const result of results) {
    if (result.status === "fulfilled" && result.value.ticker) {
      merged.push(result.value.ticker as TickerRow);
    }
  }
  return merged;
}

function formatChange(rate?: number) {
  if (rate == null || Number.isNaN(rate)) return "-";
  const pct = rate * 100;
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
}

function leadingSector(sectors: Awaited<ReturnType<typeof fetchSectorFund>>["sectors"]) {
  const getInflow = (sector: NonNullable<typeof sectors>[number], range: string) =>
    Number((sector.categoriesTradeDataList || []).find((entry) => entry.timeRange === range)?.tradeInflow || 0);
  const top = [...(sectors || [])].sort((a, b) => getInflow(b, "h1") - getInflow(a, "h1"))[0];
  return top?.tagsSimplified || top?.tag || "-";
}

function RadarCard({
  item,
  featured,
  onResearch,
}: {
  item: OpportunityItem;
  featured?: boolean;
  onResearch: (pair: string) => void;
}) {
  const change = Number(item.change24h || 0);
  const score = Number(item.score || 0);
  const conf = Number(item.confidence || 0);
  const pair = item.pair || `${item.symbol}-USDT`;
  const reasons = (item.keyReasons || []).slice(0, 2).join(" · ");

  return (
    <article className={`radar-card ${signalClass(item.signal)}${featured ? " featured" : ""}`}>
      <div className="radar-card-rank-col">
        <div className="radar-card-rank">#{item.rank ?? "-"}</div>
        <div className="radar-score-ring" style={{ ["--ring-pct" as string]: Math.min(100, Math.abs(score)) }}>
          <span className="radar-score-num">
            {score >= 0 ? "+" : ""}
            {score.toFixed(0)}
          </span>
        </div>
      </div>
      <div className="radar-card-main">
        <div className="radar-card-head">
          <span className="radar-card-symbol">{item.symbol}</span>
          <span className="radar-signal-pill">{item.label || item.signal || "中性"}</span>
        </div>
        <div className="radar-card-metrics">
          <div>
            <span className="radar-metric-label">24h</span>
            <span className={`radar-metric-value${change >= 0 ? " up" : " down"}`}>{formatChange(change)}</span>
          </div>
          <div>
            <span className="radar-metric-label">置信度</span>
            <span className="radar-metric-value">{conf.toFixed(0)}%</span>
          </div>
          <div>
            <span className="radar-metric-label">成交额</span>
            <span className="radar-metric-value">${formatVolume(Number(item.volume24h || 0))}</span>
          </div>
        </div>
        {reasons ? <div className="radar-card-reason">{reasons}</div> : null}
      </div>
      <div className="radar-card-actions">
        <Button size="small" type="primary" className="btn-gradient" onClick={() => onResearch(pair)}>
          市场情报
        </Button>
      </div>
    </article>
  );
}

export default function RadarPage() {
  const navigate = useNavigate();
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);
  const [scanResult, setScanResult] = useState<OpportunityScanPayload | null>(null);
  const [tickers, setTickers] = useState<TickerRow[]>([]);
  const [fearGreed, setFearGreed] = useState("-");
  const [sectorLead, setSectorLead] = useState("-");
  const scanningRef = useRef(false);

  const loadContext = useCallback(async () => {
    const marketResult = await fetchMarketTickers(300).catch(() => null);
    let nextTickers = ((marketResult?.tickers as TickerRow[]) || []);
    nextTickers = await ensureMajorTickers(nextTickers);
    setTickers(nextTickers);

    const [onchainResult, sectorResult] = await Promise.allSettled([
      fetchOnchain("BTC"),
      fetchSectorFund(1),
    ]);

    if (onchainResult.status === "fulfilled") {
      const fg = onchainResult.value.marketSentiment?.fearGreed;
      if (fg?.value != null) {
        setFearGreed(`${fg.value}${fg.label ? ` · ${fg.label}` : ""}`);
      }
    }
    if (sectorResult.status === "fulfilled") {
      setSectorLead(leadingSector(sectorResult.value.sectors));
    }
  }, []);

  const loadScan = useCallback(async () => {
    if (scanningRef.current) return;
    scanningRef.current = true;
    setScanning(true);
    setScanError(null);
    try {
      const payload = await fetchOpportunityScan();
      if (!payload.ok) {
        throw new Error(payload.message || "机会扫描失败");
      }
      setScanResult(payload);
    } catch (error) {
      setScanError(error instanceof Error ? error.message : "机会扫描失败");
    } finally {
      scanningRef.current = false;
      setScanning(false);
    }
  }, []);

  useEffect(() => {
    void loadContext();
    void loadScan();
  }, [loadContext, loadScan]);

  const opportunities = scanResult?.opportunities || [];
  const btcRow = findTickerRow(tickers, "BTC");
  const ethRow = findTickerRow(tickers, "ETH");
  const btcChange = btcRow?.changeRate;
  const ethChange = ethRow?.changeRate;
  const scanTimeLabel = useMemo(() => {
    if (!scanResult?.scanTime) return "-";
    return new Date(scanResult.scanTime).toLocaleTimeString("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  }, [scanResult?.scanTime]);

  const overview = useMemo(() => {
    if (scanning && !scanResult) return "多源信号扫描进行中...";
    if (scanError) return "请稍后重试或点击「扫描机会」";
    const base = scanResult?.marketOverview || "";
    const duration = scanResult?.scanDurationMs ? ` · ${(scanResult.scanDurationMs / 1000).toFixed(1)}s` : "";
    if (base) return `${base}${duration}`;
    if (opportunities.length) {
      return `已扫描 ${scanResult?.totalScanned || opportunities.length} 个标的${duration}`;
    }
    return "暂无扫描结果";
  }, [scanError, opportunities.length, scanResult, scanning]);

  return (
    <TradingPageShell
      eyebrow="Opportunity Radar"
      title="机会雷达"
      description="内置规则扫描：web3交易所 行情 + 可选 ValueScan 摘要。无需启动 web3-trading，直连或离线样本均可运行。"
      actions={
        <>
          <Button
            type="primary"
            className="btn-gradient"
            icon={<ReloadOutlined />}
            loading={scanning}
            onClick={() => void loadScan()}
          >
            扫描机会
          </Button>
          <Button onClick={() => navigate("/data-sources")}>数据源</Button>
        </>
      }
    >
      <div className="radar-page">
        <section className="radar-pulse-strip">
          <div className="radar-pulse-group">
            <div className="radar-pulse-ticker">
              <span className="radar-pulse-icon">₿</span>
              <div>
                <span className="radar-pulse-label">BTC</span>
                <span className="radar-pulse-price">{formatPrice(btcRow?.last)}</span>
                <span className={`radar-pulse-value${btcChange != null && btcChange >= 0 ? " up" : btcChange != null ? " down" : ""}`}>
                  {formatChange(btcChange)}
                </span>
              </div>
            </div>
            <div className="radar-pulse-ticker">
              <span className="radar-pulse-icon eth">Ξ</span>
              <div>
                <span className="radar-pulse-label">ETH</span>
                <span className="radar-pulse-price">{formatPrice(ethRow?.last)}</span>
                <span className={`radar-pulse-value${ethChange != null && ethChange >= 0 ? " up" : ethChange != null ? " down" : ""}`}>
                  {formatChange(ethChange)}
                </span>
              </div>
            </div>
          </div>
          <div className="radar-pulse-divider" />
          <div className="radar-pulse-group">
            <div className="radar-pulse-ticker">
              <div>
                <span className="radar-pulse-label">恐贪指数</span>
                <span className="radar-pulse-value">{fearGreed}</span>
              </div>
            </div>
            <div className="radar-pulse-ticker">
              <div>
                <span className="radar-pulse-label">领涨板块</span>
                <span className="radar-pulse-value">{sectorLead}</span>
              </div>
            </div>
          </div>
          <div className="radar-pulse-divider" />
          <div className="radar-pulse-group radar-pulse-highlight-group">
            <div className={`radar-pulse-highlight${opportunities.length ? " active" : ""}`}>
              <span className="radar-pulse-highlight-num">{opportunities.length || "-"}</span>
              <span className="radar-pulse-highlight-label">高机会标的</span>
            </div>
            <div className="radar-pulse-highlight">
              <span className="radar-pulse-meta-value">{scanTimeLabel}</span>
              <span className="radar-pulse-highlight-label">扫描更新</span>
            </div>
          </div>
        </section>

        <section className="radar-hero-card">
          <div className="radar-hero-head">
            <div>
              <div className="trading-eyebrow">OPPORTUNITY RADAR</div>
              <h2 className="radar-hero-title">今日机会</h2>
              <p className="radar-hero-overview">{overview}</p>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8, alignItems: "flex-end" }}>
              <span className="radar-engine-badge">
                {formatSource(scanResult?.source, scanResult?.engine)}
              </span>
              {scanResult?.source ? (
                <StatusPill tone={scanResult.source === "snapshot" ? "ai" : "profit"}>
                  {scanResult.source === "snapshot" ? "离线" : "就绪"}
                </StatusPill>
              ) : null}
            </div>
          </div>

          {scanning && !opportunities.length ? (
            <div className="radar-state-box">
              <div className="radar-spinner" />
              <span>正在扫描高流动性标的...</span>
            </div>
          ) : scanError ? (
            <div className="radar-state-box error">
              <span>扫描失败：{scanError}</span>
              <Button onClick={() => void loadScan()}>重试</Button>
            </div>
          ) : opportunities.length ? (
            <div className="radar-list">
              {opportunities.map((item, index) => (
                <RadarCard
                  key={`${item.symbol}-${item.rank ?? index}`}
                  item={item}
                  featured={index === 0}
                  onResearch={() => navigate(`/research?symbol=${encodeURIComponent(item.symbol)}`)}
                />
              ))}
            </div>
          ) : (
            <div className="radar-state-box">
              <span>暂无符合条件的机会，可调整筛选或稍后重试</span>
            </div>
          )}
        </section>
      </div>
    </TradingPageShell>
  );
}
