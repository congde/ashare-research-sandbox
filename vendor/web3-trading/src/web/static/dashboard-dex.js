/**
 * DexScan DEX module for TradeDashboard.
 *
 * Contains all DEX-related data fetching, rendering, and interaction logic.
 * Loaded before dashboard.js — provides DexMixin for prototype merging.
 */

// eslint-disable-next-line no-unused-vars
const DexMixin = {

    // ── DEX element IDs (merged into this.elements during init) ───
    DEX_ELEMENT_IDS: [
        "dexSymbolLabel", "dexChainSelect", "refreshDexBtn", "dexOverviewContent",
        "dexTrendingChainSelect", "dexTrendingSortSelect", "refreshDexTrendingBtn", "dexTrendingContent",
    ],

    // ── DEX event bindings ─────────────────────────────────────────
    bindDexEvents() {
        const el = this.elements;
        const on = (elem, evt, fn) => { if (elem) elem.addEventListener(evt, fn); };
        on(el.refreshDexBtn, "click", () => this.loadDexOverview(this.getActiveSymbol()));
        on(el.dexChainSelect, "change", () => this.loadDexOverview(this.getActiveSymbol()));
        on(el.refreshDexTrendingBtn, "click", () => this.loadDexTrending());
        on(el.dexTrendingChainSelect, "change", () => this.loadDexTrending());
        on(el.dexTrendingSortSelect, "change", () => this.loadDexTrending());
    },

    refreshDexData(sym) {
        this.loadDexOverview(sym);
        this.loadDexTrending();
    },

    // ── DEX Overview ────────────────────────────────────────────────
    async loadDexOverview(symbol) {
        if (!this.elements.dexOverviewContent) return;
        const sym = (symbol || this.getActiveSymbol()).toUpperCase();
        if (this.elements.dexSymbolLabel) this.elements.dexSymbolLabel.textContent = sym;
        this.elements.dexOverviewContent.textContent = `加载 ${sym} DEX 数据中...`;
        try {
            const resp = await fetch(`/api/dashboard/dex/overview?symbol=${encodeURIComponent(sym)}`);
            const data = await this.parseJsonResponse(resp);
            if (!data.ok) throw new Error(data.message || "加载失败");
            this._renderDexOverview(data, sym);
        } catch (err) {
            this.elements.dexOverviewContent.innerHTML = `<div class="vs-fund-error">DEX 数据加载失败: ${this.escapeHtml(err.message)}</div>`;
        }
    },

    _renderDexOverview(data, symbol) {
        if (!this.elements.dexOverviewContent) return;
        const price = data.price || {};
        const info = data.info || {};
        const liquidity = data.liquidity || {};
        const riskLabels = data.riskLabels || {};
        const topPools = data.topPools || [];
        const topHolders = data.topHolders || [];
        const socialHeat = data.socialHeat || {};
        const recentTrades = data.recentTrades || [];
        const chain = data.chain || "";
        const address = data.address || "";

        if (!address) {
            this.elements.dexOverviewContent.innerHTML = `<div class="vs-fund-error">${symbol} 暂无 DEX 链上映射 (仅支持主流链上代币)</div>`;
            return;
        }

        let html = `<div class="dex-overview-grid">`;

        // Price card
        html += this._renderDexPriceCard(price, info, symbol, chain);
        // Info & Risk card
        html += this._renderDexInfoCard(info, riskLabels, liquidity);
        // Social Heat card
        html += this._renderDexHeatCard(socialHeat);
        // Top Pools
        html += this._renderDexPoolsCard(topPools);

        html += `</div>`;

        // Top Holders table (full-width below)
        html += this._renderDexHoldersTable(topHolders, symbol);
        // Recent Trades table
        html += this._renderDexTradesTable(recentTrades, symbol, chain);

        html += `<div class="onchain-desc">数据来源: DexScan · kcapi.dexscan.trade · ${chain}</div>`;
        this.elements.dexOverviewContent.innerHTML = html;
    },

    _renderDexPriceCard(price, info, symbol, chain) {
        const currentPrice = price.price || info.price || "";
        const priceChange = price.change24h ?? info.priceChange24h ?? null;
        const volume24h = price.volume24h ?? info.volume24h ?? null;
        const high24h = price.high24h ?? info.high24h ?? null;
        const low24h = price.low24h ?? info.low24h ?? null;
        const mcap = info.marketCap ?? info.fdv ?? null;

        let html = `<div class="vs-metric-card"><div class="vs-metric-header">DEX 价格 <small>${chain}</small></div>`;
        if (currentPrice) {
            html += `<div class="dex-price-big">$${this.formatDexPrice(Number(currentPrice))}</div>`;
        }
        if (priceChange != null) {
            const pct = Number(priceChange);
            const cls = pct >= 0 ? "change-up" : "change-down";
            html += `<div class="vs-metric-row"><span>24h 涨跌</span><span class="${cls}">${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%</span></div>`;
        }
        if (volume24h != null) {
            html += `<div class="vs-metric-row"><span>24h 成交量</span><span>$${this.formatNumber(Number(volume24h))}</span></div>`;
        }
        if (high24h != null && low24h != null) {
            html += `<div class="vs-metric-row"><span>24h 高/低</span><span>$${this.formatDexPrice(Number(low24h))} ~ $${this.formatDexPrice(Number(high24h))}</span></div>`;
        }
        if (mcap != null) {
            html += `<div class="vs-metric-row"><span>市值</span><span>$${this.formatNumber(Number(mcap))}</span></div>`;
        }
        return html + `</div>`;
    },

    _renderDexInfoCard(info, riskLabels, liquidity) {
        let html = `<div class="vs-metric-card"><div class="vs-metric-header">代币信息 & 风险</div>`;
        const holders = info.holderCount ?? info.holders ?? null;
        const txns24h = info.txCount24h ?? info.transactionCount ?? null;
        const liqValue = liquidity.liquidity ?? liquidity.usd ?? null;

        if (holders != null) {
            html += `<div class="vs-metric-row"><span>持仓地址数</span><span>${this.formatNumber(Number(holders))}</span></div>`;
        }
        if (txns24h != null) {
            html += `<div class="vs-metric-row"><span>24h 交易数</span><span>${this.formatNumber(Number(txns24h))}</span></div>`;
        }
        if (liqValue != null) {
            html += `<div class="vs-metric-row"><span>流动性</span><span>$${this.formatNumber(Number(liqValue))}</span></div>`;
        }

        // Risk labels — API may return {riskLevel: "NONE"} or array of labels
        const riskLevel = riskLabels.riskLevel || "";
        const risks = riskLabels.labels || riskLabels.riskLabels || [];
        if (riskLevel) {
            const rlCls = riskLevel === "HIGH" || riskLevel === "DANGER" ? "dex-risk-high"
                        : riskLevel === "MEDIUM" || riskLevel === "WARN" ? "dex-risk-warn"
                        : "dex-risk-low";
            const rlLabel = riskLevel === "NONE" ? "✅ 安全" : riskLevel;
            html += `<div class="vs-metric-row"><span>风险等级</span><span class="dex-risk-tag ${rlCls}">${this.escapeHtml(rlLabel)}</span></div>`;
        }
        if (risks.length) {
            html += `<div class="dex-risk-tags">`;
            risks.forEach(r => {
                const label = typeof r === "string" ? r : r.label || r.name || "";
                const level = typeof r === "object" ? (r.level || r.severity || "") : "";
                const cls = level === "high" || level === "danger" ? "dex-risk-high" : level === "medium" || level === "warn" ? "dex-risk-warn" : "dex-risk-low";
                if (label) html += `<span class="dex-risk-tag ${cls}">${this.escapeHtml(label)}</span>`;
            });
            html += `</div>`;
        }
        return html + `</div>`;
    },

    _renderDexHeatCard(heat) {
        if (!heat || !Object.keys(heat).length) return "";
        let html = `<div class="vs-metric-card"><div class="vs-metric-header">🔥 社交热度</div>`;
        const heatValue = heat.heatValue ?? heat.heat ?? heat.score ?? null;
        const heatChange = heat.heatChange24h ?? heat.change ?? null;
        if (heatValue != null) {
            html += `<div class="dex-heat-big">${Number(heatValue).toFixed(1)}</div>`;
        }
        if (heatChange != null) {
            const pct = Number(heatChange);
            const cls = pct >= 0 ? "change-up" : "change-down";
            html += `<div class="vs-metric-row"><span>热度变化</span><span class="${cls}">${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%</span></div>`;
        }
        // KOL data
        const kols = heat.topKols || heat.kols || heat.buyTop5Kol || [];
        if (kols.length) {
            html += `<div class="dex-kol-list">`;
            kols.slice(0, 5).forEach(k => {
                const name = k.name || k.screenName || k.username || "";
                const followers = k.followersCount ?? k.followers ?? "";
                const url = k.url || k.profileUrl || "#";
                if (name) html += `<a class="dex-kol-item" href="${this.escapeHtml(url)}" target="_blank">@${this.escapeHtml(name)} ${followers ? `(${this.formatNumber(Number(followers))})` : ""}</a>`;
            });
            html += `</div>`;
        }
        return html + `</div>`;
    },

    _renderDexPoolsCard(pools) {
        if (!pools.length) return "";
        let html = `<div class="vs-metric-card vs-metric-card-wide"><div class="vs-metric-header">Top 流动性池</div>`;
        html += `<div class="dex-pool-grid">`;
        pools.forEach(p => {
            const name = p.name || p.pair || "-";
            const liq = p.liquidity ?? p.reserveUsd ?? p.usd ?? 0;
            const volume = p.volume24h ?? p.volume ?? 0;
            const apr = p.apr ?? p.feeApr ?? null;
            html += `<div class="dex-pool-item">
                <span class="dex-pool-name">${this.escapeHtml(name)}</span>
                <span class="dex-pool-liq">$${this.formatNumber(Number(liq))}</span>
                ${volume ? `<span class="dex-pool-vol">Vol $${this.formatNumber(Number(volume))}</span>` : ""}
                ${apr != null ? `<span class="dex-pool-apr">APR ${Number(apr).toFixed(1)}%</span>` : ""}
            </div>`;
        });
        html += `</div></div>`;
        return html;
    },

    _renderDexHoldersTable(holders, symbol) {
        if (!holders.length) return "";
        let html = `<div class="dex-table-section"><div class="vs-metric-header">DEX Top 持仓地址</div>`;
        html += `<div class="dex-data-table"><div class="dex-data-head"><span>#</span><span>地址</span><span>持仓量</span><span>持仓占比</span></div>`;
        holders.forEach((h, i) => {
            const addr = h.address || h.owner || "-";
            const balance = h.balance ?? h.amount ?? 0;
            const pct = h.percent ?? h.ratio ?? h.share ?? null;
            const shortAddr = this.shortenAddr(addr);
            html += `<div class="dex-data-row">
                <span>${i + 1}</span>
                <span class="dex-addr" title="${this.escapeHtml(addr)}">${this.escapeHtml(shortAddr)}</span>
                <span>${this.formatNumber(Number(balance))}</span>
                <span>${pct != null ? Number(pct).toFixed(2) + "%" : "-"}</span>
            </div>`;
        });
        return html + `</div></div>`;
    },

    _renderDexTradesTable(trades, symbol, chain) {
        if (!trades.length) return "";
        let html = `<div class="dex-table-section"><div class="vs-metric-header">DEX 最新成交</div>`;
        html += `<table class="dex-trades-table"><thead><tr>
            <th>时间</th><th>方向</th><th>代币对</th><th>数量</th><th>价格</th><th>金额</th><th>TxHash</th>
        </tr></thead><tbody>`;
        trades.slice(0, 15).forEach(t => {
            const time = t.blockTime || t.timestamp || t.time || "";
            const timeStr = time ? new Date(Number(time) > 1e12 ? Number(time) : Number(time) * 1000).toLocaleString("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "-";

            // swapType: 1=BUY, 2=SELL, 4=ADDLIQUID, 5=REMOVELIQUID
            const swapType = Number(t.swapType || 0);
            const sideMap = { 1: ["买入", "change-up"], 2: ["卖出", "change-down"], 4: ["加池", ""], 5: ["撤池", "change-down"] };
            const [sideLabel, sideCls] = sideMap[swapType] || [String(swapType), ""];

            const baseSymbol = t.baseSymbol || "";
            const quoteSymbol = t.quoteSymbol || "";
            const pair = baseSymbol && quoteSymbol ? `${baseSymbol}/${quoteSymbol}` : baseSymbol || symbol || "-";

            const amount = parseFloat(t.baseAmount || t.amount || t.tokenAmount || 0);
            const price = parseFloat(t.price || t.tokenPrice || 0);
            const value = parseFloat(t.value || t.quoteAmount || t.usdAmount || 0);

            const txHash = t.transHash || t.txHash || "";
            const shortHash = txHash ? txHash.slice(0, 6) + "..." + txHash.slice(-4) : "-";

            html += `<tr>
                <td>${timeStr}</td>
                <td class="${sideCls}">${sideLabel}</td>
                <td>${this.escapeHtml(pair)}</td>
                <td>${this.formatNumber(amount)}</td>
                <td>$${this.formatDexPrice(price)}</td>
                <td>$${this.formatNumber(value)}</td>
                <td class="dex-addr" title="${this.escapeHtml(txHash)}">${this.escapeHtml(shortHash)}</td>
            </tr>`;
        });
        return html + `</tbody></table></div>`;
    },

    // ── Trending DEX Tokens ─────────────────────────────────────────
    async loadDexTrending() {
        if (!this.elements.dexTrendingContent) return;
        const chain = this.elements.dexTrendingChainSelect ? this.elements.dexTrendingChainSelect.value : "solana";
        this.elements.dexTrendingContent.textContent = `加载 ${chain} 热门 DEX 代币...`;
        try {
            const resp = await fetch(`/api/dashboard/dex/trending?chain=${encodeURIComponent(chain)}&limit=20`);
            const data = await this.parseJsonResponse(resp);
            if (!data.ok) throw new Error(data.message || "加载失败");
            this._renderDexTrending(data.tokens || [], chain);
        } catch (err) {
            this.elements.dexTrendingContent.innerHTML = `<div class="vs-fund-error">热门代币加载失败: ${this.escapeHtml(err.message)}</div>`;
        }
    },

    _renderDexTrending(tokens, chain) {
        if (!this.elements.dexTrendingContent) return;
        if (!tokens.length) {
            this.elements.dexTrendingContent.innerHTML = `<div class='vs-fund-error'>暂无 ${chain} 热门 DEX 数据</div>`;
            return;
        }
        let html = `<div class="dex-trending-grid">`;
        tokens.forEach((t, idx) => {
            const name = t.name || t.tokenName || "-";
            const symbol = t.symbol || t.tokenSymbol || "-";
            // coin-rank API fields: closePrice, priceChange, value, volume, marketCap
            const price = parseFloat(t.closePrice || t.price || t.lastPrice || 0);
            const change = t.priceChange != null ? parseFloat(t.priceChange) * 100 : (t.priceChange24h != null ? parseFloat(t.priceChange24h) : null);
            const volume = parseFloat(t.value || t.volume24h || t.volume || t.volValue || 0);
            const mcap = parseFloat(t.marketCap || t.fdv || 0);
            const liquid = parseFloat(t.liquid || 0);
            const logo = t.logo ?? t.icon ?? "";
            const addr = t.tokenAddressBase ?? t.address ?? t.tokenContractAddress ?? t.contractAddress ?? "";
            const chainName = t.chainName ?? chain;
            const changeCls = change != null && change >= 0 ? "change-up" : "change-down";
            const changeStr = change != null ? `${change >= 0 ? "+" : ""}${change.toFixed(2)}%` : "";
            const logoHtml = logo ? `<img class="dex-token-logo" src="${logo}" alt="" onerror="this.style.display='none'">` : `<span class="vs-pick-icon">🪙</span>`;
            const tradeCount = t.tradeCount ? `${this.formatNumber(Number(t.tradeCount))} txns` : "";

            html += `<div class="dex-trending-item" data-dex-addr="${this.escapeHtml(addr)}" data-dex-chain="${this.escapeHtml(chainName)}" data-dex-symbol="${this.escapeHtml(symbol)}">
                <div class="dex-trending-rank">#${idx + 1}</div>
                ${logoHtml}
                <div class="dex-trending-info">
                    <span class="dex-trending-symbol">${this.escapeHtml(symbol)}</span>
                    <span class="dex-trending-name">${this.escapeHtml(name)}</span>
                </div>
                <div class="dex-trending-right">
                    ${price ? `<span class="dex-trending-price">$${this.formatDexPrice(price)}</span>` : ""}
                    ${changeStr ? `<span class="${changeCls}">${changeStr}</span>` : ""}
                </div>
                <div class="dex-trending-meta">
                    ${volume ? `<span>Vol $${this.formatNumber(volume)}</span>` : ""}
                    ${mcap ? `<span>MCap $${this.formatNumber(mcap)}</span>` : ""}
                    ${liquid ? `<span>Liq $${this.formatNumber(liquid)}</span>` : ""}
                    ${tradeCount ? `<span>${tradeCount}</span>` : ""}
                </div>
            </div>`;
        });
        html += `</div>`;
        html += `<div class="onchain-desc">数据来源: DexScan Trending · ${chain}</div>`;
        this.elements.dexTrendingContent.innerHTML = html;

        // Click to show detail modal
        this.elements.dexTrendingContent.querySelectorAll(".dex-trending-item").forEach(row => {
            row.addEventListener("click", () => {
                const sym = row.dataset.dexSymbol || "";
                if (sym) {
                    // Update symbol input and refresh overview
                    if (this.elements.searchInput) {
                        this.elements.searchInput.value = sym;
                        this.refreshCoinData();
                    }
                    this.loadDexOverview(sym);
                }
            });
        });
    },

    // ── Helper: format DEX price (handle very small numbers) ────
    formatDexPrice(price) {
        if (!Number.isFinite(price) || price === 0) return "0";
        if (price >= 1) return price.toFixed(4);
        if (price >= 0.001) return price.toFixed(6);
        // Very small: use scientific-ish or many decimals
        if (price >= 0.000001) return price.toFixed(8);
        return price.toExponential(4);
    },
};
