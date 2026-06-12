import { ReloadOutlined } from "@ant-design/icons";

import { Button, Input, Select, Spin } from "antd";

import { useCallback, useEffect, useMemo, useState } from "react";

import {

  fetchAiPicks,

  fetchDashboardSources,

  fetchDexTrending,

  fetchMarketTickers,

  fetchOnchain,

  fetchSectorFund,

  fetchTokenFund,

} from "../../api";

import type { DashboardAiPicks, DashboardOnchain, DashboardSectorFund, DashboardSourcesStatus } from "../../types";

import "./data-sources.css";



interface SourceCard {

  id: string;

  name: string;

  ok: boolean;

  detail: string;

}



function leadingSector(sectors: DashboardSectorFund["sectors"]) {

  const getInflow = (sector: NonNullable<DashboardSectorFund["sectors"]>[number], range: string) => {

    const item = (sector.categoriesTradeDataList || []).find((entry) => entry.timeRange === range);

    return Number(item?.tradeInflow || 0);

  };

  const top = [...(sectors || [])].sort((a, b) => getInflow(b, "h1") - getInflow(a, "h1"))[0];

  return top?.tagsSimplified || top?.tag || "-";

}



function PickColumn({

  title,

  tone,

  items,

  empty,

}: {

  title: string;

  tone: "chance" | "funds" | "risk";

  items: DashboardAiPicks["chance"];

  empty: string;

}) {

  return (

    <article className={`ds-pick-card ds-pick-${tone}`}>

      <div className="ds-pick-title">

        {title}

        <span className="ds-pick-score">{items?.length ?? 0}</span>

      </div>

      <div className="ds-pick-list">

        {items?.length ? (

          items.slice(0, 6).map((item) => (

            <div key={`${item.symbol}-${item.title}`} className="ds-pick-item">

              <strong>

                {item.symbol || "?"} · {item.title || "信号"}

              </strong>

              <span>{item.summary || "—"}</span>

            </div>

          ))

        ) : (

          <div className="ds-empty">{empty}</div>

        )}

      </div>

    </article>

  );

}



function formatFundValue(value: unknown) {

  if (value == null) {

    return "—";

  }

  if (typeof value === "number") {

    return value.toLocaleString("zh-CN");

  }

  return String(value);

}



export default function DataSourcesPage() {

  const [loading, setLoading] = useState(true);

  const [symbol, setSymbol] = useState("BTC");

  const [tradeType, setTradeType] = useState(1);

  const [sources, setSources] = useState<SourceCard[]>([]);

  const [env, setEnv] = useState<DashboardSourcesStatus["env"]>({});

  const [fearGreed, setFearGreed] = useState<DashboardOnchain["marketSentiment"]>({});

  const [tickerCount, setTickerCount] = useState("-");

  const [sectorLead, setSectorLead] = useState("-");

  const [sectors, setSectors] = useState<DashboardSectorFund["sectors"]>([]);

  const [picks, setPicks] = useState<DashboardAiPicks | null>(null);

  const [tokenFund, setTokenFund] = useState<Record<string, unknown> | null>(null);

  const [dexTokens, setDexTokens] = useState<Array<{ symbol?: string; value?: number; priceChange?: number }>>([]);



  const refresh = useCallback(async () => {

    setLoading(true);

    try {

      const [status, onchain, tickers, sector, ai, dex, fund] = await Promise.all([

        fetchDashboardSources(),

        fetchOnchain("BTC"),

        fetchMarketTickers(300),

        fetchSectorFund(tradeType),

        fetchAiPicks(),

        fetchDexTrending("solana", 5),

        fetchTokenFund(symbol),

      ]);

      setEnv(status.env || {});

      setSources(

        (status.probes || []).map((probe) => ({

          id: probe.id,

          name: probe.name,

          ok: probe.ok,

          detail: probe.error || probe.source || (probe.ok ? "已连接" : "不可用"),

        })),

      );

      setFearGreed(onchain.marketSentiment || {});

      setTickerCount(String(tickers.count ?? (tickers.tickers || []).length));

      setSectorLead(leadingSector(sector.sectors));

      setSectors(sector.sectors || []);

      setPicks(ai);

      setDexTokens(dex.tokens || []);

      setTokenFund(fund as Record<string, unknown>);

    } finally {

      setLoading(false);

    }

  }, [symbol, tradeType]);



  useEffect(() => {

    void refresh();

  }, [refresh]);



  const liveHint = useMemo(() => {

    if (env?.valuescan || env?.dexscan) {

      return "已读取 web3-trading .env";

    }

    return "离线样本";

  }, [env]);



  const fund = (tokenFund?.fund || {}) as Record<string, unknown>;

  const sentiment = (tokenFund?.sentiment || {}) as Record<string, unknown>;

  const ratio = (tokenFund?.fundMarketCapRatio || {}) as Record<string, unknown>;



  return (

    <div className="ds-page">

      <header className="ds-header">

        <div className="ds-header-copy">

          <div className="ds-eyebrow">Data Integration</div>

          <h1>数据源</h1>

          <p>

            检测 ValueScan、DexScan、KuCoin 公网与恐贪指数。配置 `.env` 后自动切换实时摘要，否则使用 `data/dashboard` 离线样本。

          </p>

        </div>

        <div className="ds-header-actions">

          <Button className="btn-gradient" type="primary" icon={<ReloadOutlined />} loading={loading} onClick={() => void refresh()}>

            全部刷新

          </Button>

        </div>

      </header>



      <section className="ds-stats">

        <div className="ds-stat">

          <span className="ds-stat-label">运行模式</span>

          <span className="ds-stat-value">{env?.valuescan || env?.dexscan ? "Live" : "Fixture"}</span>

          <span className="ds-stat-meta">{liveHint}</span>

        </div>

        <div className="ds-stat">

          <span className="ds-stat-label">恐贪指数</span>

          <span className="ds-stat-value">

            {fearGreed?.fearGreed?.value != null ? fearGreed.fearGreed.value : "—"}

          </span>

          <span className="ds-stat-meta">{fearGreed?.fearGreed?.label || "alternative.me"}</span>

        </div>

        <div className="ds-stat">

          <span className="ds-stat-label">领涨板块</span>

          <span className="ds-stat-value">{sectorLead}</span>

          <span className="ds-stat-meta">ValueScan 1h 资金</span>

        </div>

        <div className="ds-stat">

          <span className="ds-stat-label">USDT 交易对</span>

          <span className="ds-stat-value">{tickerCount}</span>

          <span className="ds-stat-meta">KuCoin 公网</span>

        </div>

      </section>



      {loading && !sources.length ? (

        <div className="ds-loading">

          <Spin />

        </div>

      ) : null}



      <section className="ds-panel">

        <div className="ds-panel-head">

          <div>

            <h2>接入状态</h2>

            <p>ValueScan · DexScan · KuCoin · 恐贪指数</p>

          </div>

          <span className={`ds-badge ${env?.valuescan ? "ds-badge-live" : "ds-badge-fixture"}`}>

            {env?.valuescan ? "Live" : "Fixture"}

          </span>

        </div>

        <div className="ds-source-grid">

          {sources.map((item) => (

            <article key={item.id} className={`ds-source-card ${item.ok ? "ds-ok" : "ds-error"}`}>

              <div className="ds-source-head">

                <span className="ds-source-dot" />

                <h3>{item.name}</h3>

              </div>

              <p className="ds-source-detail">{item.detail}</p>

            </article>

          ))}

        </div>

      </section>



      <section className="ds-picks-grid">

        <PickColumn title="AI 机会" tone="chance" items={picks?.chance} empty="暂无机会样本" />

        <PickColumn title="资金异动" tone="funds" items={picks?.funds} empty="暂无资金样本" />

        <PickColumn title="风险回避" tone="risk" items={picks?.risk} empty="暂无风险样本" />

      </section>



      <section className="ds-split">

        <div className="ds-panel">

          <div className="ds-panel-head">

            <div>

              <h2>代币资金</h2>

              <p>{symbol} · ValueScan</p>

            </div>

          </div>

          <div className="ds-toolbar">

            <Input

              value={symbol}

              onChange={(event) => setSymbol(event.target.value.toUpperCase())}

              onPressEnter={() => void refresh()}

              placeholder="BTC"

              style={{ width: 120 }}

            />

            <Button type="default" onClick={() => void refresh()}>

              刷新

            </Button>

          </div>

          <div className="ds-kv-grid">

            <div className="ds-kv-item">

              <span>24h 净流入</span>

              <strong>{formatFundValue(fund.netInflow24h)}</strong>

            </div>

            <div className="ds-kv-item">

              <span>24h 流入</span>

              <strong>{formatFundValue(fund.tradeInflow24h)}</strong>

            </div>

            <div className="ds-kv-item">

              <span>情绪分数</span>

              <strong>{formatFundValue(sentiment.score)}</strong>

            </div>

            <div className="ds-kv-item">

              <span>市值占比</span>

              <strong>{formatFundValue(ratio.ratio)}</strong>

            </div>

          </div>

        </div>



        <div className="ds-panel">

          <div className="ds-panel-head">

            <div>

              <h2>DexScan Trending</h2>

              <p>Solana · 24h 成交额</p>

            </div>

          </div>

          <div className="ds-row-list">

            {dexTokens.length ? (

              dexTokens.map((token) => (

                <div key={token.symbol} className="ds-row">

                  <div>

                    <strong>{token.symbol || "?"}</strong>

                    <span>成交额 {formatFundValue(token.value)}</span>

                  </div>

                  <span className={`ds-badge ${(token.priceChange || 0) >= 0 ? "ds-badge-up" : "ds-badge-down"}`}>

                    {(token.priceChange || 0).toFixed(1)}%

                  </span>

                </div>

              ))

            ) : (

              <div className="ds-empty">暂无 DEX 样本</div>

            )}

          </div>

        </div>

      </section>



      <section className="ds-panel">

        <div className="ds-panel-head">

          <div>

            <h2>板块资金轮动</h2>

            <p>现货 / 合约板块列表</p>

          </div>

          <div className="ds-toolbar" style={{ marginBottom: 0 }}>

            <Select

              value={tradeType}

              onChange={setTradeType}

              options={[

                { value: 1, label: "现货" },

                { value: 2, label: "合约" },

              ]}

              style={{ width: 120 }}

            />

            <Button type="default" onClick={() => void refresh()}>

              刷新

            </Button>

          </div>

        </div>

        <div className="ds-row-list">

          {(sectors || []).slice(0, 8).map((sector) => (

            <div key={sector.tag} className="ds-row">

              <div>

                <strong>{sector.tagsSimplified || sector.tag || "板块"}</strong>

                <span>1h 资金轮动</span>

              </div>

              <span className="ds-badge ds-badge-up">Sector</span>

            </div>

          ))}

        </div>

      </section>

    </div>

  );

}


