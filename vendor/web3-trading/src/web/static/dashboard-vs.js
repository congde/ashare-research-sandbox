/**
 * ValueScan module for TradeDashboard.
 *
 * Contains all VS-related data fetching, rendering, and modal logic.
 * Loaded before dashboard.js — provides VsMixin for prototype merging.
 */

// eslint-disable-next-line no-unused-vars
const VsMixin = {

    // ── VS element IDs (merged into this.elements during init) ───
    VS_ELEMENT_IDS: [
        "vsChanceList", "vsRiskList", "vsFundsList", "refreshVsPicksBtn",
        "vsFundContent", "vsFundSymbolLabel", "refreshVsFundBtn",
        "vsSectorContent", "vsSectorTypeSelect", "refreshVsSectorBtn",
        "vsWhaleOnchainContent", "vsWhaleSymbolLabel", "refreshVsWhaleBtn",
        "vsIndicatorsContent", "vsIndicatorSymbolLabel", "refreshVsIndicatorsBtn",
        "vsDetailModal", "vsDetailModalTitle", "vsDetailModalBody", "closeVsDetailModal",
    ],

    // ── VS event bindings ─────────────────────────────────────────
    bindVsEvents() {
        const el = this.elements;
        const on = (elem, evt, fn) => { if (elem) elem.addEventListener(evt, fn); };
        on(el.refreshVsPicksBtn, "click", () => this.loadVsAiPicks());
        on(el.refreshVsFundBtn, "click", () => this.loadVsFundData(this.getActiveSymbol()));
        on(el.refreshVsSectorBtn, "click", () => this.loadVsSectorFund());
        on(el.vsSectorTypeSelect, "change", () => this.loadVsSectorFund());
        on(el.refreshVsWhaleBtn, "click", () => this.loadVsWhaleOnchain(this.getActiveSymbol()));
        on(el.refreshVsIndicatorsBtn, "click", () => this.loadVsPriceIndicators(this.getActiveSymbol()));
        if (el.closeVsDetailModal) {
            on(el.closeVsDetailModal, "click", () => this.closeVsDetailModal());
            on(el.vsDetailModal, "click", (e) => { if (e.target === el.vsDetailModal) this.closeVsDetailModal(); });
        }
    },

    refreshVsData(sym) {
        this.loadVsFundData(sym);
        this.loadVsWhaleOnchain(sym);
        this.loadVsPriceIndicators(sym);
    },

    // ── AI Smart Picks ────────────────────────────────────────────
    async loadVsAiPicks() {
        const els = [this.elements.vsChanceList, this.elements.vsRiskList, this.elements.vsFundsList];
        els.forEach(el => { if (el) el.textContent = "加载中..."; });
        try {
            const resp = await fetch("/api/dashboard/vs/ai-picks");
            const data = await this.parseJsonResponse(resp);
            if (!data.ok) throw new Error(data.message || "加载失败");
            this._renderVsPickList(this.elements.vsChanceList, data.chance || [], "chance");
            this._renderVsPickList(this.elements.vsRiskList, data.risk || [], "risk");
            this._renderVsPickList(this.elements.vsFundsList, data.funds || [], "funds");
            if (typeof this.onVsPicksLoaded === "function") this.onVsPicksLoaded(data);
        } catch (err) {
            els.forEach(el => { if (el) el.innerHTML = `<div class="vs-pick-empty">加载失败: ${this.escapeHtml(err.message)}</div>`; });
        }
    },

    _renderVsPickList(el, items, type) {
        if (!el) return;
        if (!items.length) { el.innerHTML = "<div class='vs-pick-empty'>暂无数据</div>"; return; }
        const icons = { chance: "🟢", risk: "🔴", funds: "🔵" };
        const icon = icons[type] || "⚪";
        el.innerHTML = items.slice(0, 10).map(item => {
            const symbol = item.symbol || item.tokenSymbol || "-";
            const name = item.name || item.tokenName || "";
            const price = item.price != null ? `$${this.formatNumber(Number(item.price))}` : "";
            const pct24h = item.percentChange24h != null ? Number(item.percentChange24h) : null;
            const change = pct24h != null
                ? `<span class="${pct24h >= 0 ? "change-up" : "change-down"}">${pct24h >= 0 ? "+" : ""}${pct24h.toFixed(2)}%</span>` : "";
            const cost = item.cost ? `主力成本 $${this.formatNumber(Number(item.cost))}` : "";
            const deviation = item.deviation ? `偏离 ${Number(item.deviation).toFixed(1)}%` : "";
            const tradeData = (item.chanceCoinTradeDataV1Vos || item.riskCoinTradeDataV1Vos || item.fundsCoinTradeDataV1Vos || []);
            const m1 = tradeData.find(t => t.timeRange === "M1");
            const inflowNote = m1 ? `月净流入 $${this.formatNumber(Number(m1.tradeInflow))}` : "";
            const subtitle = [cost, deviation, inflowNote].filter(Boolean).join(" · ");
            const logo = item.logo || item.tokenLogo || "";
            const logoHtml = logo ? `<img class="vs-pick-logo" src="${logo}" alt="" onerror="this.style.display='none'">` : `<span class="vs-pick-icon">${icon}</span>`;
            const rank = item.marketCapRanking ? `#${item.marketCapRanking}` : "";
            return `<div class="vs-pick-item vs-pick-clickable" data-vs-symbol="${this.escapeHtml(symbol)}" data-vs-type="${type}">
                ${logoHtml}
                <div class="vs-pick-info">
                    <span class="vs-pick-symbol">${this.escapeHtml(symbol)} <small>${rank}</small></span>
                    <span class="vs-pick-name">${this.escapeHtml(name)}</span>
                    ${subtitle ? `<span class="vs-pick-reason">${this.escapeHtml(subtitle)}</span>` : ""}
                </div>
                <div class="vs-pick-right"><span class="vs-pick-price">${price}</span>${change}</div>
            </div>`;
        }).join("");
        el.querySelectorAll(".vs-pick-clickable").forEach(row => {
            row.addEventListener("click", () => this.showVsAiMessages(row.dataset.vsSymbol, row.dataset.vsType));
        });
    },

    // ── Fund & Sentiment ──────────────────────────────────────────
    async loadVsFundData(symbol) {
        if (!this.elements.vsFundContent) return;
        const sym = (symbol || this.getActiveSymbol()).toUpperCase();
        if (this.elements.vsFundSymbolLabel) this.elements.vsFundSymbolLabel.textContent = sym;
        this.elements.vsFundContent.textContent = `加载 ${sym} ValueScan 数据中...`;
        try {
            const [fundResp, whaleResp, snapResp] = await Promise.all([
                fetch(`/api/dashboard/vs/token-fund?symbol=${encodeURIComponent(sym)}`),
                fetch(`/api/dashboard/vs/whale-cost?symbol=${encodeURIComponent(sym)}`),
                fetch(`/api/dashboard/vs/fund-snapshot?symbol=${encodeURIComponent(sym)}`),
            ]);
            const fundData = await this.parseJsonResponse(fundResp);
            const whaleData = await this.parseJsonResponse(whaleResp);
            const snapData = await this.parseJsonResponse(snapResp);
            this.vsFundSnapshot = snapData.ok ? (snapData.snapshot || {}) : {};
            this._renderVsFundData(fundData, whaleData, sym);
        } catch (err) {
            this.elements.vsFundContent.innerHTML = `<div class="vs-fund-error">加载失败: ${this.escapeHtml(err.message)}</div>`;
        }
    },

    _renderVsFundData(fundData, whaleData, symbol) {
        if (!this.elements.vsFundContent) return;
        if (!fundData.ok && !whaleData.ok) {
            this.elements.vsFundContent.innerHTML = `<div class="vs-fund-error">ValueScan 数据不可用: ${this.escapeHtml(fundData.message || whaleData.message || "unknown")}</div>`;
            return;
        }
        const fund = fundData.fund || {}, ratio = fundData.fundMarketCapRatio || {};
        const sentiment = fundData.sentiment || {}, sr = fundData.supportResistance || [];
        const whaleCost = whaleData.whaleCost || [], tokenFlow = whaleData.tokenFlow || {};
        let html = `<div class="vs-fund-grid">`;

        html += this._renderFundTable(fund, symbol);
        html += this._renderSentiment(sentiment);
        html += this._renderRatio(ratio);
        html += this._renderFundSnapshot();
        html += this._renderTokenFlow(tokenFlow);
        html += `</div>`;
        html += this._renderSupportResistance(sr, fund);
        html += this._renderWhaleCost(whaleCost);

        if (!html.replace(/<div[^>]*><\/div>/g, "").trim()) html = `<div class="vs-fund-error">暂无 ${symbol} 的 ValueScan 数据</div>`;
        html += `<div class="onchain-desc">数据来源: ValueScan AI · api-beta.valuescan.io</div>`;
        this.elements.vsFundContent.innerHTML = html;
    },

    _renderFundTable(fund, symbol) {
        if (!Object.keys(fund).length) return "";
        const spots = fund.spotGoodsList || [];
        if (!spots.length) return "";
        let html = `<div class="vs-metric-card vs-metric-card-wide"><div class="vs-metric-header">实时资金积累 <small>${fund.symbol || symbol}</small></div>`;
        html += `<div class="vs-fund-table"><div class="vs-fund-table-head"><span>周期</span><span>净流入</span><span>成交额</span><span>流入变化</span></div>`;
        spots.forEach(s => {
            const inflow = Number(s.tradeInflow || 0), amount = Number(s.tradeAmount || 0);
            const inflowChange = s.tradeInflowChange;
            const cls = inflow >= 0 ? "change-up" : "change-down";
            const changeCls = inflowChange != null ? (inflowChange >= 0 ? "change-up" : "change-down") : "";
            html += `<div class="vs-fund-table-row">
                <span>${s.timeRange || "-"}</span><span class="${cls}">$${this.formatNumber(inflow)}</span>
                <span>$${this.formatNumber(amount)}</span>
                <span class="${changeCls}">${inflowChange != null ? (inflowChange >= 0 ? "+" : "") + inflowChange.toFixed(2) + "%" : "-"}</span>
            </div>`;
        });
        return html + `</div></div>`;
    },

    _renderSentiment(sentiment) {
        if (!Object.keys(sentiment).length) return "";
        let html = `<div class="vs-metric-card"><div class="vs-metric-header">社媒情绪分析</div>`;
        const bullish = sentiment.bullishRatio != null ? (sentiment.bullishRatio * 100).toFixed(1) : null;
        const neutral = sentiment.neutralRatio != null ? (sentiment.neutralRatio * 100).toFixed(1) : null;
        const bearish = sentiment.bearishRatio != null ? (sentiment.bearishRatio * 100).toFixed(1) : null;
        if (bullish != null) {
            html += `<div class="vs-sentiment-bars">`;
            html += `<div class="vs-sbar-row"><span class="vs-sbar-label">看多</span><div class="vs-sbar"><div class="vs-sbar-fill vs-sbar-bull" style="width:${bullish}%"></div></div><span class="vs-sbar-pct change-up">${bullish}%</span></div>`;
            html += `<div class="vs-sbar-row"><span class="vs-sbar-label">中性</span><div class="vs-sbar"><div class="vs-sbar-fill vs-sbar-neutral" style="width:${neutral}%"></div></div><span class="vs-sbar-pct">${neutral}%</span></div>`;
            html += `<div class="vs-sbar-row"><span class="vs-sbar-label">看空</span><div class="vs-sbar"><div class="vs-sbar-fill vs-sbar-bear" style="width:${bearish}%"></div></div><span class="vs-sbar-pct change-down">${bearish}%</span></div>`;
            html += `</div>`;
        }
        return html + `</div>`;
    },

    _renderRatio(ratio) {
        if (!Object.keys(ratio).length) return "";
        let html = `<div class="vs-metric-card"><div class="vs-metric-header">资金/市值比</div>`;
        if (ratio.totalMarketCapRatio != null) html += `<div class="vs-metric-big">${(ratio.totalMarketCapRatio * 100).toFixed(4)}%</div>`;
        if (ratio.marketCap != null) html += `<div class="vs-metric-row"><span>市值</span><span>$${this.formatNumber(ratio.marketCap)}</span></div>`;
        const rows = [
            ["现货净流入", ratio.spotTradeInflow], ["合约净流入", ratio.contractTradeInflow], ["总净流入", ratio.totalTradeInflow],
        ];
        rows.forEach(([label, val]) => {
            if (val == null) return;
            const v = Number(val), cls = v >= 0 ? "change-up" : "change-down";
            const extra = label === "总净流入" ? " vs-metric-highlight" : "";
            html += `<div class="vs-metric-row${extra}"><span>${label}</span><span class="${cls}">$${this.formatNumber(v)}</span></div>`;
        });
        return html + `</div>`;
    },

    _renderFundSnapshot() {
        const snap = this.vsFundSnapshot || {};
        const spots = snap.spotGoodsList || [], contracts = snap.contractList || [];
        if (!spots.length && !contracts.length) return "";
        const snapTime = snap.updateTime ? new Date(snap.updateTime).toLocaleString("zh-CN") : "";
        let html = `<div class="vs-metric-card vs-metric-card-wide"><div class="vs-metric-header">资金快照 <small>${snapTime}</small></div>`;
        const all = [
            ...spots.map(s => ({ ...s, market: "现货" })),
            ...contracts.map(s => ({ ...s, market: "合约" })),
        ].filter(s => ["H1", "H4", "H12", "D1", "D3", "D7"].includes(s.timeRange));
        if (all.length) {
            html += `<div class="vs-fund-table"><div class="vs-fund-table-head"><span>市场</span><span>周期</span><span>净流入</span><span>成交额</span></div>`;
            all.forEach(s => {
                const inflow = Number(s.tradeInflow || 0), amount = Number(s.tradeAmount || 0);
                const cls = inflow >= 0 ? "change-up" : "change-down";
                html += `<div class="vs-fund-table-row"><span>${s.market}</span><span>${s.timeRange}</span><span class="${cls}">$${this.formatNumber(inflow)}</span><span>$${this.formatNumber(amount)}</span></div>`;
            });
            html += `</div>`;
        }
        return html + `</div>`;
    },

    _renderTokenFlow(tokenFlow) {
        const items = tokenFlow.coinTradeFlowDataV1Vos || [];
        if (!items.length) return "";
        let html = `<div class="vs-metric-card vs-metric-card-wide"><div class="vs-metric-header">交易所链上资金流向</div>`;
        html += `<div class="vs-fund-table"><div class="vs-fund-table-head"><span>周期</span><span>流入</span><span>流出</span><span>净流入</span></div>`;
        items.forEach(f => {
            const tradeIn = Number(f.tradeIn || 0), tradeOut = Number(f.tradeOut || 0), net = Number(f.tradeInflow || 0);
            const netCls = net >= 0 ? "change-up" : "change-down";
            html += `<div class="vs-fund-table-row"><span>${f.timeRange || "-"}</span><span>$${this.formatNumber(tradeIn)}</span><span>$${this.formatNumber(tradeOut)}</span><span class="${netCls}">$${this.formatNumber(net)}</span></div>`;
        });
        return html + `</div></div>`;
    },

    _renderSupportResistance(sr, fund) {
        if (!sr.length) return "";
        const prices = sr.map(i => Number(i.price || 0)).filter(p => p > 0).sort((a, b) => a - b);
        const currentPrice = Number(fund.price || fund.spotGoodsList?.[0]?.tradeIn || 0) || (prices[Math.floor(prices.length / 2)] || 0);
        let html = `<div class="vs-sr-section"><div class="vs-metric-header">密集成交区 (压力 & 支撑)</div><div class="vs-sr-grid">`;
        sr.forEach(item => {
            const price = Number(item.price || 0);
            const date = item.date ? new Date(item.date).toLocaleDateString("zh-CN", { month: "short", day: "numeric" }) : "";
            const isBelow = price <= currentPrice;
            html += `<div class="vs-sr-item ${isBelow ? "vs-sr-support" : "vs-sr-resist"}">
                <span class="vs-sr-type">${isBelow ? "支撑" : "压力"}</span>
                <span class="vs-sr-price">$${this.formatNumber(price)}</span>
                ${date ? `<span class="vs-sr-vol">${date}</span>` : ""}
            </div>`;
        });
        return html + `</div></div>`;
    },

    _renderWhaleCost(whaleCost) {
        if (!whaleCost.length) return "";
        let html = `<div class="vs-whale-section"><div class="vs-metric-header">主力持仓成本 (近30天)</div>`;
        const latest = whaleCost[whaleCost.length - 1] || {};
        const latestCost = Number(latest.cost || 0), latestPrice = Number(latest.price || 0);
        const pnlPct = latestCost > 0 ? ((latestPrice - latestCost) / latestCost * 100) : 0;
        const pnlCls = pnlPct >= 0 ? "change-up" : "change-down";
        html += `<div class="vs-whale-summary">`;
        html += `<span>最新成本: <strong>$${this.formatNumber(latestCost)}</strong></span>`;
        html += `<span>当前价格: <strong>$${this.formatNumber(latestPrice)}</strong></span>`;
        html += `<span>浮盈: <strong class="${pnlCls}">${pnlPct >= 0 ? "+" : ""}${pnlPct.toFixed(2)}%</strong></span></div>`;
        html += `<div class="vs-whale-grid">`;
        whaleCost.slice(-10).forEach(item => {
            const date = item.date ? new Date(item.date).toLocaleDateString("zh-CN", { month: "short", day: "numeric" }) : "-";
            const cost = Number(item.cost || 0), price = Number(item.price || 0);
            const diff = cost > 0 ? ((price - cost) / cost * 100) : 0;
            const diffCls = diff >= 0 ? "change-up" : "change-down";
            html += `<div class="vs-whale-item"><span class="vs-whale-date">${date}</span><span class="vs-whale-cost">$${this.formatNumber(cost)}</span><span class="${diffCls}">${diff >= 0 ? "+" : ""}${diff.toFixed(1)}%</span></div>`;
        });
        return html + `</div></div>`;
    },

    // ── Whale On-chain ────────────────────────────────────────────
    async loadVsWhaleOnchain(symbol) {
        if (!this.elements.vsWhaleOnchainContent) return;
        const sym = (symbol || this.getActiveSymbol()).toUpperCase();
        if (this.elements.vsWhaleSymbolLabel) this.elements.vsWhaleSymbolLabel.textContent = sym;
        this.elements.vsWhaleOnchainContent.textContent = `加载 ${sym} 巨鲸链上数据...`;
        try {
            const resp = await fetch(`/api/dashboard/vs/whale-onchain?symbol=${encodeURIComponent(sym)}`);
            const data = await this.parseJsonResponse(resp);
            if (!data.ok) throw new Error(data.message || "加载失败");
            this._renderVsWhaleOnchain(data, sym);
        } catch (err) {
            this.elements.vsWhaleOnchainContent.innerHTML = `<div class="vs-fund-error">巨鲸数据加载失败: ${this.escapeHtml(err.message)}</div>`;
        }
    },

    _renderVsWhaleOnchain(data, symbol) {
        if (!this.elements.vsWhaleOnchainContent) return;
        const txns = data.largeTxns || [], holders = data.holders || [];
        let html = "";
        if (txns.length) {
            html += `<div class="vs-whale-block"><div class="vs-metric-header">大额链上交易 <small>(最新 ${txns.length} 笔)</small></div>`;
            html += `<div class="vs-txn-table"><div class="vs-txn-head"><span>时间</span><span>数量</span><span>来源</span><span>去向</span><span>TxHash</span></div>`;
            txns.forEach(tx => {
                const t = tx.blockTime ? new Date(tx.blockTime).toLocaleString("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "-";
                const amt = tx.amount ? this.formatNumber(Number(tx.amount)) : "-";
                const from = tx.fromExchangeName || this.shortenAddr(tx.fromAddress);
                const to = tx.toExchangeName || this.shortenAddr(tx.toAddress);
                const hash = tx.transHash || "", hashShort = hash ? hash.slice(0, 8) + "..." : "-";
                html += `<div class="vs-txn-row">
                    <span>${t}</span><span class="vs-txn-amount">${amt} ${symbol}</span>
                    <span class="${tx.fromExchangeName ? "vs-txn-exchange" : ""}">${this.escapeHtml(from || "未知")}</span>
                    <span class="${tx.toExchangeName ? "vs-txn-exchange" : ""}">${this.escapeHtml(to || "未知")}</span>
                    <span class="vs-txn-hash" title="${hash}">${hashShort}</span>
                </div>`;
            });
            html += `</div></div>`;
        }
        if (holders.length) {
            html += `<div class="vs-whale-block"><div class="vs-metric-header">Top 持仓地址</div>`;
            html += `<div class="vs-holder-table"><div class="vs-holder-head"><span>#</span><span>地址 / 标签</span><span>持仓量</span><span>持仓成本</span><span>浮盈</span></div>`;
            holders.forEach((h, i) => {
                const label = h.label ? (h.label.labelName || "") : "";
                const addrDisplay = label || this.shortenAddr(h.address);
                const labelIcon = h.label && h.label.labelType === "Exchange" ? "🏦 " : h.label && h.label.labelType ? "🏷️ " : "";
                const balance = h.balance ? this.formatNumber(Number(h.balance)) : "-";
                const cost = h.cost ? "$" + this.formatNumber(Number(h.cost)) : "-";
                const profit = h.profit ? Number(h.profit) : 0;
                const costChange = h.preCost && h.cost ? ((Number(h.cost) - Number(h.preCost)) / Number(h.preCost) * 100) : null;
                const costChangeHtml = costChange != null ? `<small class="${costChange >= 0 ? "change-up" : "change-down"}">${costChange >= 0 ? "+" : ""}${costChange.toFixed(2)}%</small>` : "";
                const addr = h.address || "";
                html += `<div class="vs-holder-row ${addr ? "vs-holder-clickable" : ""}" data-vs-addr="${addr}" data-vs-sym="${symbol}">
                    <span>${i + 1}</span><span class="vs-holder-addr" title="${addr}">${labelIcon}${this.escapeHtml(addrDisplay)}</span>
                    <span>${balance}</span><span>${cost} ${costChangeHtml}</span>
                    <span class="${profit >= 0 ? "change-up" : "change-down"}">$${this.formatNumber(profit)}</span>
                </div>`;
            });
            html += `</div></div>`;
        }
        if (!html) html = `<div class="vs-fund-error">暂无 ${symbol} 巨鲸链上数据</div>`;
        html += `<div class="onchain-desc">数据来源: ValueScan On-chain · 点击地址查看详情</div>`;
        this.elements.vsWhaleOnchainContent.innerHTML = html;
        this.elements.vsWhaleOnchainContent.querySelectorAll(".vs-holder-clickable").forEach(row => {
            row.addEventListener("click", () => {
                if (row.dataset.vsAddr) this.showVsAddressDetail(row.dataset.vsSym, row.dataset.vsAddr);
            });
        });
    },

    // ── Sector Fund Rotation ──────────────────────────────────────
    async loadVsSectorFund() {
        if (!this.elements.vsSectorContent) return;
        const tradeType = this.elements.vsSectorTypeSelect ? this.elements.vsSectorTypeSelect.value : "1";
        this.elements.vsSectorContent.textContent = "加载板块资金数据...";
        try {
            const resp = await fetch(`/api/dashboard/vs/sector-fund?trade_type=${tradeType}`);
            const data = await this.parseJsonResponse(resp);
            if (!data.ok) throw new Error(data.message || "加载失败");
            const sectors = data.sectors || [];
            this._renderVsSectorFund(sectors);
            if (typeof this.onVsSectorLoaded === "function") this.onVsSectorLoaded(sectors);
        } catch (err) {
            this.elements.vsSectorContent.innerHTML = `<div class="vs-fund-error">板块资金加载失败: ${this.escapeHtml(err.message)}</div>`;
        }
    },

    _renderVsSectorFund(sectors) {
        if (!this.elements.vsSectorContent) return;
        if (!sectors.length) { this.elements.vsSectorContent.innerHTML = "<div class='vs-fund-error'>暂无板块数据</div>"; return; }
        const getInflow = (s, r) => { const item = (s.categoriesTradeDataList || []).find(t => t.timeRange === r); return item ? Number(item.tradeInflow || 0) : 0; };
        const sorted = [...sectors].sort((a, b) => getInflow(b, "h1") - getInflow(a, "h1"));
        let html = `<div class="vs-sector-table"><div class="vs-sector-head"><span>板块</span><span>5m</span><span>15m</span><span>1h</span><span>4h</span><span>24h</span></div>`;
        sorted.forEach(s => {
            const name = s.tagsSimplified || s.tag || "-", tag = s.tag || "";
            const cells = ["m5", "m15", "h1", "h4", "d1"].map(r => {
                const v = getInflow(s, r), cls = v > 0 ? "change-up" : v < 0 ? "change-down" : "";
                return `<span class="${cls}">$${this.formatNumber(v)}</span>`;
            }).join("");
            html += `<div class="vs-sector-row vs-sector-clickable" data-vs-tag="${this.escapeHtml(tag)}"><span class="vs-sector-name">${this.escapeHtml(name)}</span>${cells}</div>`;
        });
        html += `</div>`;
        this.elements.vsSectorContent.innerHTML = html;
        this.elements.vsSectorContent.querySelectorAll(".vs-sector-clickable").forEach(row => {
            row.addEventListener("click", () => { if (row.dataset.vsTag) this.showVsSectorCoins(row.dataset.vsTag); });
        });
    },

    // ── Price Indicators ──────────────────────────────────────────
    async loadVsPriceIndicators(symbol) {
        if (!this.elements.vsIndicatorsContent) return;
        const sym = (symbol || this.getActiveSymbol()).toUpperCase();
        if (this.elements.vsIndicatorSymbolLabel) this.elements.vsIndicatorSymbolLabel.textContent = sym;
        this.elements.vsIndicatorsContent.textContent = `加载 ${sym} 价格指标...`;
        try {
            const resp = await fetch(`/api/dashboard/vs/price-indicators?symbol=${encodeURIComponent(sym)}`);
            const data = await this.parseJsonResponse(resp);
            if (!data.ok) throw new Error(data.message || "加载失败");
            this._renderVsPriceIndicators(data.indicators || [], sym);
        } catch (err) {
            this.elements.vsIndicatorsContent.innerHTML = `<div class="vs-fund-error">价格指标加载失败: ${this.escapeHtml(err.message)}</div>`;
        }
    },

    _renderVsPriceIndicators(indicators, symbol) {
        if (!this.elements.vsIndicatorsContent) return;
        if (!indicators.length) { this.elements.vsIndicatorsContent.innerHTML = `<div class="vs-fund-error">暂无 ${symbol} 价格指标数据</div>`; return; }
        const typeMap = { 1: { label: "看多 (Bull)", cls: "change-up" }, 2: { label: "看空 (Bear)", cls: "change-down" } };
        const recent = indicators.slice(0, 30);
        const bull = recent.filter(i => i.priceMarketType === 1).length;
        const bear = recent.filter(i => i.priceMarketType === 2).length;
        const total = bull + bear || 1;
        let html = `<div class="vs-indicator-summary"><span>近30条信号: </span><span class="change-up">看多 ${bull} (${(bull / total * 100).toFixed(0)}%)</span><span class="change-down">看空 ${bear} (${(bear / total * 100).toFixed(0)}%)</span></div>`;
        html += `<div class="vs-indicator-grid">`;
        recent.forEach(item => {
            const date = item.date ? new Date(item.date).toLocaleString("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "-";
            const info = typeMap[item.priceMarketType] || { label: String(item.priceMarketType), cls: "" };
            html += `<div class="vs-indicator-item"><span class="vs-indicator-date">${date}</span><span class="vs-indicator-signal ${info.cls}">${info.label}</span></div>`;
        });
        html += `</div><div class="onchain-desc">数据来源: ValueScan Price Market Indicators · ${symbol}</div>`;
        this.elements.vsIndicatorsContent.innerHTML = html;
    },

    // ── Modal helpers ─────────────────────────────────────────────
    openVsDetailModal(title, html) {
        if (this.elements.vsDetailModalTitle) this.elements.vsDetailModalTitle.textContent = title;
        if (this.elements.vsDetailModalBody) this.elements.vsDetailModalBody.innerHTML = html;
        if (this.elements.vsDetailModal) this.elements.vsDetailModal.classList.add("active");
    },

    closeVsDetailModal() {
        if (this.elements.vsDetailModal) this.elements.vsDetailModal.classList.remove("active");
    },

    async showVsAiMessages(symbol, type) {
        this.openVsDetailModal(`${symbol} AI 信号消息`, "<div class='vs-fund-error'>加载中...</div>");
        try {
            const resp = await fetch(`/api/dashboard/vs/ai-messages?symbol=${encodeURIComponent(symbol)}&msg_type=${type}`);
            const data = await this.parseJsonResponse(resp);
            if (!data.ok) throw new Error(data.message || "加载失败");
            const msgs = data.messages || [];
            if (!msgs.length) { this.openVsDetailModal(`${symbol} AI 信号`, "<div class='vs-fund-error'>暂无信号消息</div>"); return; }
            const typeLabel = { chance: "机会信号", risk: "风险信号", funds: "资金异动信号" }[type] || "信号";
            const msgTypeMap = { 1: "主力吸筹", 2: "突破信号", 3: "趋势启动", 4: "回调买入", 5: "放量突破", 6: "缩量回踩", 7: "底部信号", 8: "反转信号", 9: "主力派发", 10: "破位风险", 11: "见顶信号", 12: "超买风险", 13: "资金异动", 14: "主力入场", 15: "抛压预警", 16: "短线机会", 17: "趋势信号", 18: "量价配合", 19: "背离信号", 20: "突破回踩" };
            let html = `<div class="vs-metric-header">${typeLabel} (${msgs.length} 条)</div>`;
            html += msgs.map(m => {
                const t = m.updateTime ? new Date(m.updateTime).toLocaleString("zh-CN") : "";
                const msgType = m.chanceMessageType || m.riskMessageType || m.fundsMessageType || 0;
                const typeStr = msgTypeMap[msgType] || `信号#${msgType}`;
                const grade = m.grade ? "⭐".repeat(Math.min(m.grade, 5)) : "";
                const price = m.price ? `$${this.formatNumber(Number(m.price))}` : "";
                const change = m.percentChange24h != null ? `${m.percentChange24h >= 0 ? "+" : ""}${m.percentChange24h.toFixed(2)}%` : "";
                const changeCls = m.percentChange24h >= 0 ? "change-up" : "change-down";
                return `<div class="vs-msg-item"><span class="vs-msg-time">${t}</span><span class="vs-msg-text"><strong>${typeStr}</strong> ${grade} ${price} <span class="${changeCls}">${change}</span></span></div>`;
            }).join("");
            this.openVsDetailModal(`${symbol} ${typeLabel}`, html);
        } catch (err) {
            this.openVsDetailModal(`${symbol} AI 信号`, `<div class="vs-fund-error">${this.escapeHtml(err.message)}</div>`);
        }
    },

    async showVsAddressDetail(symbol, address) {
        const shortAddr = address.slice(0, 8) + "..." + address.slice(-6);
        this.openVsDetailModal(`${symbol} 地址分析 ${shortAddr}`, "<div class='vs-fund-error'>加载中...</div>");
        try {
            const resp = await fetch(`/api/dashboard/vs/address-detail?symbol=${encodeURIComponent(symbol)}&address=${encodeURIComponent(address)}`);
            const data = await this.parseJsonResponse(resp);
            if (!data.ok) throw new Error(data.message || "加载失败");
            let html = `<div class="vs-addr-header">${this.escapeHtml(address)}</div>`;
            const sections = [
                { key: "balanceTrend", label: "余额趋势", render: (item) => `${this.formatNumber(Number(item.balance || 0))} ${symbol}` },
                { key: "profitLossTrend", label: "盈亏趋势", render: (item) => { const t = Number(item.total || 0); return `<span class="${t >= 0 ? 'change-up' : 'change-down'}">$${this.formatNumber(t)}</span> (日: $${this.formatNumber(Number(item.day || 0))})`; } },
                { key: "holdTrend", label: "持仓成本趋势", render: (item) => `均价: $${this.formatNumber(Number(item.holdingPrice || 0))} / 现价: $${this.formatNumber(Number(item.price || 0))}` },
                { key: "tradeCountTrend", label: "交易数量趋势", render: (item) => `转入: ${item.toCount || 0} (${this.formatNumber(Number(item.toAmount || 0))}) / 转出: ${item.fromCount || 0} (${this.formatNumber(Number(item.fromAmount || 0))})` },
            ];
            sections.forEach(sec => {
                const items = data[sec.key] || [];
                if (!items.length) return;
                html += `<div class="vs-addr-section"><div class="vs-metric-header">${sec.label} (${items.length})</div><div class="vs-addr-trend">`;
                items.slice(-15).forEach(item => {
                    const date = item.date ? new Date(item.date).toLocaleDateString("zh-CN", { month: "short", day: "numeric" }) : "-";
                    html += `<div class="vs-addr-trend-item"><span>${date}</span><span>${sec.render(item)}</span></div>`;
                });
                html += `</div></div>`;
            });
            if (html.indexOf("vs-addr-section") < 0) html += "<div class='vs-fund-error'>暂无地址趋势数据</div>";
            this.openVsDetailModal(`${symbol} 地址分析`, html);
        } catch (err) {
            this.openVsDetailModal(`地址分析`, `<div class="vs-fund-error">${this.escapeHtml(err.message)}</div>`);
        }
    },

    async showVsSectorCoins(tag) {
        const tradeType = this.elements.vsSectorTypeSelect ? this.elements.vsSectorTypeSelect.value : "1";
        this.openVsDetailModal(`${tag} 板块代币资金`, "<div class='vs-fund-error'>加载中...</div>");
        try {
            const resp = await fetch(`/api/dashboard/vs/sector-coins?tag=${encodeURIComponent(tag)}&trade_type=${tradeType}`);
            const data = await this.parseJsonResponse(resp);
            if (!data.ok) throw new Error(data.message || "加载失败");
            const coins = data.coins || [];
            if (!coins.length) { this.openVsDetailModal(`${tag} 板块`, "<div class='vs-fund-error'>暂无代币数据</div>"); return; }
            let html = `<div class="vs-metric-header">${tag} 板块代币 (${coins.length})</div>`;
            html += `<div class="vs-fund-table"><div class="vs-fund-table-head"><span>代币</span><span>价格</span><span>1h 净流入</span><span>24h 净流入</span></div>`;
            coins.forEach(c => {
                const sym = c.symbol || c.tokenSymbol || "-";
                const price = c.price ? "$" + this.formatNumber(Number(c.price)) : "-";
                const trades = c.categoriesTradeDataList || c.coinTradeDataV1Vos || c.tradeDataList || [];
                const v1h = (trades.find(t => t.timeRange === "H1" || t.timeRange === "h1") || {}).tradeInflow || 0;
                const v24h = (trades.find(t => t.timeRange === "D1" || t.timeRange === "d1" || t.timeRange === "M1") || {}).tradeInflow || 0;
                html += `<div class="vs-fund-table-row">
                    <span class="vs-sector-name">${this.escapeHtml(sym)}</span><span>${price}</span>
                    <span class="${Number(v1h) >= 0 ? "change-up" : "change-down"}">$${this.formatNumber(Number(v1h))}</span>
                    <span class="${Number(v24h) >= 0 ? "change-up" : "change-down"}">$${this.formatNumber(Number(v24h))}</span>
                </div>`;
            });
            html += `</div>`;
            this.openVsDetailModal(`${tag} 板块代币资金`, html);
        } catch (err) {
            this.openVsDetailModal(`板块代币`, `<div class="vs-fund-error">${this.escapeHtml(err.message)}</div>`);
        }
    },
};
