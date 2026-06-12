/**
 * Web3 交易看板 - 投顾页面
 *
 * Architecture:
 *   dashboard-utils.js  — shared utilities (formatNumber, escapeHtml, …)
 *   dashboard-vs.js     — ValueScan module (VsMixin)
 *   dashboard.js        — core orchestrator (this file)
 */
class TradeDashboard {
    constructor() {
        this.state = {
            allTickers: [],
            filteredTickers: [],
            isLoading: false,
            modules: [],
            moduleSymbol: "",
            opportunityRadar: [],
            radarMeta: {},
            vsPicksIndex: { chance: new Set(), funds: new Set(), risk: new Set() },
            leadingSector: "",
            fearGreed: null,
            radarScanning: false,
        };

        const _el = (id) => document.getElementById(id);
        this.elements = {
            quoteSelect: _el("quoteSelect"), searchInput: _el("searchInput"),
            trendSelect: _el("trendSelect"), limitSelect: _el("limitSelect"),
            sortSelect: _el("sortSelect"),
            refreshBtn: _el("refreshBtn"), refreshModulesBtn: _el("refreshModulesBtn"),
            tableBody: _el("tickerTableBody"), analysisOutput: _el("analysisOutput"),
            modulesGrid: _el("modulesGrid"),
            opportunityModal: _el("opportunityModal"), opportunityModalTitle: _el("opportunityModalTitle"),
            opportunityModalMeta: _el("opportunityModalMeta"), opportunityModalBody: _el("opportunityModalBody"),
            closeOpportunityModal: _el("closeOpportunityModal"),
            symbolAnalyzeModal: _el("symbolAnalyzeModal"),
            symbolAnalyzeModalTitle: _el("symbolAnalyzeModalTitle"),
            symbolAnalyzeModalMeta: _el("symbolAnalyzeModalMeta"),
            symbolAnalyzeModalBody: _el("symbolAnalyzeModalBody"),
            closeSymbolAnalyzeModal: _el("closeSymbolAnalyzeModal"),
            statsCount: _el("statsCount"), statsUpRatio: _el("statsUpRatio"),
            statsAvgChange: _el("statsAvgChange"), statsVolume: _el("statsVolume"),
            statsQuantScore: _el("statsQuantScore"), statsOpportunityCount: _el("statsOpportunityCount"),
            opportunityRadarList: _el("opportunityRadarList"), radarOverview: _el("radarOverview"),
            refreshRadarBtn: _el("refreshRadarBtn"), radarLastRefresh: _el("radarLastRefresh"),
            radarBtcPulse: _el("radarBtcPulse"), radarEthPulse: _el("radarEthPulse"),
            radarFearGreed: _el("radarFearGreed"), radarSectorLead: _el("radarSectorLead"),
            researchDrawerToggle: _el("researchDrawerToggle"), researchDrawerBody: _el("researchDrawerBody"),
            newsList: _el("newsList"), refreshNewsBtn: _el("refreshNewsBtn"), newsSymbolLabel: _el("newsSymbolLabel"),
            narrativeContent: _el("narrativeContent"), refreshNarrativeBtn: _el("refreshNarrativeBtn"),
            narrativeSymbolLabel: _el("narrativeSymbolLabel"),
        };

        // Merge VS elements
        if (typeof VsMixin !== "undefined" && VsMixin.VS_ELEMENT_IDS) {
            VsMixin.VS_ELEMENT_IDS.forEach(id => { this.elements[id] = _el(id); });
        }
        if (typeof DexMixin !== "undefined" && DexMixin.DEX_ELEMENT_IDS) {
            DexMixin.DEX_ELEMENT_IDS.forEach(id => { this.elements[id] = _el(id); });
        }
    }

    init() {
        try { this.bindEvents(); } catch (e) { console.error("[Dashboard] bindEvents error:", e); }
        try { this.bindVsEvents(); } catch (e) { console.error("[Dashboard] bindVsEvents error:", e); }
        try { this.bindDexEvents(); } catch (e) { console.error("[Dashboard] bindDexEvents error:", e); }
        this.loadTickers();
        this.loadOpportunityRadar();
        this.loadRadarContext();
        this.loadVsAiPicks();
        this.refreshInsightPanels();
    }

    async loadRadarContext() {
        try {
            const resp = await fetch("/api/dashboard/onchain?symbol=BTC&limit=1");
            const data = await this.parseJsonResponse(resp);
            if (data.ok) {
                const fg = (data.marketSentiment || {}).fearGreed || {};
                this.state.fearGreed = fg;
                this.renderRadarTopBar();
            }
        } catch (_e) { /* optional */ }
    }

    getActiveSymbol() {
        const search = (this.elements.searchInput.value || "").trim().toUpperCase();
        if (/^[A-Z0-9]+$/.test(search)) return search;
        return "BTC";
    }

    refreshCoinData() {
        const sym = this.getActiveSymbol();
        this.refreshVsData(sym);
        this.refreshDexData(sym);
        this.refreshInsightPanels(sym);
    }

    refreshInsightPanels(symbol) {
        const sym = (symbol || this.getActiveSymbol()).toUpperCase();
        this.loadNews(sym);
        this.loadNarrative(sym);
    }

    bindEvents() {
        this.elements.refreshBtn.addEventListener("click", () => this.loadTickers());
        if (this.elements.refreshRadarBtn) {
            this.elements.refreshRadarBtn.addEventListener("click", () => this.loadOpportunityRadar());
        }
        this.elements.quoteSelect.addEventListener("change", () => this.loadTickers());
        this._searchDebounceTimer = null;
        this.elements.searchInput.addEventListener("input", () => {
            this.applyFilters();
            clearTimeout(this._searchDebounceTimer);
            this._searchDebounceTimer = setTimeout(() => this.refreshCoinData(), 600);
        });
        this.elements.trendSelect.addEventListener("change", () => this.applyFilters());
        this.elements.limitSelect.addEventListener("change", () => this.applyFilters());
        this.elements.sortSelect.addEventListener("change", () => this.applyFilters());
        window.addEventListener("resize", () => {});
        if (this.elements.refreshModulesBtn) {
            this.elements.refreshModulesBtn.addEventListener("click", () => this.loadModulesData());
        }
        if (this.elements.refreshNewsBtn) {
            this.elements.refreshNewsBtn.addEventListener("click", () => this.loadNews(this.getActiveSymbol()));
        }
        if (this.elements.refreshNarrativeBtn) {
            this.elements.refreshNarrativeBtn.addEventListener("click", () => this.loadNarrative(this.getActiveSymbol()));
        }
        if (this.elements.closeOpportunityModal) {
            this.elements.closeOpportunityModal.addEventListener("click", (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.hideOpportunityModal();
            });
        }
        if (this.elements.opportunityModal) {
            this.elements.opportunityModal.addEventListener("click", (event) => {
                if (event.target === this.elements.opportunityModal) this.hideOpportunityModal();
            });
        }
        if (this.elements.closeSymbolAnalyzeModal) {
            this.elements.closeSymbolAnalyzeModal.addEventListener("click", (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.hideSymbolAnalyzeModal();
            });
        }
        if (this.elements.symbolAnalyzeModal) {
            this.elements.symbolAnalyzeModal.addEventListener("click", (event) => {
                if (event.target === this.elements.symbolAnalyzeModal) this.hideSymbolAnalyzeModal();
            });
        }
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape") {
                this.hideOpportunityModal();
                this.hideSymbolAnalyzeModal();
            }
        });
        this.initSideNav();
    }

    async loadTickers() {
        const quote = this.elements.quoteSelect.value;
        this.state.isLoading = true;
        this.renderLoading("加载行情中...");
        try {
            const response = await fetch(`/api/market/tickers?quote=${encodeURIComponent(quote)}&limit=300`);
            const data = await this.parseJsonResponse(response);
            if (!response.ok || !data.ok) throw new Error(data.message || "行情加载失败");
            this.state.allTickers = data.tickers || [];
            this.applyFilters();
            this.renderRadarTopBar();
        } catch (error) {
            this.renderLoading(`加载失败: ${error.message}`);
        } finally {
            this.state.isLoading = false;
        }
    }

    applyFilters() {
        const search = (this.elements.searchInput.value || "").trim().toUpperCase();
        const trend = this.elements.trendSelect.value;
        const limit = Number(this.elements.limitSelect.value || "50");
        const sortBy = this.elements.sortSelect.value || "volValue_desc";
        let list = [...this.state.allTickers];
        if (search) list = list.filter((item) => item.symbol.toUpperCase().includes(search));
        if (trend === "gainers") list = list.filter((item) => item.changeRate > 0);
        else if (trend === "losers") list = list.filter((item) => item.changeRate < 0);
        list = this.enrichQuantMetrics(list);
        list = this.sortTickers(list, sortBy);
        list = list.slice(0, Math.max(1, limit));
        this.state.filteredTickers = list;
        this.renderTable();
        this.renderStats();
    }

    renderLoading(text) {
        this.elements.tableBody.innerHTML = `<tr><td colspan="8" class="empty-row">${text}</td></tr>`;
    }

    extractBaseSymbol(symbol) {
        const upper = String(symbol || "").toUpperCase();
        return upper.includes("-") ? upper.split("-")[0] : upper;
    }

    onVsPicksLoaded(data) {
        const toSet = (items) => new Set((items || []).map((i) => this.extractBaseSymbol(i.symbol || i.tokenSymbol)));
        this.state.vsPicksIndex = {
            chance: toSet(data.chance),
            funds: toSet(data.funds),
            risk: toSet(data.risk),
        };
        this.renderOpportunityRadar();
        if (this.state.filteredTickers.length) this.renderTable();
    }

    onVsSectorLoaded(sectors) {
        if (!Array.isArray(sectors) || !sectors.length) return;
        const getInflow = (s, r) => {
            const item = (s.categoriesTradeDataList || []).find((t) => t.timeRange === r);
            return item ? Number(item.tradeInflow || 0) : 0;
        };
        const top = [...sectors].sort((a, b) => getInflow(b, "h1") - getInflow(a, "h1"))[0];
        this.state.leadingSector = top ? (top.tagsSimplified || top.tag || "") : "";
        this.renderRadarTopBar();
    }

    getConfluenceTags(base) {
        const sym = String(base || "").toUpperCase();
        const idx = this.state.vsPicksIndex || {};
        const tags = [];
        if (idx.chance && idx.chance.has(sym)) tags.push({ label: "VS机会", cls: "conf-vs-chance" });
        if (idx.funds && idx.funds.has(sym)) tags.push({ label: "资金异动", cls: "conf-vs-funds" });
        if (idx.risk && idx.risk.has(sym)) tags.push({ label: "风险", cls: "conf-vs-risk" });
        const radarHit = (this.state.opportunityRadar || []).some((o) => this.extractBaseSymbol(o.symbol) === sym);
        if (radarHit) tags.push({ label: "雷达", cls: "conf-radar" });
        const ticker = this.state.filteredTickers.find((t) => this.extractBaseSymbol(t.symbol) === sym);
        if (ticker && ["A+", "A"].includes(ticker.opportunityLevel)) tags.push({ label: "高分", cls: "conf-quant" });
        const bullish = tags.some((t) => ["VS机会", "资金异动", "雷达", "高分"].includes(t.label));
        const bearish = tags.some((t) => t.label === "风险");
        const strong = bullish && tags.filter((t) => t.label !== "风险").length >= 2;
        if (strong) tags.unshift({ label: "强共振", cls: "conf-strong" });
        else if (bearish && bullish) tags.unshift({ label: "分歧", cls: "conf-mixed" });
        return tags;
    }

    renderConfluenceHtml(base, compact) {
        const tags = this.getConfluenceTags(base);
        if (!tags.length) return `<span class="conf-empty">-</span>`;
        if (compact) {
            const strong = tags.find((t) => t.label === "强共振");
            if (strong) return `<span class="conf-tag ${strong.cls}">${strong.label}</span>`;
            const radar = tags.find((t) => t.label === "雷达");
            if (radar) return `<span class="conf-tag ${radar.cls}">${radar.label}</span>`;
            return `<span class="conf-empty">-</span>`;
        }
        return tags.map((t) => `<span class="conf-tag ${t.cls}">${t.label}</span>`).join("");
    }

    renderSparkline(item) {
        const low = Number(item.low || 0), high = Number(item.high || 0), last = Number(item.last || 0);
        const range = high - low;
        if (range <= 0 || last <= 0) return `<span class="spark-empty">-</span>`;
        const pct = Math.max(0, Math.min(100, ((last - low) / range) * 100));
        const changeClass = item.changeRate >= 0 ? "spark-up" : "spark-down";
        return `<div class="spark-bar ${changeClass}" title="24h 区间位置 ${pct.toFixed(0)}%">
            <div class="spark-track"><div class="spark-fill" style="width:${pct}%"></div><div class="spark-dot" style="left:${pct}%"></div></div>
        </div>`;
    }

    async loadOpportunityRadar() {
        const listEl = this.elements.opportunityRadarList;
        const overviewEl = this.elements.radarOverview;
        if (!listEl) return;
        if (this.state.radarScanning) return;
        this.state.radarScanning = true;
        if (this.elements.refreshRadarBtn) {
            this.elements.refreshRadarBtn.disabled = true;
            this.elements.refreshRadarBtn.textContent = "扫描中...";
        }
        listEl.innerHTML = `<div class="radar-loading"><div class="radar-loading-spinner"></div><span>正在扫描高流动性标的...</span></div>`;
        if (overviewEl) overviewEl.textContent = "多源信号扫描进行中...";
        try {
            const resp = await fetch("/api/dashboard/opportunity-scan?topK=5&maxSymbols=30&minVolume24h=200000");
            const data = await this.parseJsonResponse(resp);
            if (!resp.ok || !data.ok) throw new Error(data.message || "机会扫描失败");
            this.state.opportunityRadar = data.opportunities || [];
            this.state.radarMeta = {
                overview: data.marketOverview || "",
                scanTime: data.scanTime,
                duration: data.scanDurationMs,
                total: data.totalScanned,
            };
            this.renderOpportunityRadar();
            this.renderRadarTopBar();
            if (this.state.filteredTickers.length) this.renderTable();
        } catch (error) {
            listEl.innerHTML = `<div class="radar-error">扫描失败: ${this.escapeHtml(error.message)}</div>`;
            if (overviewEl) overviewEl.textContent = "请稍后重试或点击「扫描机会」";
        } finally {
            this.state.radarScanning = false;
            if (this.elements.refreshRadarBtn) {
                this.elements.refreshRadarBtn.disabled = false;
                this.elements.refreshRadarBtn.textContent = "扫描机会";
            }
        }
    }

    renderOpportunityRadar() {
        const listEl = this.elements.opportunityRadarList;
        const overviewEl = this.elements.radarOverview;
        if (!listEl) return;
        const items = this.state.opportunityRadar || [];
        const meta = this.state.radarMeta || {};
        if (overviewEl) {
            const dur = meta.duration ? ` · ${(meta.duration / 1000).toFixed(1)}s` : "";
            overviewEl.textContent = meta.overview ? `${meta.overview}${dur}` : (items.length ? `已扫描 ${meta.total || items.length} 个标的` : "暂无扫描结果");
        }
        if (!items.length) {
            listEl.innerHTML = `<div class="radar-empty">暂无符合条件的机会，可调整筛选或稍后重试</div>`;
            return;
        }
        listEl.innerHTML = items.map((item, idx) => {
            const base = this.extractBaseSymbol(item.symbol);
            const pair = item.pair || `${base}-USDT`;
            const change = Number(item.change24h || 0);
            const changeClass = change >= 0 ? "change-up" : "change-down";
            const signedRate = `${change >= 0 ? "+" : ""}${(change * 100).toFixed(2)}%`;
            const signalClass = this.getSignalClass(item.signal);
            const confTags = this.getConfluenceTags(base);
            const isStrong = confTags.some((t) => t.label === "强共振");
            const featured = idx === 0 ? " radar-card-featured" : "";
            const strongCls = isStrong ? " radar-card-strong" : "";
            const confHtml = this.renderConfluenceHtml(base, !isStrong);
            const reasons = (item.keyReasons || []).slice(0, 2).map((r) => this.escapeHtml(r)).join(" · ");
            const score = Number(item.score || 0);
            const conf = Number(item.confidence || 0);
            const scoreRingPct = Math.min(100, Math.abs(score));
            return `<article class="radar-card ${signalClass}${featured}${strongCls}">
                <div class="radar-card-rank-col">
                    <div class="radar-card-rank">#${item.rank || idx + 1}</div>
                    <div class="radar-score-ring" style="--ring-pct:${scoreRingPct}">
                        <span class="radar-score-num tabnum">${score >= 0 ? "+" : ""}${score.toFixed(0)}</span>
                    </div>
                </div>
                <div class="radar-card-main">
                    <div class="radar-card-head">
                        <span class="radar-card-symbol">${this.escapeHtml(base)}</span>
                        <span class="radar-card-signal signal-pill">${this.escapeHtml(item.label || item.signal || "中性")}</span>
                        ${isStrong ? `<span class="radar-strong-badge">强共振</span>` : ""}
                    </div>
                    <div class="radar-card-metrics">
                        <div class="radar-metric radar-metric-change ${changeClass}">
                            <span class="radar-metric-label">24h</span>
                            <span class="radar-metric-value tabnum">${signedRate}</span>
                        </div>
                        <div class="radar-metric">
                            <span class="radar-metric-label">置信度</span>
                            <span class="radar-metric-value tabnum">${conf.toFixed(0)}%</span>
                        </div>
                        <div class="radar-metric">
                            <span class="radar-metric-label">成交额</span>
                            <span class="radar-metric-value tabnum">$${this.formatNumber(item.volume24h || 0)}</span>
                        </div>
                    </div>
                    ${reasons ? `<div class="radar-card-reason">${reasons}</div>` : ""}
                    <div class="radar-card-tags">${confHtml}</div>
                </div>
                <div class="radar-card-actions">
                    <a class="btn btn-primary btn-sm" href="/analysis?symbol=${encodeURIComponent(pair)}">深度分析</a>
                    <button class="btn btn-ghost btn-sm" data-radar-analyze="${this.escapeHtml(pair)}">快速分析</button>
                </div>
            </article>`;
        }).join("");
        listEl.querySelectorAll("[data-radar-analyze]").forEach((btn) => {
            btn.addEventListener("click", (event) => {
                event.stopPropagation();
                const pair = btn.dataset.radarAnalyze;
                if (pair) this.analyzeSymbol(pair);
            });
        });
    }

    getSignalClass(signal) {
        const s = String(signal || "").toUpperCase();
        if (s === "BUY") return "radar-buy";
        if (s === "WEAK_BUY") return "radar-weak-buy";
        if (s === "SELL") return "radar-sell";
        if (s === "WEAK_SELL") return "radar-weak-sell";
        return "radar-neutral";
    }

    renderRadarTopBar() {
        const findTicker = (base) => this.state.allTickers.find((t) => this.extractBaseSymbol(t.symbol) === base);
        const renderPulse = (el, base) => {
            if (!el) return;
            const t = findTicker(base);
            const valEl = el.querySelector(".pulse-ticker-value");
            if (!valEl) return;
            if (!t) { valEl.textContent = "-"; valEl.className = "pulse-ticker-value tabnum"; return; }
            const rate = Number(t.changeRate || 0);
            const cls = rate >= 0 ? "change-up" : "change-down";
            valEl.className = `pulse-ticker-value tabnum ${cls}`;
            valEl.textContent = `${rate >= 0 ? "+" : ""}${(rate * 100).toFixed(2)}%`;
        };
        renderPulse(this.elements.radarBtcPulse, "BTC");
        renderPulse(this.elements.radarEthPulse, "ETH");
        const fgEl = this.elements.radarFearGreed;
        if (fgEl) {
            const valEl = fgEl.querySelector(".pulse-chip-value");
            const fg = this.state.fearGreed || {};
            if (valEl) {
                const v = fg.value;
                valEl.textContent = v != null ? `${v}${fg.label ? ` · ${fg.label}` : ""}` : "-";
                valEl.className = "pulse-chip-value tabnum";
                if (v != null) {
                    if (v <= 25) valEl.classList.add("fg-extreme-fear");
                    else if (v <= 45) valEl.classList.add("fg-fear");
                    else if (v >= 75) valEl.classList.add("fg-greed");
                    else if (v >= 55) valEl.classList.add("fg-mild-greed");
                }
            }
        }
        const sectorEl = this.elements.radarSectorLead;
        if (sectorEl) {
            const valEl = sectorEl.querySelector(".pulse-chip-value");
            if (valEl) {
                valEl.textContent = this.state.leadingSector || "-";
                valEl.classList.toggle("pulse-sector-hot", Boolean(this.state.leadingSector));
            }
        }
        if (this.elements.radarLastRefresh) {
            const ts = this.state.radarMeta.scanTime;
            if (ts) {
                const d = new Date(ts);
                this.elements.radarLastRefresh.textContent = d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
            }
        }
    }

    renderTable() {
        const rows = this.state.filteredTickers;
        if (rows.length === 0) {
            this.renderLoading("没有匹配的数据");
            return;
        }
        this.elements.tableBody.innerHTML = rows.map((item) => {
            const changeClass = item.changeRate >= 0 ? "change-up" : "change-down";
            const signedRate = `${item.changeRate >= 0 ? "+" : ""}${(item.changeRate * 100).toFixed(2)}%`;
            const scoreClass = this.getScoreClass(item.quantScore);
            const opportunityClass = this.getOpportunityClass(item.opportunityLevel);
            const base = this.extractBaseSymbol(item.symbol);
            const confTags = this.getConfluenceTags(base);
            const isStrong = confTags.some((t) => t.label === "强共振");
            const rowClass = [isStrong ? "row-strong-conf" : "", ["A+", "A"].includes(item.opportunityLevel) ? "row-high-opp" : ""].filter(Boolean).join(" ");
            return `<tr class="${rowClass}">
                <td class="cell-symbol"><div class="cell-symbol-wrap"><button type="button" class="symbol-detail-btn" data-symbol-detail="${item.symbol}"><span class="symbol-base">${base}</span><span class="symbol-quote">${item.symbol.includes("-") ? item.symbol.split("-")[1] : ""}</span></button><button type="button" class="row-analyze-btn" data-symbol-analyze="${item.symbol}">分析</button></div></td>
                <td>${this.renderSparkline(item)}</td>
                <td class="tabnum cell-price">${this.formatNumber(item.last)}</td>
                <td class="${changeClass} cell-change tabnum">${signedRate}</td>
                <td class="tabnum cell-vol">${this.formatNumber(item.volValue)}</td>
                <td class="quant-score ${scoreClass} tabnum">${(item.quantScore || 0).toFixed(1)}</td>
                <td><span class="opportunity-badge ${opportunityClass} opp-badge-lg">${item.opportunityLevel || "D"}</span></td>
                <td class="conf-cell">${this.renderConfluenceHtml(base, true)}</td>
            </tr>`;
        }).join("");
        this.elements.tableBody.querySelectorAll("[data-symbol-detail]").forEach((btn) => {
            btn.addEventListener("click", () => {
                const symbol = btn.dataset.symbolDetail;
                if (!symbol) return;
                const base = this.extractBaseSymbol(symbol);
                if (this.elements.searchInput) this.elements.searchInput.value = base;
                this.refreshInsightPanels(base);
                this.openOpportunityModal(symbol);
            });
        });
        this.elements.tableBody.querySelectorAll("[data-symbol-analyze]").forEach((btn) => {
            btn.addEventListener("click", (event) => {
                event.stopPropagation();
                const symbol = btn.dataset.symbolAnalyze;
                if (!symbol) return;
                const base = this.extractBaseSymbol(symbol);
                if (this.elements.searchInput) this.elements.searchInput.value = base;
                this.refreshInsightPanels(base);
                this.analyzeSymbol(symbol);
            });
        });
    }

    renderStats() {
        const rows = this.state.filteredTickers;
        if (rows.length === 0) {
            ["statsCount", "statsUpRatio", "statsAvgChange", "statsVolume", "statsQuantScore", "statsOpportunityCount"].forEach((id) => { this.elements[id].textContent = "-"; });
            return;
        }
        const upCount = rows.filter((item) => item.changeRate > 0).length;
        const avgChange = rows.reduce((sum, item) => sum + item.changeRate, 0) / rows.length;
        const totalVolValue = rows.reduce((sum, item) => sum + item.volValue, 0);
        const avgQuantScore = rows.reduce((sum, item) => sum + Number(item.quantScore || 0), 0) / rows.length;
        const opportunityCount = rows.filter((item) => ["A+", "A", "B"].includes(item.opportunityLevel)).length;
        this.elements.statsCount.textContent = `${rows.length}`;
        this.elements.statsUpRatio.textContent = `${((upCount / rows.length) * 100).toFixed(1)}%`;
        this.elements.statsAvgChange.textContent = `${avgChange >= 0 ? "+" : ""}${(avgChange * 100).toFixed(2)}%`;
        this.elements.statsVolume.textContent = this.formatNumber(totalVolValue);
        this.elements.statsQuantScore.textContent = avgQuantScore.toFixed(1);
        this.elements.statsOpportunityCount.textContent = `${opportunityCount}`;
        const highlight = document.getElementById("pulseHighlightOpp");
        if (highlight) {
            highlight.classList.toggle("pulse-highlight-active", opportunityCount > 0);
            highlight.classList.toggle("pulse-highlight-hot", opportunityCount >= 3);
        }
    }

    openSymbolAnalyzeModal(symbols, metaText) {
        if (!this.elements.symbolAnalyzeModal) return;
        const list = Array.isArray(symbols) ? symbols : [symbols];
        const label = list.length === 1 ? list[0] : `${list.length} 个币种`;
        if (this.elements.symbolAnalyzeModalTitle) {
            this.elements.symbolAnalyzeModalTitle.textContent = list.length === 1 ? `${list[0]} 分析` : "批量分析";
        }
        if (this.elements.symbolAnalyzeModalMeta) {
            this.elements.symbolAnalyzeModalMeta.textContent = metaText || label;
        }
        if (this.elements.symbolAnalyzeModalBody) {
            this.elements.symbolAnalyzeModalBody.textContent = "分析中，请稍候...";
        }
        this.elements.symbolAnalyzeModal.classList.add("active");
    }

    hideSymbolAnalyzeModal() {
        if (this.elements.symbolAnalyzeModal) {
            this.elements.symbolAnalyzeModal.classList.remove("active");
        }
    }

    async fetchModulesForSymbol(symbol) {
        try {
            const response = await fetch(`/api/skills/modules?symbol=${encodeURIComponent(symbol)}`);
            const data = await this.parseJsonResponse(response);
            if (!response.ok || !data.ok) return [];
            return Array.isArray(data.modules) ? data.modules : [];
        } catch (_e) {
            return [];
        }
    }

    buildAnalyzeMeta(symbols) {
        return symbols.map((sym) => {
            const item = this.state.filteredTickers.find((row) => String(row.symbol || "").toUpperCase() === String(sym).toUpperCase());
            if (!item) return sym;
            const rate = `${item.changeRate >= 0 ? "+" : ""}${(item.changeRate * 100).toFixed(2)}%`;
            return `${sym} · 24h ${rate} · 机会 ${item.opportunityLevel || "D"} · 评分 ${Number(item.quantScore || 0).toFixed(1)}`;
        }).join("\n");
    }

    async requestSkillsAnalysis(symbols, moduleSnapshot) {
        const response = await fetch("/api/skills/analyze", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                symbols,
                focus: "从量化分析 + 机会分析角度输出交易决策，必须给出优先级、建议入场区间、止损位、失效条件与仓位建议。",
                quantSnapshot: this.collectQuantSnapshot(symbols),
                moduleSnapshot: moduleSnapshot || { symbol: symbols[0], modules: [] },
            }),
        });
        const data = await this.parseJsonResponse(response);
        if (!response.ok || !data.ok) throw new Error(data.message || "分析失败");
        return data.content || "(无分析结果)";
    }

    async analyzeSymbol(symbol) {
        const sym = this.normalizeSymbolInput(symbol);
        if (!sym) return;
        const btn = this.elements.tableBody?.querySelector(`[data-symbol-analyze="${sym}"]`)
            || this.elements.tableBody?.querySelector(`[data-symbol-analyze="${symbol}"]`);
        if (btn) btn.disabled = true;
        this.openSymbolAnalyzeModal([sym], this.buildAnalyzeMeta([sym]));
        try {
            const modules = await this.fetchModulesForSymbol(sym);
            const content = await this.requestSkillsAnalysis([sym], { symbol: sym, modules });
            if (this.elements.symbolAnalyzeModalBody) {
                this.elements.symbolAnalyzeModalBody.textContent = content;
            }
        } catch (error) {
            if (this.elements.symbolAnalyzeModalBody) {
                this.elements.symbolAnalyzeModalBody.textContent = `分析失败: ${error.message}`;
            }
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    getPrimarySymbol() {
        if (this.state.filteredTickers.length > 0) return this.state.filteredTickers[0].symbol;
        const sym = this.getActiveSymbol();
        const quote = String(this.elements.quoteSelect?.value || "USDT").trim().toUpperCase();
        return `${sym}-${quote}`;
    }

    async loadModulesData() {
        if (!this.elements.modulesGrid) return;
        const symbol = this.getPrimarySymbol();
        this.state.moduleSymbol = symbol;
        this.elements.modulesGrid.innerHTML = `<div class="module-data">加载 ${symbol} 的技能模块数据中...</div>`;
        try {
            const response = await fetch(`/api/skills/modules?symbol=${encodeURIComponent(symbol)}`);
            const data = await this.parseJsonResponse(response);
            if (!response.ok || !data.ok) throw new Error(data.message || "技能模块加载失败");
            this.state.modules = Array.isArray(data.modules) ? data.modules : [];
            this.renderModules();
        } catch (error) {
            this.elements.modulesGrid.innerHTML = `<div class="module-data">加载失败: ${error.message}</div>`;
        }
    }

    normalizeSymbolInput(raw) {
        const upper = String(raw || "").trim().toUpperCase().replace(/\s+/g, "").replace(/\//g, "-").replace(/_/g, "-");
        if (/^[A-Z0-9]+-[A-Z0-9]+$/.test(upper)) return upper;
        if (/^[A-Z0-9]+$/.test(upper)) {
            const quote = String(this.elements.quoteSelect.value || "USDT").trim().toUpperCase();
            return `${upper}-${quote}`;
        }
        return upper;
    }

    renderModules() {
        const modules = this.state.modules || [];
        if (modules.length === 0) {
            this.elements.modulesGrid.innerHTML = `<div class="module-data">暂无模块数据</div>`;
            return;
        }
        this.elements.modulesGrid.innerHTML = modules.map((module) => {
            const status = module.status || "unknown";
            const className = status === "ok"
                ? "module-ok"
                : status === "unavailable"
                    ? "module-warn"
                    : status === "auth_required"
                        ? "module-auth"
                        : "module-error";
            const meta = `${status.toUpperCase()} • ${module.latencyMs || 0}ms`;
            let dataText = "";
            if (status === "ok") {
                dataText = this.toPrettySummary(module.data);
            } else if (status === "unavailable" || status === "auth_required") {
                dataText = [module.note, module.data ? this.toPrettySummary(module.data) : ""].filter(Boolean).join("\n\n");
            } else {
                dataText = module.note || module.error || "无详细信息";
            }
            return `<article class="module-card">
                <h4>${module.name || "unknown"}</h4>
                <div class="module-meta ${className}">${meta}</div>
                <div class="module-data">${dataText}</div>
            </article>`;
        }).join("");
    }

    toPrettySummary(data) {
        if (!data || typeof data !== "object") return "-";
        const raw = JSON.stringify(data, null, 2);
        return raw.length > 1200 ? `${raw.slice(0, 1200)} ...` : raw;
    }

    sortTickers(list, sortBy) {
        const sorted = [...list];
        if (sortBy === "changeRate_desc") { sorted.sort((a, b) => b.changeRate - a.changeRate); return sorted; }
        if (sortBy === "changeRate_asc") { sorted.sort((a, b) => a.changeRate - b.changeRate); return sorted; }
        if (sortBy === "volatility_desc") { sorted.sort((a, b) => this.computeVolatility(b) - this.computeVolatility(a)); return sorted; }
        if (sortBy === "quant_score_desc") { sorted.sort((a, b) => Number(b.quantScore || 0) - Number(a.quantScore || 0)); return sorted; }
        sorted.sort((a, b) => b.volValue - a.volValue);
        return sorted;
    }

    enrichQuantMetrics(list) {
        if (!Array.isArray(list) || list.length === 0) return [];
        const liquidities = list.map((item) => Math.log10(Math.max(1, Number(item.volValue || 0))));
        const volatilities = list.map((item) => this.computeVolatility(item));
        const momentums = list.map((item) => Number(item.changeRate || 0));
        return list.map((item) => {
            const liquidityRaw = Math.log10(Math.max(1, Number(item.volValue || 0)));
            const volatilityRaw = this.computeVolatility(item);
            const momentumRaw = Number(item.changeRate || 0);
            const liquidityPct = this.rankPercentile(liquidities, liquidityRaw);
            const volatilityPct = this.rankPercentile(volatilities, volatilityRaw);
            const momentumPct = this.rankPercentile(momentums, momentumRaw);
            const quantScore = liquidityPct * 35 + volatilityPct * 30 + momentumPct * 25 + (momentumRaw > 0 ? 10 : 0);
            const boundedScore = Math.max(0, Math.min(100, quantScore));
            const opportunityLevel = this.getOpportunityLevel(boundedScore, momentumRaw, volatilityRaw);
            return { ...item, quant: { liquidityPct, volatilityPct, momentumPct, volatilityRaw }, quantScore: boundedScore, opportunityLevel };
        });
    }

    rankPercentile(values, target) {
        if (!Array.isArray(values) || values.length === 0) return 0;
        const sorted = [...values].sort((a, b) => a - b);
        let rank = 0;
        for (const value of sorted) { if (value <= target) rank += 1; }
        return rank / sorted.length;
    }

    getOpportunityLevel(score, momentum, volatility) {
        if (score >= 80 && momentum > 0 && volatility > 0.008) return "A+";
        if (score >= 70 && momentum >= 0) return "A";
        if (score >= 58) return "B";
        if (score >= 45) return "C";
        return "D";
    }

    getScoreClass(score) {
        if (score >= 70) return "score-high";
        if (score >= 50) return "score-mid";
        return "score-low";
    }

    getOpportunityClass(level) {
        if (level === "A+" || level === "A") return "opp-a";
        if (level === "B") return "opp-b";
        if (level === "C") return "opp-c";
        return "opp-d";
    }

    collectQuantSnapshot(symbols) {
        const selected = new Set((symbols || []).map((s) => String(s).toUpperCase()));
        return this.state.filteredTickers.filter((item) => selected.has(String(item.symbol || "").toUpperCase())).map((item) => ({
            symbol: item.symbol, last: item.last, changeRate: item.changeRate, volValue: item.volValue,
            quantScore: Number(item.quantScore || 0), opportunityLevel: item.opportunityLevel || "D", quant: item.quant || {},
        }));
    }

    openOpportunityModal(symbol) {
        if (!this.elements.opportunityModal) return;
        const item = this.state.filteredTickers.find((row) => String(row.symbol || "").toUpperCase() === String(symbol || "").toUpperCase());
        if (!item) return;
        const volatility = this.computeVolatility(item);
        const momentum = Number(item.changeRate || 0);
        const direction = momentum >= 0 ? "顺势多头观察" : "逆势反弹观察";
        const entryLower = momentum >= 0 ? item.last * 0.992 : item.last * 0.998;
        const entryUpper = momentum >= 0 ? item.last * 1.003 : item.last * 1.008;
        const stopLoss = momentum >= 0 ? item.low * 0.997 : item.high * 1.003;
        const target1 = momentum >= 0 ? item.high * 1.005 : item.low * 0.995;
        const invalid = momentum >= 0 ? "量价背离且跌破日内低点" : "跌势延续且放量破前低";
        const quant = item.quant || {};
        const timeframePlans = this.buildTimeframePlans(item, momentum, volatility);
        this.elements.opportunityModalTitle.textContent = `${item.symbol} 机会解释`;
        this.elements.opportunityModalMeta.innerHTML = `机会等级: <strong>${item.opportunityLevel || "D"}</strong> · 量化评分: <strong>${Number(item.quantScore || 0).toFixed(1)}</strong> · 方向: <strong>${direction}</strong>`;
        this.elements.opportunityModalBody.textContent =
            `因子拆解\n- 流动性分位: ${(Number(quant.liquidityPct || 0) * 100).toFixed(1)}%\n- 波动率分位: ${(Number(quant.volatilityPct || 0) * 100).toFixed(1)}%\n- 动量分位: ${(Number(quant.momentumPct || 0) * 100).toFixed(1)}%\n- 实际波动率: ${(volatility * 100).toFixed(2)}%\n- 24h涨跌幅: ${(momentum * 100).toFixed(2)}%\n\n机会解读\n- 该标的在当前筛选池中具备 ${item.opportunityLevel || "D"} 级机会。\n\n建议交易计划（参考）\n- 入场区间: ${this.formatNumber(entryLower)} ~ ${this.formatNumber(entryUpper)}\n- 止损位: ${this.formatNumber(stopLoss)}\n- 第一目标位: ${this.formatNumber(target1)}\n- 建议仓位: ${item.opportunityLevel === "A+" ? "20-30%" : item.opportunityLevel === "A" ? "15-25%" : item.opportunityLevel === "B" ? "10-15%" : "5-10%"}\n- 失效条件: ${invalid}\n\n多时间框架\n` +
            timeframePlans.map((plan) => `[${plan.label}] ${plan.bias}\n  入场: ${this.formatNumber(plan.entryLower)} ~ ${this.formatNumber(plan.entryUpper)}\n  止损: ${this.formatNumber(plan.stopLoss)}\n  第一目标: ${this.formatNumber(plan.target1)}\n  建议仓位: ${plan.position}\n  失效条件: ${plan.invalid}`).join("\n\n");
        this.elements.opportunityModal.classList.add("active");
    }

    buildTimeframePlans(item, momentum, volatility) {
        const bullish = momentum >= 0;
        const basePosition = item.opportunityLevel === "A+" ? 0.28 : item.opportunityLevel === "A" ? 0.22 : item.opportunityLevel === "B" ? 0.14 : 0.08;
        const frames = [
            { label: "15m", entryPullback: bullish ? 0.0018 : -0.0012, entryBreak: bullish ? 0.0014 : -0.0022, risk: bullish ? 0.0016 : 0.0018, targetFactor: 0.6, posFactor: 0.8 },
            { label: "1h", entryPullback: bullish ? 0.0045 : -0.0025, entryBreak: bullish ? 0.0025 : -0.004, risk: bullish ? 0.0038 : 0.0042, targetFactor: 1.2, posFactor: 1.0 },
            { label: "4h", entryPullback: bullish ? 0.009 : -0.0045, entryBreak: bullish ? 0.004 : -0.006, risk: bullish ? 0.007 : 0.008, targetFactor: 2.0, posFactor: 1.2 },
        ];
        return frames.map((frame) => {
            const entryLower = bullish ? item.last * (1 - frame.entryPullback) : item.last * (1 + frame.entryPullback);
            const entryUpper = bullish ? item.last * (1 + frame.entryBreak) : item.last * (1 + frame.entryBreak);
            const stopLoss = bullish ? Math.min(item.low * (1 - frame.risk), entryLower * (1 - frame.risk)) : Math.max(item.high * (1 + frame.risk), entryUpper * (1 + frame.risk));
            const targetStep = Math.max(0.003, volatility * frame.targetFactor);
            const target1 = bullish ? item.last * (1 + targetStep) : item.last * (1 - targetStep);
            const posPct = Math.max(0.04, Math.min(0.35, basePosition * frame.posFactor));
            return { label: frame.label, entryLower, entryUpper, stopLoss, target1, position: `${Math.round(posPct * 100)}%`, bias: bullish ? "顺势回踩/突破跟随" : "反弹承压/延续下探", invalid: bullish ? "跌破前低且成交量放大" : "突破前高且买盘持续放大" };
        });
    }

    hideOpportunityModal() {
        if (this.elements.opportunityModal) {
            this.elements.opportunityModal.classList.remove("active");
        }
    }

    closeOpportunityModal() {
        this.hideOpportunityModal();
    }

    closeSymbolAnalyzeModal() {
        this.hideSymbolAnalyzeModal();
    }

    async parseJsonResponse(response) {
        const text = await response.text();
        if (!text.trim()) return {};
        try {
            return JSON.parse(text);
        } catch (_e) {
            throw new Error(`接口返回非 JSON (${response.status}): ${text.slice(0, 160)}`);
        }
    }

    initSideNav() {
        // Navigation is now handled by href links in the HTML
    }

    async loadNews(symbol) {
        if (!this.elements.newsList) return;
        const sym = this.extractBaseSymbol(symbol || this.getActiveSymbol());
        if (this.elements.newsSymbolLabel) this.elements.newsSymbolLabel.textContent = sym;
        this.elements.newsList.textContent = `加载 ${sym} 新闻中...`;
        try {
            const response = await fetch(`/api/dashboard/news?symbol=${encodeURIComponent(sym)}&limit=20`);
            const data = await this.parseJsonResponse(response);
            if (!data.ok) throw new Error(data.message || "加载失败");
            this._renderNews(data.news || [], data.message || "");
        } catch (error) {
            this.elements.newsList.innerHTML = `<div class="news-error">加载失败: ${this.escapeHtml(error.message)}</div>`;
        }
    }

    _renderNews(list, msg) {
        if (!this.elements.newsList) return;
        if (!list.length) {
            this.elements.newsList.innerHTML = `<div class="news-empty">${this.escapeHtml(msg || "暂无要闻")}</div>`;
            return;
        }
        const sourceCountMap = {};
        list.forEach((n) => { const s = n.source || "unknown"; sourceCountMap[s] = (sourceCountMap[s] || 0) + 1; });
        const badges = Object.entries(sourceCountMap).map(([s, c]) => `<span class="news-src-badge${s === "web_search" ? " ws" : ""}">${this.escapeHtml(s === "web_search" ? "🔍 Web Search" : s)} (${c})</span>`).join("");
        let html = `<div class="news-source-bar">${badges}<span class="news-total">${list.length} 条</span></div>`;
        html += list.map((item) => {
            const title = (item.title || "").trim() || "无标题";
            const url = item.url || "#";
            const source = (item.source || "").trim() || "—";
            const body = (item.body || "").trim();
            const time = item.publishedAt ? new Date(item.publishedAt).toLocaleString("zh-CN", { dateStyle: "short", timeStyle: "short" }) : "";
            const bodyHtml = body ? `<span class="news-body">${this.escapeHtml(body.length > 120 ? `${body.slice(0, 120)}...` : body)}</span>` : "";
            return `<a class="news-item" href="${url}" target="_blank" rel="noopener"><span class="news-title">${this.escapeHtml(title)}</span>${bodyHtml}<span class="news-meta${source === "web_search" ? " ws" : ""}">${this.escapeHtml(source)}${time ? ` · ${time}` : ""}</span></a>`;
        }).join("");
        this.elements.newsList.innerHTML = html;
    }

    async loadNarrative(symbol) {
        if (!this.elements.narrativeContent) return;
        const sym = this.extractBaseSymbol(symbol || this.getActiveSymbol());
        if (this.elements.narrativeSymbolLabel) this.elements.narrativeSymbolLabel.textContent = sym;
        this.elements.narrativeContent.textContent = `加载 ${sym} 叙事中...`;
        try {
            const [fundResp, chanceResp, riskResp, fundsResp] = await Promise.all([
                fetch(`/api/dashboard/vs/token-fund?symbol=${encodeURIComponent(sym)}`),
                fetch(`/api/dashboard/vs/ai-messages?symbol=${encodeURIComponent(sym)}&msg_type=chance`),
                fetch(`/api/dashboard/vs/ai-messages?symbol=${encodeURIComponent(sym)}&msg_type=risk`),
                fetch(`/api/dashboard/vs/ai-messages?symbol=${encodeURIComponent(sym)}&msg_type=funds`),
            ]);
            const fundData = await this.parseJsonResponse(fundResp);
            const chanceData = await this.parseJsonResponse(chanceResp);
            const riskData = await this.parseJsonResponse(riskResp);
            const fundsData = await this.parseJsonResponse(fundsResp);
            this._renderNarrative(sym, fundData, chanceData, riskData, fundsData);
        } catch (error) {
            this.elements.narrativeContent.innerHTML = `<div class="narrative-error">加载失败: ${this.escapeHtml(error.message)}</div>`;
        }
    }

    _renderNarrative(symbol, fundData, chanceData, riskData, fundsData) {
        if (!this.elements.narrativeContent) return;
        const sentiment = (fundData.ok ? fundData.sentiment : null) || {};
        const msgTypeMap = { 1: "主力吸筹", 2: "突破信号", 3: "趋势启动", 4: "回调买入", 5: "放量突破", 6: "缩量回踩", 7: "底部信号", 8: "反转信号", 9: "主力派发", 10: "破位风险", 11: "见顶信号", 12: "超买风险", 13: "资金异动", 14: "主力入场", 15: "抛压预警", 16: "短线机会", 17: "趋势信号", 18: "量价配合", 19: "背离信号", 20: "突破回踩" };
        const signalGroups = [
            { type: "chance", label: "机会追踪", data: chanceData },
            { type: "risk", label: "风险追踪", data: riskData },
            { type: "funds", label: "资金异动", data: fundsData },
        ];
        const signals = [];
        signalGroups.forEach((group) => {
            if (!group.data.ok) return;
            (group.data.messages || []).forEach((msg) => {
                signals.push({ ...msg, _channel: group.type, _channelLabel: group.label });
            });
        });
        signals.sort((a, b) => Number(b.updateTime || 0) - Number(a.updateTime || 0));

        const narrativeTexts = this._collectNarrativeTexts(sentiment);
        if (!narrativeTexts.length && !signals.length && !Object.keys(sentiment).length) {
            const err = fundData.message || chanceData.message || "暂无叙事数据";
            this.elements.narrativeContent.innerHTML = `<div class="narrative-empty">${this.escapeHtml(err)}</div>`;
            return;
        }

        let html = "";
        if (Object.keys(sentiment).length) {
            html += `<div class="narrative-sentiment"><div class="narrative-sentiment-title">社媒情绪 · ${this.escapeHtml(symbol)}</div>`;
            html += this._renderNarrativeSentimentBars(sentiment);
            html += `</div>`;
        }
        if (narrativeTexts.length) {
            html += `<div class="narrative-group"><div class="narrative-group-title">市场叙事</div>`;
            html += narrativeTexts.map((item) => {
                const time = item.updateTime ? new Date(item.updateTime).toLocaleString("zh-CN", { dateStyle: "short", timeStyle: "short" }) : "";
                return `<div class="narrative-item"><span class="narrative-group-title ${item.cls}">${this.escapeHtml(item.label)}</span>${this.escapeHtml(item.text)}${time ? `<span class="narrative-item-meta">${time}</span>` : ""}</div>`;
            }).join("");
            html += `</div>`;
        }
        if (signals.length) {
            html += `<div class="narrative-group"><div class="narrative-group-title">AI 追踪信号</div>`;
            html += signals.slice(0, 8).map((msg) => {
                const t = msg.updateTime ? new Date(msg.updateTime).toLocaleString("zh-CN", { dateStyle: "short", timeStyle: "short" }) : "";
                const msgType = msg.chanceMessageType || msg.riskMessageType || msg.fundsMessageType || 0;
                const typeStr = msgTypeMap[msgType] || `信号#${msgType}`;
                const grade = msg.grade ? "⭐".repeat(Math.min(msg.grade, 5)) : "";
                const price = msg.price ? `$${this.formatNumber(Number(msg.price))}` : "";
                const change = msg.percentChange24h != null ? `${msg.percentChange24h >= 0 ? "+" : ""}${Number(msg.percentChange24h).toFixed(2)}%` : "";
                const changeCls = Number(msg.percentChange24h || 0) >= 0 ? "change-up" : "change-down";
                return `<div class="narrative-signal-item"><span class="narrative-signal-type ${msg._channel}">${this.escapeHtml(msg._channelLabel)}</span><strong>${this.escapeHtml(typeStr)}</strong> ${grade} ${price} <span class="${changeCls}">${change}</span>${t ? `<span class="narrative-item-meta">${t}</span>` : ""}</div>`;
            }).join("");
            html += `</div>`;
        }
        html += `<div class="onchain-desc">数据来源: ValueScan 社媒情绪 + AI 追踪</div>`;
        this.elements.narrativeContent.innerHTML = html;
    }

    _renderNarrativeSentimentBars(sentiment) {
        const bullish = sentiment.bullishRatio != null ? (sentiment.bullishRatio * 100).toFixed(1) : null;
        const neutral = sentiment.neutralRatio != null ? (sentiment.neutralRatio * 100).toFixed(1) : null;
        const bearish = sentiment.bearishRatio != null ? (sentiment.bearishRatio * 100).toFixed(1) : null;
        if (bullish == null) return "";
        return `<div class="vs-sentiment-bars">
            <div class="vs-sbar-row"><span class="vs-sbar-label">看多</span><div class="vs-sbar"><div class="vs-sbar-fill vs-sbar-bull" style="width:${bullish}%"></div></div><span class="vs-sbar-pct change-up">${bullish}%</span></div>
            <div class="vs-sbar-row"><span class="vs-sbar-label">中性</span><div class="vs-sbar"><div class="vs-sbar-fill vs-sbar-neutral" style="width:${neutral}%"></div></div><span class="vs-sbar-pct">${neutral}%</span></div>
            <div class="vs-sbar-row"><span class="vs-sbar-label">看空</span><div class="vs-sbar"><div class="vs-sbar-fill vs-sbar-bear" style="width:${bearish}%"></div></div><span class="vs-sbar-pct change-down">${bearish}%</span></div>
        </div>`;
    }

    _collectNarrativeTexts(sentiment) {
        const groups = [
            { label: "看多", cls: "narr-bull", items: sentiment.bullishContents || [] },
            { label: "中性", cls: "narr-neutral", items: sentiment.neutralContents || [] },
            { label: "看空", cls: "narr-bear", items: sentiment.bearishContents || [] },
        ];
        const out = [];
        groups.forEach((group) => {
            (group.items || []).slice(0, 2).forEach((item) => {
                const text = (item.chinese || item.english || item.content || "").trim();
                if (!text) return;
                out.push({ label: group.label, cls: group.cls, text, updateTime: item.updateTime });
            });
        });
        out.sort((a, b) => Number(b.updateTime || 0) - Number(a.updateTime || 0));
        return out.slice(0, 6);
    }
}

// ---------------------------------------------------------------------------
// Mixin composition: merge DashboardUtils + VsMixin into the prototype
// ---------------------------------------------------------------------------
if (typeof DashboardUtils !== "undefined") {
    Object.keys(DashboardUtils).forEach(key => {
        TradeDashboard.prototype[key] = DashboardUtils[key];
    });
}
if (typeof VsMixin !== "undefined") {
    Object.keys(VsMixin).forEach(key => {
        if (key === "VS_ELEMENT_IDS") return;
        TradeDashboard.prototype[key] = VsMixin[key];
    });
}
if (typeof DexMixin !== "undefined") {
    Object.keys(DexMixin).forEach(key => {
        if (key === "DEX_ELEMENT_IDS") return;
        TradeDashboard.prototype[key] = DexMixin[key];
    });
}

document.addEventListener("DOMContentLoaded", () => {
    new TradeDashboard().init();
});
