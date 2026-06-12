class StrategyPage {
    constructor() {
        const _el = (id) => document.getElementById(id);
        this.elements = {
            strategySymbolInput: _el("strategySymbolInput"),
            strategyKlineTypeSelect: _el("strategyKlineTypeSelect"),
            strategyModelSelect: _el("strategyModelSelect"),
            applyStrategyBtn: _el("applyStrategyBtn"),
            generateSignalBtn: _el("generateSignalBtn"),
            signalRefreshToggle: _el("signalRefreshToggle"),
            signalRefreshCountdown: _el("signalRefreshCountdown"),
            autoRefreshToggle: _el("autoRefreshToggle"),
            strategyBaseInfo: _el("strategyBaseInfo"),
            strategyPairLabel: _el("strategyPairLabel"),
            strategyKlineChart: _el("strategyKlineChart"),
            strategyKlineChartHint: _el("strategyKlineChartHint"),
            strategyKlineMetrics: _el("strategyKlineMetrics"),
            strategyKlineVerdict: _el("strategyKlineVerdict"),
            strategySignalSymbolLabel: _el("strategySignalSymbolLabel"),
            strategySignalBadge: _el("strategySignalBadge"),
            strategySignalContent: _el("strategySignalContent"),
            strategyModelTag: _el("strategyModelTag"),
        };

        this.state = {
            baseSymbol: "BTC",
            pairSymbol: "BTC-USDT",
            quote: "USDT",
            model: "deepseek/deepseek-v4-pro",
            klineType: "1hour",
        };

        this.klineStack = null;
        this._signalRefreshTimer = null;
        this._signalCountdownTimer = null;
        this._signalCountdownSec = 0;
    }

    init() {
        this.hydrateFromQuery();
        this.bindEvents();
        this.initKlineChart();
        this.loadMarketData();
        this.loadSignalAnalysis();
    }

    hydrateFromQuery() {
        const params = new URLSearchParams(window.location.search || "");
        this.setSymbolState(params.get("symbol") || "BTC");
        this.state.model = params.get("model") || this.state.model;
        this.state.klineType = params.get("type") || this.state.klineType;
        this.elements.strategySymbolInput.value = this.state.baseSymbol;
        this.elements.strategyModelSelect.value = this.state.model;
        this.elements.strategyKlineTypeSelect.value = this.state.klineType;
        this.updateStaticLabels();
    }

    bindEvents() {
        this.elements.applyStrategyBtn?.addEventListener("click", () => this.applySymbol());
        this.elements.generateSignalBtn?.addEventListener("click", () => this.loadSignalAnalysis());
        this.elements.signalRefreshToggle?.addEventListener("change", () => this.handleSignalRefreshToggle());
        this.elements.autoRefreshToggle?.addEventListener("change", () => this.handleAutoRefreshToggle());
        this.elements.strategyModelSelect?.addEventListener("change", () => {
            this.state.model = this.elements.strategyModelSelect.value || this.state.model;
            this.updateStaticLabels();
            this.updateUrl();
        });
        this.elements.strategyKlineTypeSelect?.addEventListener("change", () => {
            this.state.klineType = this.elements.strategyKlineTypeSelect.value || this.state.klineType;
            this.updateUrl();
            this.loadKlineAnalysis();
        });
        this.elements.strategySymbolInput?.addEventListener("keydown", (event) => {
            if (event.key === "Enter") this.applySymbol();
        });
        window.addEventListener("resize", () => this.resizeKlineChart());
    }

    handleAutoRefreshToggle() {
        if (this.elements.autoRefreshToggle?.checked) {
            this.startAutoRefresh();
        } else {
            this.stopAutoRefresh();
        }
    }

    applySymbol() {
        this.setSymbolState(this.elements.strategySymbolInput.value || this.state.baseSymbol);
        this.updateStaticLabels();
        this.updateUrl();
        this.loadMarketData();
        if (this.elements.autoRefreshToggle?.checked) {
            this.stopAutoRefresh();
            this.startAutoRefresh();
        }
    }

    setSymbolState(rawSymbol) {
        const raw = String(rawSymbol || "BTC").trim().toUpperCase().replace(/\s+/g, "").replace(/\//g, "-").replace(/_/g, "-");
        if (/^[A-Z0-9]+-[A-Z0-9]+$/.test(raw)) {
            const [base] = raw.split("-");
            this.state.baseSymbol = base || "BTC";
            this.state.quote = "USDT";
            this.state.pairSymbol = `${this.state.baseSymbol}-USDT`;
        } else {
            this.state.baseSymbol = raw.replace(/-.*/, "") || "BTC";
            this.state.quote = "USDT";
            this.state.pairSymbol = `${this.state.baseSymbol}-${this.state.quote}`;
        }
        if (this.elements.strategySymbolInput) this.elements.strategySymbolInput.value = this.state.baseSymbol;
    }

    updateStaticLabels() {
        if (this.elements.strategyPairLabel) this.elements.strategyPairLabel.textContent = this.state.pairSymbol;
        if (this.elements.strategySignalSymbolLabel) this.elements.strategySignalSymbolLabel.textContent = this.state.baseSymbol;
        if (this.elements.strategyModelTag) this.elements.strategyModelTag.textContent = this.formatModelName(this.state.model);
    }

    updateUrl() {
        const params = new URLSearchParams();
        params.set("symbol", this.state.baseSymbol);
        params.set("model", this.state.model);
        params.set("type", this.state.klineType);
        window.history.replaceState({}, "", `/strategy?${params.toString()}`);
    }

    async loadPageData() {
        this.updateUrl();
        this.renderBaseInfoLoading();
        await Promise.all([
            this.loadBasicInfo(),
            this.loadKlineAnalysis(),
        ]);
    }

    async loadMarketData() {
        this.renderBaseInfoLoading();
        await Promise.all([
            this.loadBasicInfo(),
            this.loadKlineAnalysis(),
        ]);
    }

    startAutoRefresh() {
        this.stopAutoRefresh();
        this._marketRefreshTimer = setInterval(() => this.loadMarketData(), 10000);
    }

    stopAutoRefresh() {
        if (this._marketRefreshTimer) {
            clearInterval(this._marketRefreshTimer);
            this._marketRefreshTimer = null;
        }
    }

    /* ── 定时信号刷新 (5 min) ────────────────────── */
    handleSignalRefreshToggle() {
        if (this.elements.signalRefreshToggle?.checked) {
            this.startSignalRefresh();
        } else {
            this.stopSignalRefresh();
        }
    }

    startSignalRefresh() {
        this.stopSignalRefresh();
        const INTERVAL = 5 * 60; // 300 seconds
        this._signalCountdownSec = INTERVAL;
        this.updateSignalCountdown();
        this._signalCountdownTimer = setInterval(() => {
            this._signalCountdownSec--;
            if (this._signalCountdownSec <= 0) {
                this._signalCountdownSec = INTERVAL;
                this.loadSignalAnalysis();
            }
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
        const m = Math.floor(this._signalCountdownSec / 60);
        const s = this._signalCountdownSec % 60;
        this.elements.signalRefreshCountdown.textContent = `${m}:${String(s).padStart(2, "0")}`;
    }

    renderBaseInfoLoading() {
        if (!this.elements.strategyBaseInfo) return;
        this.elements.strategyBaseInfo.innerHTML = `
            <article class="stats-card"><h3>当前币种</h3><p>${this.escapeHtml(this.state.baseSymbol)}</p></article>
            <article class="stats-card"><h3>最新价格</h3><p>加载中...</p></article>
            <article class="stats-card"><h3>24h 涨跌</h3><p>加载中...</p></article>
            <article class="stats-card"><h3>24h 高低</h3><p>加载中...</p></article>
            <article class="stats-card"><h3>24h 成交额</h3><p>加载中...</p></article>
            <article class="stats-card"><h3>交易对</h3><p>${this.escapeHtml(this.state.pairSymbol)}</p></article>
        `;
    }

    async loadBasicInfo() {
        const url = `/api/market/tickers?quote=${encodeURIComponent(this.state.quote)}&search=${encodeURIComponent(this.state.baseSymbol)}&limit=50`;
        try {
            const response = await fetch(url);
            const data = await this.parseJsonResponse(response);
            if (!response.ok || !data.ok) throw new Error(data.message || "基础信息加载失败");
            const tickers = Array.isArray(data.tickers) ? data.tickers : [];
            const matched = tickers.find((item) => String(item.symbol || "").toUpperCase() === this.state.pairSymbol)
                || tickers.find((item) => String(item.symbol || "").toUpperCase().startsWith(`${this.state.baseSymbol}-`))
                || null;
            this.renderBaseInfo(matched);
        } catch (error) {
            this.renderBaseInfo(null, error.message);
        }
    }

    renderBaseInfo(item, errorMessage = "") {
        if (!this.elements.strategyBaseInfo) return;
        if (!item) {
            this.elements.strategyBaseInfo.innerHTML = `
                <article class="stats-card"><h3>当前币种</h3><p>${this.escapeHtml(this.state.baseSymbol)}</p></article>
                <article class="stats-card"><h3>最新价格</h3><p>-</p></article>
                <article class="stats-card"><h3>24h 涨跌</h3><p>-</p></article>
                <article class="stats-card"><h3>24h 高低</h3><p>-</p></article>
                <article class="stats-card"><h3>24h 成交额</h3><p>-</p></article>
                <article class="stats-card"><h3>状态</h3><p>${this.escapeHtml(errorMessage || "未获取到基础信息")}</p></article>
            `;
            return;
        }
        const changeRate = Number(item.changeRate || 0) * 100;
        const changeClass = changeRate >= 0 ? "change-up" : "change-down";
        const highLow = `${this.formatNumber(item.high)} / ${this.formatNumber(item.low)}`;
        this.elements.strategyBaseInfo.innerHTML = `
            <article class="stats-card"><h3>当前币种</h3><p>${this.escapeHtml(this.state.baseSymbol)}</p></article>
            <article class="stats-card"><h3>最新价格</h3><p>${this.formatNumber(item.last)}</p></article>
            <article class="stats-card"><h3>24h 涨跌</h3><p class="${changeClass}">${changeRate >= 0 ? "+" : ""}${changeRate.toFixed(2)}%</p></article>
            <article class="stats-card"><h3>24h 高低</h3><p>${highLow}</p></article>
            <article class="stats-card"><h3>24h 成交额</h3><p>${this.formatNumber(item.volValue)}</p></article>
            <article class="stats-card"><h3>交易对</h3><p>${this.escapeHtml(item.symbol || this.state.pairSymbol)}</p></article>
        `;
    }

    initKlineChart() {
        const saved = typeof KlineIndicatorControls !== "undefined"
            ? KlineIndicatorControls.loadSaved(KLINE_DEFAULT_INDICATORS || {})
            : {};
        this.klineStack = new KlineChartStack({
            mainEl: this.elements.strategyKlineChart,
            legendEl: document.getElementById("strategyKlineLegend"),
            hintEl: this.elements.strategyKlineChartHint,
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
        if (this.elements.strategyKlineVerdict) this.elements.strategyKlineVerdict.textContent = `正在分析 ${this.state.pairSymbol} K 线...`;
        if (this.elements.strategyKlineChartHint) this.elements.strategyKlineChartHint.textContent = "加载 K 线数据中...";
        try {
            const response = await fetch(`/api/market/kline-analysis?symbol=${encodeURIComponent(this.state.pairSymbol)}&type=${encodeURIComponent(this.state.klineType)}&limit=120`);
            const data = await this.parseJsonResponse(response);
            if (!response.ok || !data.ok) throw new Error(data.message || "K 线分析失败");
            this.renderKline(data);
        } catch (error) {
            this.renderKlineChart([]);
            if (this.elements.strategyKlineMetrics) this.elements.strategyKlineMetrics.innerHTML = `<div class="strategy-empty">${this.escapeHtml(error.message)}</div>`;
            if (this.elements.strategyKlineVerdict) this.elements.strategyKlineVerdict.textContent = `K 线分析失败: ${error.message}`;
        }
    }

    renderKline(payload) {
        const metrics = payload.metrics || {};
        const verdict = payload.verdict || {};
        if (this.elements.strategyPairLabel) this.elements.strategyPairLabel.textContent = payload.symbol || this.state.pairSymbol;
        this.renderKlineChart(payload.candles || []);
        if (this.elements.strategyKlineMetrics) {
            this.elements.strategyKlineMetrics.innerHTML = [
                this.renderMetricCard("趋势", payload.trend || "-"),
                this.renderMetricCard("RSI", metrics.rsi != null ? Number(metrics.rsi).toFixed(1) : "-"),
                this.renderMetricCard("区间位置", metrics.rangePositionPct != null ? `${Number(metrics.rangePositionPct).toFixed(0)}%` : "-"),
                this.renderMetricCard("布林宽度", metrics.bbWidth != null ? `${Number(metrics.bbWidth).toFixed(1)}%` : "-"),
                this.renderMetricCard("支撑", this.formatNumber(metrics.support20)),
                this.renderMetricCard("阻力", this.formatNumber(metrics.resistance20)),
            ].join("");
        }
        if (this.elements.strategyKlineVerdict) {
            const reasons = Array.isArray(verdict.reasons) ? verdict.reasons.slice(0, 6) : [];
            const score = Number(verdict.score || 0);
            const confidence = Number(verdict.confidence || 0);
            const actionLabel = verdict.actionLabel || "观望";
            const actionClass = /买|多|BUY/i.test(actionLabel) ? "kv-action-buy" : /卖|空|SELL/i.test(actionLabel) ? "kv-action-sell" : "kv-action-neutral";
            const periodLabel = this.escapeHtml(payload.type || this.state.klineType);
            const trendLabel = this.escapeHtml(payload.trend || "-");

            let html = `<div class="kv-card">`;
            /* 头部：操作建议 + 核心数据 */
            html += `<div class="kv-header">`;
            html += `<span class="kv-action ${actionClass}">${this.escapeHtml(actionLabel)}</span>`;
            html += `<div class="kv-stats">`;
            html += `<span class="kv-stat"><span class="kv-stat-label">置信度</span><span class="kv-stat-value">${confidence.toFixed(1)}%</span></span>`;
            html += `<span class="kv-stat"><span class="kv-stat-label">评分</span><span class="kv-stat-value">${score > 0 ? "+" : ""}${score.toFixed(1)}</span></span>`;
            html += `<span class="kv-stat"><span class="kv-stat-label">周期</span><span class="kv-stat-value">${periodLabel}</span></span>`;
            html += `<span class="kv-stat"><span class="kv-stat-label">趋势</span><span class="kv-stat-value">${trendLabel}</span></span>`;
            html += `</div></div>`;
            /* 置信度进度条 */
            const barColor = confidence >= 70 ? "#3ecf8e" : confidence >= 40 ? "#f4b942" : "#ff6b6b";
            html += `<div class="kv-bar-wrap"><div class="kv-bar" style="width:${Math.min(confidence, 100)}%;background:${barColor}"></div></div>`;
            /* 分析依据 */
            if (reasons.length) {
                html += `<div class="kv-reasons"><div class="kv-reasons-title">分析依据</div><ul>`;
                reasons.forEach((r, i) => { html += `<li><span class="kv-reason-idx">${i + 1}</span>${this.escapeHtml(r)}</li>`; });
                html += `</ul></div>`;
            }
            html += `</div>`;
            this.elements.strategyKlineVerdict.innerHTML = html;
        }
    }

    async loadSignalAnalysis() {
        if (!this.elements.strategySignalContent) return;
        this.klineStack?.clearTradePlan();
        const stopPoll = () => { if (this._signalPollTimer) { clearInterval(this._signalPollTimer); this._signalPollTimer = null; } this._signalPollN = 0; };
        if (this._signalPollTimer) { stopPoll(); }
        if (this.elements.strategySignalBadge) {
            this.elements.strategySignalBadge.className = "signal-badge signal-neutral";
            this.elements.strategySignalBadge.textContent = "分析中";
        }
        this.elements.strategySignalContent.innerHTML = `<div class="signal-loading">正在提交 ${this.state.baseSymbol} LLM 信号分析任务...</div>`;
        const maxPolls = 200;
        try {
            const submitResp = await fetch(`/api/dashboard/llm-signal-analysis?symbol=${encodeURIComponent(this.state.baseSymbol)}&model=${encodeURIComponent(this.state.model)}`);
            const submitData = await this.parseJsonResponse(submitResp);
            if (!submitResp.ok || !submitData.ok) throw new Error(submitData.message || "提交分析任务失败");
            const taskId = submitData.taskId;
            this._signalPollN = 0;
            this.elements.strategySignalContent.innerHTML = `<div class="signal-loading">LLM 信号分析进行中，请稍候...</div>`;
            this._signalPollTimer = setInterval(async () => {
                try {
                    this._signalPollN = (this._signalPollN || 0) + 1;
                    if (this._signalPollN > maxPolls) {
                        stopPoll();
                        this.elements.strategySignalContent.innerHTML = `<div class="signal-error">分析超时，请重试。若问题持续，请检查服务端与模型网关。</div>`;
                        if (this.elements.strategySignalBadge) { this.elements.strategySignalBadge.className = "signal-badge signal-neutral"; this.elements.strategySignalBadge.textContent = "未就绪"; }
                        return;
                    }
                    if (this._signalPollN % 5 === 0 && this.elements.strategySignalContent) {
                        this.elements.strategySignalContent.innerHTML = `<div class="signal-loading">LLM 信号分析进行中（已约 ${this._signalPollN * 3}s）…</div>`;
                    }
                    const pollResp = await fetch(`/api/dashboard/llm-signal-analysis/poll?taskId=${encodeURIComponent(taskId)}`);
                    const pollData = await this.parseJsonResponse(pollResp);
                    if (!pollResp.ok || pollData.ok === false) {
                        stopPoll();
                        this.elements.strategySignalContent.innerHTML = `<div class="signal-error">轮询失败: ${this.escapeHtml(pollData.message || pollResp.statusText || "未知")}</div>`;
                        if (this.elements.strategySignalBadge) { this.elements.strategySignalBadge.className = "signal-badge signal-neutral"; this.elements.strategySignalBadge.textContent = "未就绪"; }
                        return;
                    }
                    if (pollData.status === "done") {
                        stopPoll();
                        this.renderSignalBlock(pollData.data);
                    } else if (pollData.status === "failed") {
                        stopPoll();
                        this.elements.strategySignalContent.innerHTML = `<div class="signal-error">LLM 信号分析失败: ${this.escapeHtml(pollData.message || "未知错误")}</div>`;
                        if (this.elements.strategySignalBadge) { this.elements.strategySignalBadge.className = "signal-badge signal-neutral"; this.elements.strategySignalBadge.textContent = "未就绪"; }
                    }
                } catch (pollErr) {
                    stopPoll();
                    this.elements.strategySignalContent.innerHTML = `<div class="signal-error">轮询失败: ${this.escapeHtml(pollErr.message)}</div>`;
                    if (this.elements.strategySignalBadge) { this.elements.strategySignalBadge.className = "signal-badge signal-neutral"; this.elements.strategySignalBadge.textContent = "未就绪"; }
                }
            }, 3000);
        } catch (error) {
            this.elements.strategySignalContent.innerHTML = `<div class="signal-error">LLM 信号分析失败: ${this.escapeHtml(error.message)}</div>`;
        }
    }

    renderSignalBlock(data) {
        if (!data || !this.elements.strategySignalContent) return;
        const signal = data.signal || "NEUTRAL";
        const label = data.signalLabel || data.label || "观望";
        const confidence = Number(data.confidence || 0);
        const score = Number(data.score || 0);
        const reasons = Array.isArray(data.reasons) ? data.reasons : [];
        const summary = data.summary || "";
        const market = data.market || {};
        const kline = data.kline || {};
        const analysis = data.analysis || {};
        const factors = data.factors || {};
        const risks = Array.isArray(data.risks) ? data.risks : [];
        const scenarios = Array.isArray(data.scenarios) ? data.scenarios : [];
        const dataQuality = data.dataQuality || {};
        const engineMeta = data.engineMeta || {};
        const onchainMetrics = data.onchainMetrics || {};

        const badgeClassMap = {
            BUY: "signal-buy", WEAK_BUY: "signal-weak-buy", SELL: "signal-sell", WEAK_SELL: "signal-weak-sell", NEUTRAL: "signal-neutral",
        };
        if (this.elements.strategySignalBadge) {
            this.elements.strategySignalBadge.className = `signal-badge ${badgeClassMap[signal] || "signal-neutral"}`;
            this.elements.strategySignalBadge.textContent = label;
        }
        if (this.elements.strategySignalSymbolLabel) this.elements.strategySignalSymbolLabel.textContent = this.state.baseSymbol;
        if (this.elements.strategyModelTag) this.elements.strategyModelTag.textContent = this.formatModelName(engineMeta.model || this.state.model);

        const last = Number(market.last || 0);
        const changeRate = Number(market.changeRate || 0);
        const changeClass = changeRate >= 0 ? "change-up" : "change-down";
        const signedRate = `${changeRate >= 0 ? "+" : ""}${(changeRate * 100).toFixed(2)}%`;

        let klineSummary = "";
        Object.entries(kline).forEach(([key, value]) => {
            const trendMap = { bullish: "多头趋势", bearish: "空头趋势", weak_bullish: "短线偏多", weak_bearish: "短线偏空", neutral: "中性" };
            const labelText = key === "1hour" ? "1h" : key === "4hour" ? "4h" : key;
            const cls = value.trend === "bullish" || value.trend === "weak_bullish" ? "kline-bull" : value.trend === "bearish" || value.trend === "weak_bearish" ? "kline-bear" : "kline-neutral";
            klineSummary += `<span class="signal-kline-tag ${cls}">${labelText}: ${trendMap[value.trend] || value.trend}</span> `;
        });

        let html = `<div class="signal-header-row">`;
        html += `<div class="signal-price"><span class="signal-price-val">${this.formatNumber(last)}</span> <span class="signal-price-change ${changeClass}">${signedRate}</span></div>`;
        html += `<div class="signal-confidence">置信度 <strong>${confidence.toFixed(1)}%</strong> · 综合得分 <strong>${score > 0 ? "+" : ""}${score.toFixed(0)}</strong></div>`;
        html += `</div>`;

        if (klineSummary) html += `<div class="signal-kline-row">${klineSummary}</div>`;
        if (summary) html += `<div class="signal-summary-card"><h4>核心结论</h4><p>${this.escapeHtml(summary)}</p></div>`;
        html += this.renderSignalLogicFlow({ data, signal, label, confidence, score });

        html += `<div class="signal-meta-row">`;
        html += `<span>市场状态: ${this.escapeHtml(this.toChineseDisplay("marketState", analysis.marketState || "uncertain"))}</span>`;
        html += `<span>执行准备度: ${this.escapeHtml(this.toChineseDisplay("executionReadiness", analysis.executionReadiness || "wait"))}</span>`;
        html += `<span>模型: ${this.escapeHtml(this.formatModelName(engineMeta.model || this.state.model))}</span>`;
        if ((onchainMetrics.fearGreed || {}).value != null) html += `<span>恐贪指数: ${onchainMetrics.fearGreed.value}</span>`;
        html += `</div>`;

        if (reasons.length) {
            html += `<div class="signal-reasons"><h4>分析依据</h4><ul>`;
            reasons.slice(0, 12).forEach((reason) => {
                html += `<li class="reason-neutral">${this.escapeHtml(reason)}</li>`;
            });
            html += `</ul></div>`;
        }

        if (data.tradePlan && Object.keys(data.tradePlan).length > 0) {
            const plan = data.tradePlan;
            html += `<div class="signal-trade-plan"><h4>交易计划</h4><div class="signal-grid signal-grid-2">`;
            html += this.renderMetricCard("支撑位", this.formatNumber(plan.support));
            html += this.renderMetricCard("阻力位", this.formatNumber(plan.resistance));
            html += this.renderMetricCard("入场区间", `${this.formatNumber(plan.entryLow)} ~ ${this.formatNumber(plan.entryHigh)}`);
            html += this.renderMetricCard("止损位", this.formatNumber(plan.stop));
            html += this.renderMetricCard("目标一", this.formatNumber(plan.target1));
            html += this.renderMetricCard("目标二", this.formatNumber(plan.target2));
            html += `</div></div>`;
        }

        const consensus = analysis.consensus || {};
        const execution = analysis.execution || {};
        const levels = analysis.keyLevels || {};
        const catalysts = analysis.catalysts || [];
        html += `<div class="signal-structured-block"><h4>策略视角</h4><div class="signal-grid signal-grid-3">`;
        html += this.renderMetricCard("方向偏置", this.toChineseDisplay("bias", analysis.bias || "neutral"));
        html += this.renderMetricCard("市场状态", this.toChineseDisplay("marketState", analysis.marketState || "uncertain"));
        html += this.renderMetricCard("分析周期", this.toChineseDisplay("horizon", analysis.horizon || "intraday"));
        html += this.renderMetricCard("执行准备度", this.toChineseDisplay("executionReadiness", analysis.executionReadiness || "wait"));
        html += this.renderMetricCard("一致性分数", consensus.agreementScore != null ? `${Number(consensus.agreementScore * 100).toFixed(0)}%` : "-");
        html += this.renderMetricCard("一致性强度", this.toChineseDisplay("strength", consensus.strength || "weak"));
        html += this.renderMetricCard("失效位", this.formatNumber(levels.invalidation));
        html += this.renderMetricCard("盈亏比1", execution.riskReward1 != null ? String(execution.riskReward1) : "-");
        html += this.renderMetricCard("盈亏比2", execution.riskReward2 != null ? String(execution.riskReward2) : "-");
        html += `</div>`;
        if ((consensus.conflicts || []).length) html += `<div class="signal-inline-list"><strong>冲突点：</strong>${consensus.conflicts.map((item) => `<span class="signal-chip signal-chip-warning">${this.escapeHtml(item)}</span>`).join("")}</div>`;
        if (execution.action) html += `<div class="signal-inline-note"><strong>执行建议：</strong>${this.escapeHtml(execution.action)}</div>`;
        if (catalysts.length) html += `<div class="signal-inline-list"><strong>催化条件：</strong>${catalysts.map((item) => `<span class="signal-chip signal-chip-positive">${this.escapeHtml(item)}</span>`).join("")}</div>`;
        html += `</div>`;

        const factorEntries = [
            ["技术面", factors.technical],
            ["筹码/资金（ValueScan）", factors.onchain],
            ["消息面", factors.news],
            ["筹码/情绪", factors.positioning],
        ].filter(([, block]) => block && (((block.highlights || []).length > 0) || Number(block.score || 0) !== 0));
        if (factorEntries.length) {
            html += `<div class="signal-structured-block"><h4>多维因子拆解</h4><div class="signal-factor-grid">`;
            factorEntries.forEach(([title, block]) => {
                const highlights = (block.highlights || []).slice(0, 3).map((item) => `<li>${this.escapeHtml(item)}</li>`).join("");
                html += `<div class="signal-factor-card"><div class="signal-factor-head"><span>${title}</span><span>${this.toChineseDisplay("direction", block.direction || "neutral")} · ${Number(block.score || 0).toFixed(1)}</span></div><div class="signal-factor-sub">置信度 ${(Number(block.confidence || 0) * 100).toFixed(0)}%</div>${highlights ? `<ul>${highlights}</ul>` : ""}</div>`;
            });
            html += `</div></div>`;
        }

        if (risks.length) {
            html += `<div class="signal-structured-block"><h4>主要风险</h4><div class="signal-list-grid">`;
            risks.slice(0, 4).forEach((risk) => {
                html += `<div class="signal-info-card"><div class="signal-info-title">${this.escapeHtml(risk.type || "风险")}</div><div class="signal-info-meta">级别: ${this.toChineseDisplay("severity", risk.severity || "medium")}</div>${risk.evidence ? `<p>${this.escapeHtml(risk.evidence)}</p>` : ""}${risk.trigger ? `<p><strong>触发：</strong>${this.escapeHtml(risk.trigger)}</p>` : ""}${risk.mitigation ? `<p><strong>应对：</strong>${this.escapeHtml(risk.mitigation)}</p>` : ""}</div>`;
            });
            html += `</div></div>`;
        }

        if (scenarios.length) {
            html += `<div class="signal-structured-block"><h4>情景推演</h4><div class="signal-list-grid">`;
            scenarios.slice(0, 3).forEach((item) => {
                const targets = (item.target || []).map((value) => this.formatNumber(value)).filter(Boolean).join(" / ");
                html += `<div class="signal-info-card"><div class="signal-info-title">${this.toChineseDisplay("scenario", item.name || "base")} · ${(Number(item.probability || 0) * 100).toFixed(0)}%</div>${item.trigger ? `<p><strong>触发：</strong>${this.escapeHtml(item.trigger)}</p>` : ""}${item.action ? `<p><strong>动作：</strong>${this.escapeHtml(item.action)}</p>` : ""}${targets ? `<p><strong>目标：</strong>${this.escapeHtml(targets)}</p>` : ""}</div>`;
            });
            html += `</div></div>`;
        }

        if (dataQuality && Object.keys(dataQuality).length) {
            html += `<div class="signal-structured-block"><h4>数据质量</h4><div class="signal-grid signal-grid-3">`;
            html += this.renderMetricCard("覆盖度", dataQuality.coverageScore != null ? `${Number(dataQuality.coverageScore * 100).toFixed(0)}%` : "-");
            Object.entries(dataQuality.sourceStatus || {}).forEach(([name, value]) => {
                html += this.renderMetricCard(name, value);
            });
            html += `</div>`;
            if ((dataQuality.limitations || []).length) html += `<div class="signal-inline-note"><strong>局限：</strong>${dataQuality.limitations.map((item) => this.escapeHtml(item)).join("；")}</div>`;
            html += `</div>`;
        }

        this.elements.strategySignalContent.innerHTML = html;
        if (data.tradePlan && Object.keys(data.tradePlan).length > 0) {
            this.klineStack?.setTradePlan(data.tradePlan);
        } else {
            this.klineStack?.clearTradePlan();
        }
    }

    renderSignalLogicFlow({ data, signal, label, confidence, score }) {
        const analysis = data.analysis || {};
        const factors = data.factors || {};
        const dataQuality = data.dataQuality || {};
        const plan = data.tradePlan || {};
        const consensus = analysis.consensus || {};
        const execution = analysis.execution || {};
        const factorSummary = [
            ["技术面", factors.technical],
            ["筹码/资金（ValueScan）", factors.onchain],
            ["消息面", factors.news],
            ["筹码面", factors.positioning],
        ]
            .filter(([, block]) => block && (((block.highlights || []).length > 0) || Number(block.score || 0) !== 0))
            .map(([title, block]) => `${title}: ${this.toChineseDisplay("direction", block.direction || "neutral")} / ${Number(block.score || 0).toFixed(1)}`)
            .join("<br>");

        const conflictText = (consensus.conflicts || dataQuality.conflictFlags || []).slice(0, 2).join("；") || "主要维度方向一致，未见显著冲突";
        const qualityText = dataQuality.coverageScore != null ? `覆盖度 ${(Number(dataQuality.coverageScore || 0) * 100).toFixed(0)}%` : "覆盖度未知";
        const actionText = execution.action || (plan.entryLow || plan.entryHigh ? `参考 ${this.formatNumber(plan.entryLow)} ~ ${this.formatNumber(plan.entryHigh)} 区间执行` : "等待更多确认信号");
        const steps = [
            {
                title: "① 市场状态识别",
                body: `${this.toChineseDisplay("marketState", analysis.marketState || "uncertain")} · ${this.toChineseDisplay("bias", analysis.bias || "neutral")}`,
                meta: `${this.toChineseDisplay("horizon", analysis.horizon || "intraday")} / ${qualityText}`,
            },
            {
                title: "② 多维证据汇总",
                body: factorSummary || "暂无结构化因子，改由 reasons 生成基线判断",
                meta: `消息 ${Number(data.newsCount || 0)} 条 · 一致性 ${(Number(consensus.agreementScore || 0) * 100).toFixed(0)}%`,
            },
            {
                title: "③ 冲突与风险校验",
                body: this.escapeHtml(conflictText),
                meta: `执行准备度 ${this.toChineseDisplay("executionReadiness", analysis.executionReadiness || "wait")}`,
            },
            {
                title: "④ 执行与风控落地",
                body: this.escapeHtml(actionText),
                meta: `RR1 ${execution.riskReward1 != null ? Number(execution.riskReward1).toFixed(2) : "-"} · RR2 ${execution.riskReward2 != null ? Number(execution.riskReward2).toFixed(2) : "-"}`,
            },
        ];

        let html = `<div class="signal-logic-flow"><div class="signal-logic-head"><h4>逻辑流转 · 如何推出该信号</h4><div class="signal-logic-final">结论：<strong>${this.escapeHtml(label)}</strong> · 置信度 ${Number(confidence || 0).toFixed(1)}% · 得分 ${score > 0 ? "+" : ""}${Number(score || 0).toFixed(0)}</div></div><div class="signal-logic-steps">`;
        steps.forEach((step, index) => {
            html += `<div class="signal-logic-step"><div class="signal-logic-step-title">${step.title}</div><div class="signal-logic-step-body">${step.body}</div><div class="signal-logic-step-meta">${step.meta}</div></div>`;
            if (index < steps.length - 1) html += `<div class="signal-logic-arrow">→</div>`;
        });
        html += `</div><div class="signal-logic-foot">`;
        html += `<span class="signal-chip ${signal === "BUY" || signal === "WEAK_BUY" ? "signal-chip-positive" : signal === "SELL" || signal === "WEAK_SELL" ? "signal-chip-negative" : "signal-chip-warning"}">${this.escapeHtml(signal)}</span>`;
        if (plan.stop) html += `<span class="signal-chip">失效位 ${this.formatNumber(plan.stop)}</span>`;
        if (plan.target1) html += `<span class="signal-chip">目标位 ${this.formatNumber(plan.target1)}</span>`;
        html += `</div></div>`;
        return html;
    }

    renderMetricCard(label, value) {
        return `<div class="signal-metric-card"><div class="signal-metric-label">${this.escapeHtml(label)}</div><div class="signal-metric-value">${this.escapeHtml(String(value ?? "-"))}</div></div>`;
    }

    formatModelName(model) {
        const value = String(model || "");
        if (value.includes("deepseek-v4-flash")) return "DeepSeek V4 Flash";
        if (value.includes("deepseek-v4-pro")) return "DeepSeek V4 Pro";
        if (value.includes("deepseek-v4")) return "DeepSeek V4";
        if (value.includes("deepseek-chat")) return "DeepSeek Chat (V3)";
        if (value.includes("deepseek-reasoner")) return "DeepSeek Reasoner";
        if (value.includes("Qwen3.5-27B")) return "Qwen 3.5 27B";
        return value || "-";
    }

    toChineseDisplay(type, value) {
        const text = String(value ?? "").trim();
        if (!text) return "-";
        const map = {
            bias: { bullish: "偏多", bearish: "偏空", neutral: "中性" },
            direction: { bullish: "偏多", bearish: "偏空", neutral: "中性" },
            marketState: {
                trend_continuation: "趋势延续",
                trend_continuation_near_resistance: "趋势延续但接近压力",
                range_rebound: "区间反弹",
                range_breakdown_risk: "区间下破风险",
                breakout_confirmation: "突破确认",
                false_breakout_risk: "假突破风险",
                uncertain: "方向尚不明朗",
            },
            horizon: { intraday: "日内", intraday_swing: "日内到波段", swing: "波段" },
            executionReadiness: { ready: "可执行", watch_pullback: "等待回踩", wait_breakout: "等待突破确认", avoid: "暂不参与", wait: "继续观察" },
            strength: { weak: "较弱", medium: "中等", strong: "较强" },
            severity: { low: "低", medium: "中", high: "高" },
            scenario: { bull: "乐观情景", base: "基准情景", bear: "悲观情景" },
        };
        const normalized = text.toLowerCase();
        const mapped = map[type]?.[normalized];
        if (mapped) return mapped;
        return /[\u4e00-\u9fa5]/.test(text) ? text : text.replace(/_/g, " ");
    }
}

if (typeof DashboardUtils !== "undefined") {
    Object.keys(DashboardUtils).forEach((key) => {
        StrategyPage.prototype[key] = DashboardUtils[key];
    });
}

document.addEventListener("DOMContentLoaded", () => {
    new StrategyPage().init();
});
