/**
 * Deep Analysis Page — unified coin analysis.
 *
 * Merges: StrategyPage (K-line, BOLL, MACD, LLM signal) + Dashboard (onchain, news, VS whale, VS indicators).
 * Depends on: dashboard-utils.js (DashboardUtils)
 */
class AnalysisPage {
    constructor() {
        const _el = (id) => document.getElementById(id);
        this.elements = {
            analysisSymbolInput: _el("analysisSymbolInput"),
            analysisKlineTypeSelect: _el("analysisKlineTypeSelect"),
            analysisModelSelect: _el("analysisModelSelect"),
            applySymbolBtn: _el("applySymbolBtn"),
            generateSignalBtn: _el("generateSignalBtn"),
            signalRefreshToggle: _el("signalRefreshToggle"),
            signalRefreshCountdown: _el("signalRefreshCountdown"),
            autoRefreshToggle: _el("autoRefreshToggle"),
            analysisBaseInfo: _el("analysisBaseInfo"),
            analysisPairLabel: _el("analysisPairLabel"),
            analysisKlineChart: _el("analysisKlineChart"),
            analysisKlineChartHint: _el("analysisKlineChartHint"),
            analysisKlineMetrics: _el("analysisKlineMetrics"),
            analysisKlineVerdict: _el("analysisKlineVerdict"),
            analysisSignalSymbolLabel: _el("analysisSignalSymbolLabel"),
            analysisSignalBadge: _el("analysisSignalBadge"),
            analysisSignalContent: _el("analysisSignalContent"),
            analysisModelTag: _el("analysisModelTag"),
            // Onchain & News
            onchainContent: _el("onchainContent"),
            refreshOnchainBtn: _el("refreshOnchainBtn"),
            newsList: _el("newsList"),
            refreshNewsBtn: _el("refreshNewsBtn"),
            // VS Whale & Indicators
            vsWhaleOnchainContent: _el("vsWhaleOnchainContent"),
            vsWhaleSymbolLabel: _el("vsWhaleSymbolLabel"),
            refreshVsWhaleBtn: _el("refreshVsWhaleBtn"),
            vsIndicatorsContent: _el("vsIndicatorsContent"),
            vsIndicatorSymbolLabel: _el("vsIndicatorSymbolLabel"),
            refreshVsIndicatorsBtn: _el("refreshVsIndicatorsBtn"),
            // VS Detail Modal
            vsDetailModal: _el("vsDetailModal"),
            vsDetailModalTitle: _el("vsDetailModalTitle"),
            vsDetailModalBody: _el("vsDetailModalBody"),
            closeVsDetailModal: _el("closeVsDetailModal"),
            // DEX Overview
            dexSymbolLabel: _el("dexSymbolLabel"),
            dexChainSelect: _el("dexChainSelect"),
            refreshDexBtn: _el("refreshDexBtn"),
            dexOverviewContent: _el("dexOverviewContent"),
        };

        this.state = { baseSymbol: "BTC", pairSymbol: "BTC-USDT", quote: "USDT", model: "deepseek/deepseek-v4-pro", klineType: "1hour" };

        // Chart stack
        this.klineStack = null;
        this._signalRefreshTimer = null;
        this._signalCountdownTimer = null;
        this._signalCountdownSec = 0;
        this._signalPollTimer = null;
        this._marketRefreshTimer = null;
    }

    toBeijingTsSec(tsSec) {
        const t = Number(tsSec || 0);
        if (!Number.isFinite(t) || t <= 0) return 0;
        // LightweightCharts uses UTC-based unix seconds; shift to UTC+8 for Beijing display.
        return t + 8 * 3600;
    }

    init() {
        this.hydrateFromQuery();
        this.bindEvents();
        this.initKlineChart();
        if (this.elements.autoRefreshToggle) this.elements.autoRefreshToggle.checked = true;
        this.loadMarketData();
        this.startAutoRefresh();
        this.loadSignalAnalysis();
        this.loadCoinData();
    }

    hydrateFromQuery() {
        const params = new URLSearchParams(window.location.search || "");
        this.setSymbolState(params.get("symbol") || "BTC");
        this.state.model = params.get("model") || this.state.model;
        this.state.klineType = params.get("type") || this.state.klineType;
        this.elements.analysisSymbolInput.value = this.state.baseSymbol;
        this.elements.analysisModelSelect.value = this.state.model;
        this.elements.analysisKlineTypeSelect.value = this.state.klineType;
        this.updateStaticLabels();
    }

    bindEvents() {
        this.elements.applySymbolBtn?.addEventListener("click", () => this.applySymbol());
        this.elements.generateSignalBtn?.addEventListener("click", () => this.loadSignalAnalysis());
        this.elements.signalRefreshToggle?.addEventListener("change", () => this.handleSignalRefreshToggle());
        this.elements.autoRefreshToggle?.addEventListener("change", () => this.handleAutoRefreshToggle());
        this.elements.analysisModelSelect?.addEventListener("change", () => { this.state.model = this.elements.analysisModelSelect.value; this.updateStaticLabels(); this.updateUrl(); });
        this.elements.analysisKlineTypeSelect?.addEventListener("change", () => { this.state.klineType = this.elements.analysisKlineTypeSelect.value; this.updateUrl(); this.loadKlineAnalysis(); });
        this.elements.analysisSymbolInput?.addEventListener("keydown", (e) => { if (e.key === "Enter") this.applySymbol(); });
        window.addEventListener("resize", () => this.resizeKlineChart());
        // Onchain & News
        this.elements.refreshOnchainBtn?.addEventListener("click", () => this.loadOnchain());
        this.elements.refreshNewsBtn?.addEventListener("click", () => this.loadNews());
        // VS Whale & Indicators
        this.elements.refreshVsWhaleBtn?.addEventListener("click", () => this.loadVsWhaleOnchain());
        this.elements.refreshVsIndicatorsBtn?.addEventListener("click", () => this.loadVsPriceIndicators());
        // VS Modal
        if (this.elements.closeVsDetailModal) {
            this.elements.closeVsDetailModal.addEventListener("click", () => this.closeVsDetailModal());
            this.elements.vsDetailModal?.addEventListener("click", (e) => { if (e.target === this.elements.vsDetailModal) this.closeVsDetailModal(); });
        }
        // DEX Overview
        this.elements.refreshDexBtn?.addEventListener("click", () => this.loadDexOverview(this.state.baseSymbol));
        this.elements.dexChainSelect?.addEventListener("change", () => this.loadDexOverview(this.state.baseSymbol));
    }

    applySymbol() {
        this.setSymbolState(this.elements.analysisSymbolInput.value || this.state.baseSymbol);
        this.updateStaticLabels();
        this.updateUrl();
        this.loadMarketData();
        this.loadCoinData();
        if (this.elements.autoRefreshToggle?.checked) { this.stopAutoRefresh(); this.startAutoRefresh(); }
    }

    loadCoinData() {
        const sym = this.state.baseSymbol;
        this.loadOnchain();
        this.loadNews();
        this.loadVsWhaleOnchain();
        this.loadVsPriceIndicators();
        this.loadDexOverview(sym);
    }

    setSymbolState(rawSymbol) {
        const raw = String(rawSymbol || "BTC").trim().toUpperCase().replace(/\s+/g, "").replace(/\//g, "-").replace(/_/g, "-");
        if (/^[A-Z0-9]+-[A-Z0-9]+$/.test(raw)) { this.state.baseSymbol = raw.split("-")[0] || "BTC"; }
        else { this.state.baseSymbol = raw.replace(/-.*/, "") || "BTC"; }
        this.state.quote = "USDT";
        this.state.pairSymbol = `${this.state.baseSymbol}-USDT`;
        if (this.elements.analysisSymbolInput) this.elements.analysisSymbolInput.value = this.state.baseSymbol;
    }

    /** Compatibility shim for DexMixin — returns the active base symbol */
    getActiveSymbol() {
        return this.state.baseSymbol || "BTC";
    }

    updateStaticLabels() {
        if (this.elements.analysisPairLabel) this.elements.analysisPairLabel.textContent = this.state.pairSymbol;
        if (this.elements.analysisSignalSymbolLabel) this.elements.analysisSignalSymbolLabel.textContent = this.state.baseSymbol;
        if (this.elements.analysisModelTag) this.elements.analysisModelTag.textContent = this.formatModelName(this.state.model);
        if (this.elements.vsWhaleSymbolLabel) this.elements.vsWhaleSymbolLabel.textContent = this.state.baseSymbol;
        if (this.elements.vsIndicatorSymbolLabel) this.elements.vsIndicatorSymbolLabel.textContent = this.state.baseSymbol;
        if (this.elements.dexSymbolLabel) this.elements.dexSymbolLabel.textContent = this.state.baseSymbol;
    }

    updateUrl() {
        const params = new URLSearchParams();
        params.set("symbol", this.state.baseSymbol);
        params.set("model", this.state.model);
        params.set("type", this.state.klineType);
        window.history.replaceState({}, "", `/analysis?${params.toString()}`);
    }

    // ── Auto refresh ─────────────────────────────────────────
    handleAutoRefreshToggle() { this.elements.autoRefreshToggle?.checked ? this.startAutoRefresh() : this.stopAutoRefresh(); }
    startAutoRefresh() { this.stopAutoRefresh(); this._marketRefreshTimer = setInterval(() => this.loadMarketData(), 3000); }
    stopAutoRefresh() { if (this._marketRefreshTimer) { clearInterval(this._marketRefreshTimer); this._marketRefreshTimer = null; } }

    handleSignalRefreshToggle() { this.elements.signalRefreshToggle?.checked ? this.startSignalRefresh() : this.stopSignalRefresh(); }
    startSignalRefresh() {
        this.stopSignalRefresh();
        const INTERVAL = 300;
        this._signalCountdownSec = INTERVAL;
        this.updateSignalCountdown();
        this._signalCountdownTimer = setInterval(() => {
            this._signalCountdownSec--;
            if (this._signalCountdownSec <= 0) { this._signalCountdownSec = INTERVAL; this.loadSignalAnalysis(); }
            this.updateSignalCountdown();
        }, 1000);
    }
    stopSignalRefresh() {
        if (this._signalRefreshTimer) { clearInterval(this._signalRefreshTimer); this._signalRefreshTimer = null; }
        if (this._signalCountdownTimer) { clearInterval(this._signalCountdownTimer); this._signalCountdownTimer = null; }
        this._signalCountdownSec = 0;
        if (this.elements.signalRefreshCountdown) this.elements.signalRefreshCountdown.textContent = "";
    }
    updateSignalCountdown() {
        if (!this.elements.signalRefreshCountdown) return;
        const m = Math.floor(this._signalCountdownSec / 60), s = this._signalCountdownSec % 60;
        this.elements.signalRefreshCountdown.textContent = `${m}:${String(s).padStart(2, "0")}`;
    }

    // ── Market Data ──────────────────────────────────────────
    async loadMarketData() {
        this.renderBaseInfoLoading();
        await Promise.all([this.loadBasicInfo(), this.loadKlineAnalysis()]);
    }

    renderBaseInfoLoading() {
        if (!this.elements.analysisBaseInfo) return;
        this.elements.analysisBaseInfo.innerHTML = `<article class="stats-card"><h3>当前币种</h3><p>${this.escapeHtml(this.state.baseSymbol)}</p></article><article class="stats-card"><h3>最新价格</h3><p>加载中...</p></article><article class="stats-card"><h3>24h 涨跌</h3><p>加载中...</p></article><article class="stats-card"><h3>24h 高低</h3><p>加载中...</p></article><article class="stats-card"><h3>24h 成交额</h3><p>加载中...</p></article><article class="stats-card"><h3>交易对</h3><p>${this.escapeHtml(this.state.pairSymbol)}</p></article>`;
    }

    async loadBasicInfo() {
        try {
            const response = await fetch(`/api/market/tickers?quote=${encodeURIComponent(this.state.quote)}&search=${encodeURIComponent(this.state.baseSymbol)}&limit=50`);
            const data = await this.parseJsonResponse(response);
            if (!response.ok || !data.ok) throw new Error(data.message || "基础信息加载失败");
            const tickers = Array.isArray(data.tickers) ? data.tickers : [];
            const matched = tickers.find((item) => String(item.symbol || "").toUpperCase() === this.state.pairSymbol) || tickers.find((item) => String(item.symbol || "").toUpperCase().startsWith(`${this.state.baseSymbol}-`)) || null;
            this.renderBaseInfo(matched);
        } catch (error) { this.renderBaseInfo(null, error.message); }
    }

    renderBaseInfo(item, errorMessage = "") {
        if (!this.elements.analysisBaseInfo) return;
        if (!item) {
            this.elements.analysisBaseInfo.innerHTML = `<article class="stats-card"><h3>当前币种</h3><p>${this.escapeHtml(this.state.baseSymbol)}</p></article><article class="stats-card"><h3>最新价格</h3><p>-</p></article><article class="stats-card"><h3>24h 涨跌</h3><p>-</p></article><article class="stats-card"><h3>24h 高低</h3><p>-</p></article><article class="stats-card"><h3>24h 成交额</h3><p>-</p></article><article class="stats-card"><h3>状态</h3><p>${this.escapeHtml(errorMessage || "未获取到")}</p></article>`;
            return;
        }
        const changeRate = Number(item.changeRate || 0) * 100;
        const changeClass = changeRate >= 0 ? "change-up" : "change-down";
        this.elements.analysisBaseInfo.innerHTML = `<article class="stats-card"><h3>当前币种</h3><p>${this.escapeHtml(this.state.baseSymbol)}</p></article><article class="stats-card"><h3>最新价格</h3><p>${this.formatNumber(item.last)}</p></article><article class="stats-card"><h3>24h 涨跌</h3><p class="${changeClass}">${changeRate >= 0 ? "+" : ""}${changeRate.toFixed(2)}%</p></article><article class="stats-card"><h3>24h 高低</h3><p>${this.formatNumber(item.high)} / ${this.formatNumber(item.low)}</p></article><article class="stats-card"><h3>24h 成交额</h3><p>${this.formatNumber(item.volValue)}</p></article><article class="stats-card"><h3>交易对</h3><p>${this.escapeHtml(item.symbol || this.state.pairSymbol)}</p></article>`;
    }

    // ── K-line Chart ─────────────────────────────────────────
    initKlineChart() {
        const saved = typeof KlineIndicatorControls !== "undefined"
            ? KlineIndicatorControls.loadSaved(KLINE_DEFAULT_INDICATORS || {})
            : {};
        this.klineStack = new KlineChartStack({
            mainEl: this.elements.analysisKlineChart,
            legendEl: document.getElementById("analysisKlineLegend"),
            hintEl: this.elements.analysisKlineChartHint,
            toTime: (ts) => this.toBeijingTsSec(ts),
            indicators: saved,
        });
        this.klineStack.init();
        const toolbar = document.querySelector(".strategy-kline-section .kline-indicator-toolbar");
        if (toolbar && typeof KlineIndicatorControls !== "undefined") {
            this.klineIndicatorControls = new KlineIndicatorControls(toolbar, this.klineStack);
            this.klineIndicatorControls.bind();
        }
    }

    resizeKlineChart() {
        this.klineStack?.resize();
    }

    renderKlineChart(candles) {
        this.klineStack?.render(candles);
    }

    async loadKlineAnalysis() {
        if (this.elements.analysisKlineVerdict) this.elements.analysisKlineVerdict.textContent = `正在分析 ${this.state.pairSymbol} K 线...`;
        if (this.elements.analysisKlineChartHint) this.elements.analysisKlineChartHint.textContent = "加载 K 线数据中...";
        try {
            const response = await fetch(`/api/market/kline-analysis?symbol=${encodeURIComponent(this.state.pairSymbol)}&type=${encodeURIComponent(this.state.klineType)}&limit=120&realtime=1`);
            const data = await this.parseJsonResponse(response);
            if (!response.ok || !data.ok) throw new Error(data.message || "K 线分析失败");
            this.renderKline(data);
        } catch (error) {
            this.renderKlineChart([]);
            if (this.elements.analysisKlineMetrics) this.elements.analysisKlineMetrics.innerHTML = `<div class="strategy-empty">${this.escapeHtml(error.message)}</div>`;
            if (this.elements.analysisKlineVerdict) this.elements.analysisKlineVerdict.textContent = `K 线分析失败: ${error.message}`;
        }
    }

    renderKline(payload) {
        const metrics = payload.metrics || {}, verdict = payload.verdict || {};
        if (this.elements.analysisPairLabel) this.elements.analysisPairLabel.textContent = payload.symbol || this.state.pairSymbol;
        this.renderKlineChart(payload.candles || []);
        if (this.elements.analysisKlineMetrics) {
            this.elements.analysisKlineMetrics.innerHTML = [
                this.renderMetricCard("趋势", payload.trend || "-"),
                this.renderMetricCard("RSI", metrics.rsi != null ? Number(metrics.rsi).toFixed(1) : "-"),
                this.renderMetricCard("区间位置", metrics.rangePositionPct != null ? `${Number(metrics.rangePositionPct).toFixed(0)}%` : "-"),
                this.renderMetricCard("布林宽度", metrics.bbWidth != null ? `${Number(metrics.bbWidth).toFixed(1)}%` : "-"),
                this.renderMetricCard("支撑", this.formatNumber(metrics.support20)),
                this.renderMetricCard("阻力", this.formatNumber(metrics.resistance20)),
            ].join("");
        }
        if (this.elements.analysisKlineVerdict) {
            const reasons = Array.isArray(verdict.reasons) ? verdict.reasons.slice(0, 6) : [];
            const score = Number(verdict.score || 0), confidence = Number(verdict.confidence || 0);
            const actionLabel = verdict.actionLabel || "观望";
            const actionClass = /买|多|BUY/i.test(actionLabel) ? "kv-action-buy" : /卖|空|SELL/i.test(actionLabel) ? "kv-action-sell" : "kv-action-neutral";
            let html = `<div class="kv-card"><div class="kv-header"><span class="kv-action ${actionClass}">${this.escapeHtml(actionLabel)}</span><div class="kv-stats"><span class="kv-stat"><span class="kv-stat-label">置信度</span><span class="kv-stat-value">${confidence.toFixed(1)}%</span></span><span class="kv-stat"><span class="kv-stat-label">评分</span><span class="kv-stat-value">${score > 0 ? "+" : ""}${score.toFixed(1)}</span></span><span class="kv-stat"><span class="kv-stat-label">周期</span><span class="kv-stat-value">${this.escapeHtml(payload.type || this.state.klineType)}</span></span><span class="kv-stat"><span class="kv-stat-label">趋势</span><span class="kv-stat-value">${this.escapeHtml(payload.trend || "-")}</span></span></div></div>`;
            const barColor = confidence >= 70 ? "#3ecf8e" : confidence >= 40 ? "#f4b942" : "#ff6b6b";
            html += `<div class="kv-bar-wrap"><div class="kv-bar" style="width:${Math.min(confidence, 100)}%;background:${barColor}"></div></div>`;
            if (reasons.length) { html += `<div class="kv-reasons"><div class="kv-reasons-title">分析依据</div><ul>`; reasons.forEach((r, i) => { html += `<li><span class="kv-reason-idx">${i + 1}</span>${this.escapeHtml(r)}</li>`; }); html += `</ul></div>`; }
            html += `</div>`;
            this.elements.analysisKlineVerdict.innerHTML = html;
        }
    }

    // ── LLM Signal Analysis ──────────────────────────────────
    async loadSignalAnalysis() {
        if (!this.elements.analysisSignalContent) return;
        this.klineStack?.clearTradePlan();
        if (this._signalPollTimer) { clearInterval(this._signalPollTimer); this._signalPollTimer = null; }
        if (this.elements.analysisSignalBadge) { this.elements.analysisSignalBadge.className = "signal-badge signal-neutral"; this.elements.analysisSignalBadge.textContent = "分析中"; }
        this.elements.analysisSignalContent.innerHTML = `<div class="signal-loading">正在提交 ${this.state.baseSymbol} LLM 信号分析任务...</div>`;
        const stopPoll = () => { if (this._signalPollTimer) { clearInterval(this._signalPollTimer); this._signalPollTimer = null; } this._signalPollN = 0; };
        try {
            const submitResp = await fetch(`/api/dashboard/llm-signal-analysis?symbol=${encodeURIComponent(this.state.baseSymbol)}&model=${encodeURIComponent(this.state.model)}`);
            const submitData = await this.parseJsonResponse(submitResp);
            if (!submitResp.ok || !submitData.ok) throw new Error(submitData.message || "提交任务失败");
            const taskId = submitData.taskId;
            this._signalPollN = 0;
            const maxPolls = 200; /* 200 * 3s ≈ 10 min, above typical llm_signal_timeout + data fetch */
            this.elements.analysisSignalContent.innerHTML = `<div class="signal-loading">LLM 信号分析进行中，请稍候...</div>`;
            this._signalPollTimer = setInterval(async () => {
                try {
                    this._signalPollN = (this._signalPollN || 0) + 1;
                    if (this._signalPollN > maxPolls) {
                        stopPoll();
                        this.elements.analysisSignalContent.innerHTML = `<div class="signal-error">分析超时，请重试。若问题持续，请检查服务端与模型网关。</div>`;
                        if (this.elements.analysisSignalBadge) { this.elements.analysisSignalBadge.className = "signal-badge signal-neutral"; this.elements.analysisSignalBadge.textContent = "未就绪"; }
                        return;
                    }
                    if (this._signalPollN % 5 === 0 && this.elements.analysisSignalContent) {
                        const sec = this._signalPollN * 3;
                        this.elements.analysisSignalContent.innerHTML = `<div class="signal-loading">LLM 信号分析进行中（已约 ${sec}s）…</div>`;
                    }
                    const pollResp = await fetch(`/api/dashboard/llm-signal-analysis/poll?taskId=${encodeURIComponent(taskId)}`);
                    const pollData = await this.parseJsonResponse(pollResp);
                    if (!pollResp.ok || pollData.ok === false) {
                        stopPoll();
                        this.elements.analysisSignalContent.innerHTML = `<div class="signal-error">分析轮询失败: ${this.escapeHtml(pollData.message || pollResp.statusText || "未知")}</div>`;
                        if (this.elements.analysisSignalBadge) { this.elements.analysisSignalBadge.className = "signal-badge signal-neutral"; this.elements.analysisSignalBadge.textContent = "未就绪"; }
                        return;
                    }
                    if (pollData.status === "done") { stopPoll(); this.renderSignalBlock(pollData.data); }
                    else if (pollData.status === "failed") { stopPoll(); this.elements.analysisSignalContent.innerHTML = `<div class="signal-error">分析失败: ${this.escapeHtml(pollData.message || "未知错误")}</div>`; if (this.elements.analysisSignalBadge) { this.elements.analysisSignalBadge.className = "signal-badge signal-neutral"; this.elements.analysisSignalBadge.textContent = "未就绪"; } }
                } catch (pollErr) { stopPoll(); this.elements.analysisSignalContent.innerHTML = `<div class="signal-error">轮询失败: ${this.escapeHtml(pollErr.message)}</div>`; if (this.elements.analysisSignalBadge) { this.elements.analysisSignalBadge.className = "signal-badge signal-neutral"; this.elements.analysisSignalBadge.textContent = "未就绪"; } }
            }, 3000);
        } catch (error) { this.elements.analysisSignalContent.innerHTML = `<div class="signal-error">LLM 信号分析失败: ${this.escapeHtml(error.message)}</div>`; }
    }

    renderSignalBlock(data) {
        if (!data || !this.elements.analysisSignalContent) return;
        const signal = data.signal || "NEUTRAL", label = data.signalLabel || data.label || "观望";
        const confidence = Number(data.confidence || 0), score = Number(data.score || 0);
        const reasons = Array.isArray(data.reasons) ? data.reasons : [];
        const summary = data.summary || "", market = data.market || {}, kline = data.kline || {};
        const analysis = data.analysis || {}, factors = data.factors || {};
        const risks = Array.isArray(data.risks) ? data.risks : [];
        const scenarios = Array.isArray(data.scenarios) ? data.scenarios : [];
        const dataQuality = data.dataQuality || {}, engineMeta = data.engineMeta || {}, onchainMetrics = data.onchainMetrics || {};
        const vs = data.valuescan || {};

        const badgeClassMap = { BUY: "signal-buy", WEAK_BUY: "signal-weak-buy", SELL: "signal-sell", WEAK_SELL: "signal-weak-sell", NEUTRAL: "signal-neutral" };
        if (this.elements.analysisSignalBadge) { this.elements.analysisSignalBadge.className = `signal-badge ${badgeClassMap[signal] || "signal-neutral"}`; this.elements.analysisSignalBadge.textContent = label; }
        if (this.elements.analysisModelTag) this.elements.analysisModelTag.textContent = this.formatModelName(engineMeta.model || this.state.model);

        const last = Number(market.last || 0), changeRate = Number(market.changeRate || 0);
        const changeClass = changeRate >= 0 ? "change-up" : "change-down";
        const signedRate = `${changeRate >= 0 ? "+" : ""}${(changeRate * 100).toFixed(2)}%`;

        let klineSummary = "";
        Object.entries(kline).forEach(([key, value]) => {
            const trendMap = { bullish: "多头趋势", bearish: "空头趋势", weak_bullish: "短线偏多", weak_bearish: "短线偏空", neutral: "中性" };
            const tl = key === "1hour" ? "1h" : key === "4hour" ? "4h" : key;
            const cls = value.trend === "bullish" || value.trend === "weak_bullish" ? "kline-bull" : value.trend === "bearish" || value.trend === "weak_bearish" ? "kline-bear" : "kline-neutral";
            klineSummary += `<span class="signal-kline-tag ${cls}">${tl}: ${trendMap[value.trend] || value.trend}</span> `;
        });

        let html = `<div class="signal-header-row"><div class="signal-price"><span class="signal-price-val">${this.formatNumber(last)}</span> <span class="signal-price-change ${changeClass}">${signedRate}</span></div><div class="signal-confidence">置信度 <strong>${confidence.toFixed(1)}%</strong> · 综合得分 <strong>${score > 0 ? "+" : ""}${score.toFixed(0)}</strong></div></div>`;
        if (klineSummary) html += `<div class="signal-kline-row">${klineSummary}</div>`;
        if (summary) html += `<div class="signal-summary-card"><h4>核心结论</h4><p>${this.escapeHtml(summary)}</p></div>`;
        html += this.renderSignalLogicFlow({ data, signal, label, confidence, score });

        html += `<div class="signal-meta-row"><span>市场状态: ${this.escapeHtml(this.toChineseDisplay("marketState", analysis.marketState || "uncertain"))}</span><span>执行准备度: ${this.escapeHtml(this.toChineseDisplay("executionReadiness", analysis.executionReadiness || "wait"))}</span><span>模型: ${this.escapeHtml(this.formatModelName(engineMeta.model || this.state.model))}</span>`;
        if ((onchainMetrics.fearGreed || {}).value != null) html += `<span>市场情绪·恐贪: ${onchainMetrics.fearGreed.value}</span>`;
        html += `</div>`;

        html += this._buildVsInsightsHtml(data.valuescanInsights, vs, last);
        html += this._buildFiveSignalHtml(data);
        html += this._buildStrategyBacktestsHtml(data.strategyBacktests);

        if (reasons.length) { html += `<div class="signal-reasons"><h4>分析依据</h4><ul>`; reasons.slice(0, 12).forEach(r => { const isPos = /偏多|多头|涨|乐观|反弹|流入|正面|买|机会|支撑|看多/.test(r); const isNeg = /偏空|空头|跌|悲观|回调|流出|负面|卖|风险|压力|看空/.test(r); html += `<li class="${isPos ? "reason-positive" : isNeg ? "reason-negative" : "reason-neutral"}">${this.escapeHtml(r)}</li>`; }); html += `</ul></div>`; }

        if (data.tradePlan && Object.keys(data.tradePlan).length) {
            const plan = data.tradePlan;
            html += `<div class="signal-trade-plan"><h4>交易计划</h4><div class="signal-grid signal-grid-2">`;
            html += this.renderMetricCard("支撑位", this.formatNumber(plan.support)) + this.renderMetricCard("阻力位", this.formatNumber(plan.resistance)) + this.renderMetricCard("入场区间", `${this.formatNumber(plan.entryLow)} ~ ${this.formatNumber(plan.entryHigh)}`) + this.renderMetricCard("止损位", this.formatNumber(plan.stop)) + this.renderMetricCard("目标一", this.formatNumber(plan.target1)) + this.renderMetricCard("目标二", this.formatNumber(plan.target2));
            html += `</div></div>`;
        }

        // Strategy perspective
        const consensus = analysis.consensus || {}, execution = analysis.execution || {}, levels = analysis.keyLevels || {}, catalysts = analysis.catalysts || [];
        html += `<div class="signal-structured-block"><h4>策略视角</h4><div class="signal-grid signal-grid-3">`;
        html += this.renderMetricCard("方向偏置", this.toChineseDisplay("bias", analysis.bias || "neutral")) + this.renderMetricCard("市场状态", this.toChineseDisplay("marketState", analysis.marketState || "uncertain")) + this.renderMetricCard("分析周期", this.toChineseDisplay("horizon", analysis.horizon || "intraday")) + this.renderMetricCard("执行准备度", this.toChineseDisplay("executionReadiness", analysis.executionReadiness || "wait")) + this.renderMetricCard("一致性分数", consensus.agreementScore != null ? `${Number(consensus.agreementScore * 100).toFixed(0)}%` : "-") + this.renderMetricCard("一致性强度", this.toChineseDisplay("strength", consensus.strength || "weak")) + this.renderMetricCard("失效位", this.formatNumber(levels.invalidation)) + this.renderMetricCard("盈亏比1", execution.riskReward1 != null ? String(execution.riskReward1) : "-") + this.renderMetricCard("盈亏比2", execution.riskReward2 != null ? String(execution.riskReward2) : "-");
        html += `</div>`;
        if ((consensus.conflicts || []).length) html += `<div class="signal-inline-list"><strong>冲突点：</strong>${consensus.conflicts.map(i => `<span class="signal-chip signal-chip-warning">${this.escapeHtml(i)}</span>`).join("")}</div>`;
        if (execution.action) html += `<div class="signal-inline-note"><strong>执行建议：</strong>${this.escapeHtml(execution.action)}</div>`;
        if (catalysts.length) html += `<div class="signal-inline-list"><strong>催化条件：</strong>${catalysts.map(i => `<span class="signal-chip signal-chip-positive">${this.escapeHtml(i)}</span>`).join("")}</div>`;
        html += `</div>`;

        // Factors
        const consensusHl = [
            ...((analysis.consensus || {}).conflicts || []),
            ...((factors.news || {}).highlights || []).map((h) => `新闻: ${h}`),
        ];
        const consensusFactor = {
            direction: (analysis.consensus || {}).direction || analysis.bias || "neutral",
            score: ((analysis.consensus || {}).agreementScore || 0) * 100,
            confidence: 0.5,
            highlights: consensusHl,
        };
        const factorEntries = [
            ["技术面", factors.technical, "K线/行情/衍生品/盘口/回测/量化价量（与 LLM 信号分析上下文一致）"],
            ["筹码/资金（ValueScan）", factors.onchain, ""],
            ["盘面/资金情绪", factors.positioning, ""],
            ["共识（含新闻）", consensusFactor, ""],
        ].filter(([, b]) => b && (((b.highlights || []).length) || Number(b.score || 0) !== 0));
        if (factorEntries.length) {
            html += `<div class="signal-structured-block"><h4>多维因子拆解</h4><div class="signal-factor-grid">`;
            factorEntries.forEach(([title, block, sub]) => {
                const maxHl = title === "技术面" ? 8 : 3;
                const hl = (block.highlights || []).slice(0, maxHl).map(i => `<li>${this.escapeHtml(i)}</li>`).join("");
                html += `<div class="signal-factor-card"><div class="signal-factor-head"><span>${title}</span><span>${this.toChineseDisplay("direction", block.direction || "neutral")} · ${Number(block.score || 0).toFixed(1)}</span></div>`;
                if (sub) html += `<div class="signal-factor-sub">${this.escapeHtml(sub)}</div>`;
                html += `<div class="signal-factor-sub">置信度 ${(Number(block.confidence || 0) * 100).toFixed(0)}%</div>${hl ? `<ul>${hl}</ul>` : ""}</div>`;
            });
            html += `</div></div>`;
        }

        // Risks
        if (risks.length) { html += `<div class="signal-structured-block"><h4>主要风险</h4><div class="signal-list-grid">`; risks.slice(0, 4).forEach(r => { html += `<div class="signal-info-card"><div class="signal-info-title">${this.escapeHtml(r.type || "风险")}</div><div class="signal-info-meta">级别: ${this.toChineseDisplay("severity", r.severity || "medium")}</div>${r.evidence ? `<p>${this.escapeHtml(r.evidence)}</p>` : ""}${r.trigger ? `<p><strong>触发：</strong>${this.escapeHtml(r.trigger)}</p>` : ""}${r.mitigation ? `<p><strong>应对：</strong>${this.escapeHtml(r.mitigation)}</p>` : ""}</div>`; }); html += `</div></div>`; }

        // Scenarios
        if (scenarios.length) { html += `<div class="signal-structured-block"><h4>情景推演</h4><div class="signal-list-grid">`; scenarios.slice(0, 3).forEach(i => { const tg = (i.target || []).map(v => this.formatNumber(v)).filter(Boolean).join(" / "); html += `<div class="signal-info-card"><div class="signal-info-title">${this.toChineseDisplay("scenario", i.name || "base")} · ${(Number(i.probability || 0) * 100).toFixed(0)}%</div>${i.trigger ? `<p><strong>触发：</strong>${this.escapeHtml(i.trigger)}</p>` : ""}${i.action ? `<p><strong>动作：</strong>${this.escapeHtml(i.action)}</p>` : ""}${tg ? `<p><strong>目标：</strong>${this.escapeHtml(tg)}</p>` : ""}</div>`; }); html += `</div></div>`; }

        // Data quality
        if (dataQuality && Object.keys(dataQuality).length) { html += `<div class="signal-structured-block"><h4>数据质量</h4><div class="signal-grid signal-grid-3">`; html += this.renderMetricCard("覆盖度", dataQuality.coverageScore != null ? `${Number(dataQuality.coverageScore * 100).toFixed(0)}%` : "-"); Object.entries(dataQuality.sourceStatus || {}).forEach(([n, v]) => { html += this.renderMetricCard(n, v); }); html += `</div>`; if ((dataQuality.limitations || []).length) html += `<div class="signal-inline-note"><strong>局限：</strong>${dataQuality.limitations.map(i => this.escapeHtml(i)).join("；")}</div>`; html += `</div>`; }

        this.elements.analysisSignalContent.innerHTML = html;
        if (data.tradePlan && Object.keys(data.tradePlan).length > 0) {
            this.klineStack?.setTradePlan(data.tradePlan);
        } else {
            this.klineStack?.clearTradePlan();
        }
    }

    _buildStrategyBacktestsHtml(bundle) {
        if (!bundle || !bundle.available) return "";
        const rows = (bundle.strategies || []).filter(s => s.ok).sort(
            (a, b) => Number(b.totalReturnPct || 0) - Number(a.totalReturnPct || 0)
        );
        if (!rows.length) return "";
        const meta = `${bundle.klineType || "1h"} · ${bundle.totalCandles || 0} 根 · ${bundle.successCount || 0}/${bundle.totalCount || 0} 策略`;
        let html = `<div class="signal-structured-block"><h4>策略回测矩阵（辩论前）</h4><div class="signal-inline-note">${this.escapeHtml(meta)} · 样本内历史，非未来收益保证</div><div class="signal-list-grid">`;
        rows.slice(0, 10).forEach(s => {
            const ret = Number(s.totalReturnPct || 0);
            const retCls = ret >= 0 ? "change-up" : "change-down";
            html += `<div class="signal-info-card"><div class="signal-info-title">${this.escapeHtml(s.displayName || s.name)}</div>`;
            html += `<div class="signal-info-meta">收益 <span class="${retCls}">${ret >= 0 ? "+" : ""}${ret.toFixed(2)}%</span> · 胜率 ${Number(s.winRate || 0).toFixed(1)}% · ${s.totalTrades || 0} 笔 · 回撤 -${Number(s.maxDrawdownPct || 0).toFixed(2)}% · 夏普 ${Number(s.sharpeRatio || 0).toFixed(2)}</div></div>`;
        });
        if (rows.length > 10) html += `<div class="signal-inline-note">另有 ${rows.length - 10} 个策略已注入 LLM 上下文</div>`;
        return html + `</div></div>`;
    }

    _buildVsInsightsHtml(insights, vs, last) {
        if (insights && insights.available) {
            const hits = insights.signalHits || {};
            const hitParts = [];
            if (hits.chance) hitParts.push("机会榜");
            if (hits.risk) hitParts.push("风险榜");
            if (hits.funds) hitParts.push("资金异动");
            let html = `<div class="signal-structured-block signal-vs-summary"><h4>ValueScan 追踪摘要</h4><div class="signal-inline-list">`;
            html += `<span class="signal-chip">大盘 ${this.escapeHtml(insights.marketRegimeLabel || "-")}</span>`;
            if (hitParts.length) html += `<span class="signal-chip signal-chip-warning">${hitParts.join(" · ")}</span>`;
            html += `<span class="signal-chip">倾向 ${this.escapeHtml(insights.actionBias || "-")}</span>`;
            html += `</div><p class="signal-inline-note">${this.escapeHtml(insights.primaryAlert || "")}</p>`;
            const plan = insights.suggestedPlan || {};
            if (plan.entryLow && plan.stop) {
                html += `<div class="signal-inline-note">VS 建议价：入场 ${this.formatNumber(plan.entryLow)}~${this.formatNumber(plan.entryHigh)} · 止损 ${this.formatNumber(plan.stop)} · 目标 ${this.formatNumber(plan.target1)}</div>`;
            }
            const alerts = insights.alerts || [];
            if (alerts.length > 1) {
                html += `<ul class="signal-reasons-compact">${alerts.slice(1, 5).map(a => `<li>${this.escapeHtml(a)}</li>`).join("")}</ul>`;
            }
            return html + `</div>`;
        }
        return this._buildVsSummaryHtml(vs, last);
    }

    _buildFiveSignalHtml(data) {
        const row = typeof data === "object" && data.fiveSignalAlignment
            ? data
            : { fiveSignalAlignment: data || {} };
        if (!row.fiveSignalAlignment || !Object.keys(row.fiveSignalAlignment).length) return "";
        const body = DashboardUtils.formatFiveSignalsHtml(row, { gate: false });
        return (
            `<div class="signal-structured-block"><h4>信号明细（入场门禁：四周期 + LLM 因子 + 量化确认 + 可执行）</h4>` +
            `${body}` +
            `<p class="signal-inline-note">实盘页需相同币种、相同 LLM 模型，并建议同样开启 TradingAgents，同一时刻结果才一致。</p>` +
            `</div>`
        );
    }

    _buildVsSummaryHtml(vs, last) {
        if (!vs || !Object.keys(vs).length) return "";
        const chips = [];
        const fund = vs.fund || {};
        const spots = fund.spotGoodsList || [];
        if (spots.length) {
            const d1 = spots.find(s => s.timeRange === "D1") || spots[spots.length - 1];
            const inflow = Number(d1.tradeInflow || 0);
            chips.push(`资金 D1 净流入 <span class="${inflow >= 0 ? "change-up" : "change-down"}">$${this.formatNumber(inflow)}</span>`);
        }
        const sent = vs.sentiment || {};
        if (sent.bullishRatio != null) {
            chips.push(`社媒看多 ${(sent.bullishRatio * 100).toFixed(0)}%`);
        }
        if (vs.aiSignals && Object.keys(vs.aiSignals).length) {
            chips.push(`AI 榜单命中: ${Object.keys(vs.aiSignals).join("/")}`);
        }
        const sr = vs.supportResistance || [];
        if (sr.length && last) {
            const nearest = sr.reduce((best, z) => {
                const p = Number(z.price || z.densePrice || 0);
                if (!p) return best;
                const dist = Math.abs(p - last);
                return !best || dist < best.dist ? { dist, p, t: z.type || z.denseType } : best;
            }, null);
            if (nearest) chips.push(`近邻 ${nearest.t || "位"} $${this.formatNumber(nearest.p)}`);
        }
        if (vs.aiMarketAnalyseHistory && vs.aiMarketAnalyseHistory.length) {
            const latest = vs.aiMarketAnalyseHistory[0];
            const preview = (latest.content || "").slice(0, 80);
            if (preview) chips.push(`大盘解析: ${this.escapeHtml(preview)}${preview.length >= 80 ? "…" : ""}`);
        }
        if (!chips.length) return "";
        return `<div class="signal-structured-block signal-vs-summary"><h4>ValueScan 摘要</h4><div class="signal-inline-list">${chips.map(c => `<span class="signal-chip">${c}</span>`).join("")}</div></div>`;
    }

    renderSignalLogicFlow({ data, signal, label, confidence, score }) {
        const analysis = data.analysis || {}, factors = data.factors || {}, dataQuality = data.dataQuality || {}, plan = data.tradePlan || {};
        const consensus = analysis.consensus || {}, execution = analysis.execution || {};
        const factorSummary = [
            ["技术面", factors.technical],
            ["筹码/资金（VS）", factors.onchain],
            ["盘面/资金情绪", factors.positioning],
            ["共识（含新闻）", analysis.consensus],
        ].filter(([, b]) => b && (((b.highlights || []).length) || Number(b.score || 0) !== 0 || b.agreementScore != null))
            .map(([t, b]) => {
                if (b.agreementScore != null) {
                    return `${t}: ${this.toChineseDisplay("direction", b.direction || "neutral")} / 一致性 ${(Number(b.agreementScore) * 100).toFixed(0)}%`;
                }
                return `${t}: ${this.toChineseDisplay("direction", b.direction || "neutral")} / ${Number(b.score || 0).toFixed(1)}`;
            }).join("<br>");
        const conflictText = (consensus.conflicts || dataQuality.conflictFlags || []).slice(0, 2).map(i => this.escapeHtml(i)).join("；") || "主要维度方向一致";
        const qualityText = dataQuality.coverageScore != null ? `覆盖度 ${(Number(dataQuality.coverageScore || 0) * 100).toFixed(0)}%` : "覆盖度未知";
        const actionText = execution.action ? this.escapeHtml(execution.action) : plan.entryLow || plan.entryHigh ? `参考 ${this.formatNumber(plan.entryLow)} ~ ${this.formatNumber(plan.entryHigh)} 区间执行` : "等待更多确认信号";
        const steps = [
            { title: "① 市场状态识别", body: `${this.toChineseDisplay("marketState", analysis.marketState || "uncertain")} · ${this.toChineseDisplay("bias", analysis.bias || "neutral")}`, meta: `${this.toChineseDisplay("horizon", analysis.horizon || "intraday")} / ${qualityText}` },
            { title: "② 多维证据汇总", body: factorSummary || "暂无结构化因子", meta: `消息 ${Number(data.newsCount || 0)} 条 · 一致性 ${(Number(consensus.agreementScore || 0) * 100).toFixed(0)}%` },
            { title: "③ 冲突与风险校验", body: conflictText, meta: `执行准备度 ${this.toChineseDisplay("executionReadiness", analysis.executionReadiness || "wait")}` },
            { title: "④ 执行与风控落地", body: actionText, meta: `RR1 ${execution.riskReward1 != null ? Number(execution.riskReward1).toFixed(2) : "-"} · RR2 ${execution.riskReward2 != null ? Number(execution.riskReward2).toFixed(2) : "-"}` },
        ];
        let html = `<div class="signal-logic-flow"><div class="signal-logic-head"><h4>逻辑流转 · 如何推出该信号</h4><div class="signal-logic-final">结论：<strong>${this.escapeHtml(label)}</strong> · 置信度 ${Number(confidence || 0).toFixed(1)}% · 得分 ${score > 0 ? "+" : ""}${Number(score || 0).toFixed(0)}</div></div><div class="signal-logic-steps">`;
        steps.forEach((s, i) => { html += `<div class="signal-logic-step"><div class="signal-logic-step-title">${s.title}</div><div class="signal-logic-step-body">${s.body}</div><div class="signal-logic-step-meta">${s.meta}</div></div>`; if (i < steps.length - 1) html += `<div class="signal-logic-arrow">→</div>`; });
        html += `</div><div class="signal-logic-foot"><span class="signal-chip ${signal === "BUY" || signal === "WEAK_BUY" ? "signal-chip-positive" : signal === "SELL" || signal === "WEAK_SELL" ? "signal-chip-negative" : "signal-chip-warning"}">${this.escapeHtml(signal)}</span>`;
        if (plan.stop) html += `<span class="signal-chip">失效位 ${this.formatNumber(plan.stop)}</span>`;
        if (plan.target1) html += `<span class="signal-chip">目标位 ${this.formatNumber(plan.target1)}</span>`;
        html += `</div></div>`;
        return html;
    }

    // ── News ─────────────────────────────────────────────────
    async loadNews() {
        if (!this.elements.newsList) return;
        const sym = this.state.baseSymbol;
        this.elements.newsList.textContent = `加载 ${sym} 消息中...`;
        try {
            const response = await fetch(`/api/dashboard/news?symbol=${encodeURIComponent(sym)}&limit=20`);
            const data = await this.parseJsonResponse(response);
            if (!data.ok) throw new Error(data.message || "加载失败");
            this._renderNews(data.news || [], data.message || "");
        } catch (error) { this.elements.newsList.innerHTML = `<div class="news-error">加载失败: ${this.escapeHtml(error.message)}</div>`; }
    }

    _renderNews(list, msg) {
        if (!this.elements.newsList) return;
        if (!list.length) { this.elements.newsList.innerHTML = `<div class='news-empty'>${this.escapeHtml(msg || "暂无要闻")}</div>`; return; }
        const sourceCountMap = {};
        list.forEach(n => { const s = n.source || "unknown"; sourceCountMap[s] = (sourceCountMap[s] || 0) + 1; });
        const badges = Object.entries(sourceCountMap).map(([s, c]) => `<span class="news-src-badge${s === "web_search" ? " ws" : ""}">${this.escapeHtml(s === "web_search" ? "🔍 Web Search" : s)} (${c})</span>`).join("");
        let html = `<div class="news-source-bar">${badges}<span class="news-total">${list.length} 条</span></div>`;
        html += list.map(item => {
            const title = (item.title || "").trim() || "无标题", url = item.url || "#", source = (item.source || "").trim() || "—";
            const body = (item.body || "").trim(), time = item.publishedAt ? new Date(item.publishedAt).toLocaleString("zh-CN", { dateStyle: "short", timeStyle: "short" }) : "";
            const bodyHtml = body ? `<span class="news-body">${this.escapeHtml(body.length > 120 ? body.slice(0, 120) + "..." : body)}</span>` : "";
            return `<a class="news-item" href="${url}" target="_blank" rel="noopener"><span class="news-title">${this.escapeHtml(title)}</span>${bodyHtml}<span class="news-meta${source === "web_search" ? " ws" : ""}">${this.escapeHtml(source)}${time ? " · " + time : ""}</span></a>`;
        }).join("");
        this.elements.newsList.innerHTML = html;
    }

    // ── Onchain ──────────────────────────────────────────────
    async loadOnchain() {
        if (!this.elements.onchainContent) return;
        const sym = this.state.baseSymbol;
        this.elements.onchainContent.textContent = `加载 ${sym} ValueScan 链上数据...`;
        try {
            const response = await fetch(`/api/dashboard/onchain?symbol=${encodeURIComponent(sym)}&limit=8`);
            const data = await this.parseJsonResponse(response);
            if (!data.ok) throw new Error(data.message || "加载失败");
            this._renderOnchain(data);
        } catch (error) {
            this.elements.onchainContent.innerHTML = `<div class="onchain-error">筹码/资金数据加载失败: ${this.escapeHtml(error.message)}</div>`;
        }
    }

    _renderOnchain(data) {
        if (!this.elements.onchainContent || !data) {
            this.elements.onchainContent.innerHTML = "<div class='onchain-empty'>暂无 ValueScan 链上数据</div>";
            return;
        }
        const chain = data.valuescanChain || {};
        const symbol = data.symbol || "BTC";
        let html = `<div class="onchain-desc">数据来源: ValueScan 开放 API · <a href="https://claw.valuescan.io/zh-CN/%E6%8E%A5%E5%8F%A3%E6%96%87%E6%A1%A3%E6%80%BB%E8%A7%88.html" target="_blank" rel="noopener">接口文档</a></div>`;

        const flow = chain.tokenFlow || {};
        if (Object.keys(flow).length) {
            html += `<div class="oc-section-title">代币流向</div><pre class="onchain-json-snippet">${this.escapeHtml(JSON.stringify(flow, null, 0).slice(0, 600))}</pre>`;
        }

        const whale = chain.whaleCost || [];
        if (whale.length) {
            const latest = whale[whale.length - 1] || {};
            html += `<div class="oc-section-title">主力成本</div><div class="oc-metrics-grid">`;
            if (latest.cost != null) html += `<div class="oc-metric-mini"><div class="oc-mini-label">最新成本</div><div class="oc-mini-value">$${this.formatNumber(latest.cost)}</div></div>`;
            if (latest.price != null) html += `<div class="oc-metric-mini"><div class="oc-mini-label">现价</div><div class="oc-mini-value">$${this.formatNumber(latest.price)}</div></div>`;
            html += `</div>`;
        }

        const txns = chain.largeTransactions || [];
        if (txns.length) {
            html += `<div class="vs-whale-block"><div class="vs-metric-header">大额交易 <small>(${txns.length} 笔)</small></div><div class="vs-txn-table"><div class="vs-txn-head"><span>时间</span><span>数量</span><span>来源</span><span>去向</span></div>`;
            txns.slice(0, 8).forEach(tx => {
                const t = tx.blockTime ? new Date(tx.blockTime).toLocaleString("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "-";
                html += `<div class="vs-txn-row"><span>${t}</span><span>${tx.amount ? this.formatNumber(Number(tx.amount)) : "-"}</span><span>${this.escapeHtml(tx.fromExchangeName || this.shortenAddr(tx.fromAddress) || "-")}</span><span>${this.escapeHtml(tx.toExchangeName || this.shortenAddr(tx.toAddress) || "-")}</span></div>`;
            });
            html += `</div></div>`;
        }

        const holders = chain.holderList || [];
        if (holders.length) {
            html += `<div class="vs-whale-block"><div class="vs-metric-header">持币地址 Top${Math.min(5, holders.length)}</div>`;
            holders.slice(0, 5).forEach((h, i) => {
                html += `<div class="vs-holder-row"><span>#${i + 1}</span> <span>${this.escapeHtml(this.shortenAddr(h.address))}</span> <span>${this.formatNumber(h.balance || h.holdAmount || 0)}</span></div>`;
            });
            html += `</div>`;
        }

        const trends = chain.topHolderAddressTrends || [];
        if (trends.length) {
            html += `<div class="oc-section-title">Top 地址趋势（余额/持仓）</div>`;
            trends.forEach(t => {
                html += `<div class="signal-inline-note">${this.escapeHtml(this.shortenAddr(t.address))} · 样本 ${(t.balanceTrend || []).length} 点</div>`;
            });
        }

        const mcp = data.mcp || {};
        if ((mcp.summary || "").trim()) {
            html += `<div class="oc-sentiment-section"><div class="oc-section-title">MCP 补充</div><p class="onchain-summary">${this.escapeHtml(mcp.summary)}</p></div>`;
        }

        if (!chain.vsTokenId && !txns.length && !whale.length && !holders.length) {
            html += `<div class='onchain-empty'>未找到 ${symbol} 的 ValueScan 代币或未配置 VS_OPEN_API_KEY</div>`;
        }
        this.elements.onchainContent.innerHTML = html;
    }

    // ── VS Whale On-chain ────────────────────────────────────
    async loadVsWhaleOnchain() {
        if (!this.elements.vsWhaleOnchainContent) return;
        const sym = this.state.baseSymbol;
        if (this.elements.vsWhaleSymbolLabel) this.elements.vsWhaleSymbolLabel.textContent = sym;
        this.elements.vsWhaleOnchainContent.textContent = `加载 ${sym} 巨鲸链上数据...`;
        try {
            const resp = await fetch(`/api/dashboard/vs/whale-onchain?symbol=${encodeURIComponent(sym)}`);
            const data = await this.parseJsonResponse(resp);
            if (!data.ok) throw new Error(data.message || "加载失败");
            this._renderVsWhaleOnchain(data, sym);
        } catch (err) { this.elements.vsWhaleOnchainContent.innerHTML = `<div class="vs-fund-error">巨鲸数据加载失败: ${this.escapeHtml(err.message)}</div>`; }
    }

    _renderVsWhaleOnchain(data, symbol) {
        if (!this.elements.vsWhaleOnchainContent) return;
        const txns = data.largeTxns || [], holders = data.holders || [];
        let html = "";
        if (txns.length) {
            html += `<div class="vs-whale-block"><div class="vs-metric-header">大额链上交易 <small>(${txns.length} 笔)</small></div><div class="vs-txn-table"><div class="vs-txn-head"><span>时间</span><span>数量</span><span>来源</span><span>去向</span><span>TxHash</span></div>`;
            txns.forEach(tx => {
                const t = tx.blockTime ? new Date(tx.blockTime).toLocaleString("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "-";
                html += `<div class="vs-txn-row"><span>${t}</span><span class="vs-txn-amount">${tx.amount ? this.formatNumber(Number(tx.amount)) : "-"} ${symbol}</span><span class="${tx.fromExchangeName ? "vs-txn-exchange" : ""}">${this.escapeHtml(tx.fromExchangeName || this.shortenAddr(tx.fromAddress) || "未知")}</span><span class="${tx.toExchangeName ? "vs-txn-exchange" : ""}">${this.escapeHtml(tx.toExchangeName || this.shortenAddr(tx.toAddress) || "未知")}</span><span class="vs-txn-hash" title="${tx.transHash || ""}">${(tx.transHash || "").slice(0, 8)}...</span></div>`;
            });
            html += `</div></div>`;
        }
        if (holders.length) {
            html += `<div class="vs-whale-block"><div class="vs-metric-header">Top 持仓地址</div><div class="vs-holder-table"><div class="vs-holder-head"><span>#</span><span>地址 / 标签</span><span>持仓量</span><span>持仓成本</span><span>浮盈</span></div>`;
            holders.forEach((h, i) => {
                const label = h.label ? (h.label.labelName || "") : "";
                const addrDisplay = label || this.shortenAddr(h.address);
                const labelIcon = h.label?.labelType === "Exchange" ? "🏦 " : h.label?.labelType ? "🏷️ " : "";
                const profit = h.profit ? Number(h.profit) : 0;
                html += `<div class="vs-holder-row ${h.address ? "vs-holder-clickable" : ""}" data-vs-addr="${h.address || ""}" data-vs-sym="${symbol}"><span>${i + 1}</span><span class="vs-holder-addr" title="${h.address || ""}">${labelIcon}${this.escapeHtml(addrDisplay)}</span><span>${h.balance ? this.formatNumber(Number(h.balance)) : "-"}</span><span>${h.cost ? "$" + this.formatNumber(Number(h.cost)) : "-"}</span><span class="${profit >= 0 ? "change-up" : "change-down"}">$${this.formatNumber(profit)}</span></div>`;
            });
            html += `</div></div>`;
        }
        if (!html) html = `<div class="vs-fund-error">暂无 ${symbol} 巨鲸链上数据</div>`;
        html += `<div class="onchain-desc">数据来源: ValueScan On-chain</div>`;
        this.elements.vsWhaleOnchainContent.innerHTML = html;
        this.elements.vsWhaleOnchainContent.querySelectorAll(".vs-holder-clickable").forEach(row => {
            row.addEventListener("click", () => { if (row.dataset.vsAddr) this.showVsAddressDetail(row.dataset.vsSym, row.dataset.vsAddr); });
        });
    }

    // ── VS Price Indicators ──────────────────────────────────
    async loadVsPriceIndicators() {
        if (!this.elements.vsIndicatorsContent) return;
        const sym = this.state.baseSymbol;
        if (this.elements.vsIndicatorSymbolLabel) this.elements.vsIndicatorSymbolLabel.textContent = sym;
        this.elements.vsIndicatorsContent.textContent = `加载 ${sym} 价格指标...`;
        try {
            const resp = await fetch(`/api/dashboard/vs/price-indicators?symbol=${encodeURIComponent(sym)}`);
            const data = await this.parseJsonResponse(resp);
            if (!data.ok) throw new Error(data.message || "加载失败");
            const indicators = data.indicators || [];
            if (!indicators.length) { this.elements.vsIndicatorsContent.innerHTML = `<div class="vs-fund-error">暂无 ${sym} 价格指标</div>`; return; }
            const typeMap = { 1: { label: "看多 (Bull)", cls: "change-up" }, 2: { label: "看空 (Bear)", cls: "change-down" } };
            const recent = indicators.slice(0, 30);
            const bull = recent.filter(i => i.priceMarketType === 1).length, bear = recent.filter(i => i.priceMarketType === 2).length, total = bull + bear || 1;
            let html = `<div class="vs-indicator-summary"><span>近30条信号: </span><span class="change-up">看多 ${bull} (${(bull / total * 100).toFixed(0)}%)</span><span class="change-down">看空 ${bear} (${(bear / total * 100).toFixed(0)}%)</span></div><div class="vs-indicator-grid">`;
            recent.forEach(item => { const date = item.date ? new Date(item.date).toLocaleString("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "-"; const info = typeMap[item.priceMarketType] || { label: String(item.priceMarketType), cls: "" }; html += `<div class="vs-indicator-item"><span class="vs-indicator-date">${date}</span><span class="vs-indicator-signal ${info.cls}">${info.label}</span></div>`; });
            html += `</div><div class="onchain-desc">数据来源: ValueScan Price Market Indicators</div>`;
            this.elements.vsIndicatorsContent.innerHTML = html;
        } catch (err) { this.elements.vsIndicatorsContent.innerHTML = `<div class="vs-fund-error">价格指标加载失败: ${this.escapeHtml(err.message)}</div>`; }
    }

    // ── VS Modal helpers ─────────────────────────────────────
    openVsDetailModal(title, html) { if (this.elements.vsDetailModalTitle) this.elements.vsDetailModalTitle.textContent = title; if (this.elements.vsDetailModalBody) this.elements.vsDetailModalBody.innerHTML = html; if (this.elements.vsDetailModal) this.elements.vsDetailModal.classList.add("active"); }
    closeVsDetailModal() { if (this.elements.vsDetailModal) this.elements.vsDetailModal.classList.remove("active"); }

    async showVsAddressDetail(symbol, address) {
        const shortAddr = address.slice(0, 8) + "..." + address.slice(-6);
        this.openVsDetailModal(`${symbol} 地址分析 ${shortAddr}`, "<div class='vs-fund-error'>加载中...</div>");
        try {
            const resp = await fetch(`/api/dashboard/vs/address-detail?symbol=${encodeURIComponent(symbol)}&address=${encodeURIComponent(address)}`);
            const data = await this.parseJsonResponse(resp);
            if (!data.ok) throw new Error(data.message || "加载失败");
            let html = `<div class="vs-addr-header">${this.escapeHtml(address)}</div>`;
            const sections = [
                { key: "balanceTrend", label: "余额趋势", render: (i) => `${this.formatNumber(Number(i.balance || 0))} ${symbol}` },
                { key: "profitLossTrend", label: "盈亏趋势", render: (i) => { const t = Number(i.total || 0); return `<span class="${t >= 0 ? 'change-up' : 'change-down'}">$${this.formatNumber(t)}</span>`; } },
                { key: "holdTrend", label: "持仓成本趋势", render: (i) => `均价: $${this.formatNumber(Number(i.holdingPrice || 0))} / 现价: $${this.formatNumber(Number(i.price || 0))}` },
            ];
            sections.forEach(sec => {
                const items = data[sec.key] || [];
                if (!items.length) return;
                html += `<div class="vs-addr-section"><div class="vs-metric-header">${sec.label}</div><div class="vs-addr-trend">`;
                items.slice(-15).forEach(item => { const date = item.date ? new Date(item.date).toLocaleDateString("zh-CN", { month: "short", day: "numeric" }) : "-"; html += `<div class="vs-addr-trend-item"><span>${date}</span><span>${sec.render(item)}</span></div>`; });
                html += `</div></div>`;
            });
            if (html.indexOf("vs-addr-section") < 0) html += "<div class='vs-fund-error'>暂无地址趋势数据</div>";
            this.openVsDetailModal(`${symbol} 地址分析`, html);
        } catch (err) { this.openVsDetailModal(`地址分析`, `<div class="vs-fund-error">${this.escapeHtml(err.message)}</div>`); }
    }
}

// Merge shared utilities
if (typeof DashboardUtils !== "undefined") {
    Object.keys(DashboardUtils).forEach(key => { AnalysisPage.prototype[key] = DashboardUtils[key]; });
}
// Merge DexMixin for DEX data rendering
if (typeof DexMixin !== "undefined") {
    Object.keys(DexMixin).forEach(key => {
        if (key === "DEX_ELEMENT_IDS") return;
        AnalysisPage.prototype[key] = DexMixin[key];
    });
}

document.addEventListener("DOMContentLoaded", () => { new AnalysisPage().init(); });
