const ARENA_AGENT_LABELS = {
    technical_signal: "技术信号",
    trend_hunter: "趋势猎手",
    claude_agent: "Claude",
    dashboard_deepseek: "DeepSeek 看板",
};

const ARENA_AGENT_PRESETS = {
    hybrid_default: {
        agents: ["trend_hunter", "claude_agent", "dashboard_deepseek"],
        executionAgents: ["technical_signal", "claude_agent"],
    },
    llm_consensus: {
        agents: ["claude_agent", "dashboard_deepseek"],
        executionAgents: ["claude_agent"],
    },
    rules_llm: {
        agents: ["technical_signal", "claude_agent"],
        executionAgents: ["technical_signal"],
    },
    minimal: {
        agents: ["technical_signal"],
        executionAgents: ["technical_signal"],
    },
};

class LiveTradingPage {
    constructor() {
        const $ = (id) => document.getElementById(id);
        this.elements = {
            refreshLiveBtn: $("refreshLiveBtn"),
            refreshVsContextBtn: $("refreshVsContextBtn"),
            refreshPositionAlertsBtn: $("refreshPositionAlertsBtn"),
            liveVsMarketBanner: $("liveVsMarketBanner"),
            liveVsSseStatus: $("liveVsSseStatus"),
            liveVsSymbolCards: $("liveVsSymbolCards"),
            livePositionAlerts: $("livePositionAlerts"),
            liveAutomationPipelineSelect: $("liveAutomationPipelineSelect"),
            startLiveAutomationBtn: $("startLiveAutomationBtn"),
            stopLiveAutomationBtn: $("stopLiveAutomationBtn"),
            liveAutomationStatusBtn: $("liveAutomationStatusBtn"),
            liveAutomationRunningBadge: $("liveAutomationRunningBadge"),
            agentArenaMaxRoundsInput: $("agentArenaMaxRoundsInput"),

            llmFuturesAutoLiveInput: $("llmFuturesAutoLiveInput"),
            agentArenaPresetSelect: $("agentArenaPresetSelect"),
            agentArenaPresetSummary: $("agentArenaPresetSummary"),
            agentArenaAdvanced: $("agentArenaAdvanced"),
            agentArenaActiveSelect: $("agentArenaActiveSelect"),
            agentArenaAgentsSelect: $("agentArenaAgentsSelect"),
            agentArenaAccountInput: $("agentArenaAccountInput"),
            agentArenaRagInput: $("agentArenaRagInput"),
            agentArenaMicroInput: $("agentArenaMicroInput"),
            agentArenaCards: $("agentArenaCards"),
            agentArenaSignals: $("agentArenaSignals"),
            analyzeLlmFuturesBtn: $("analyzeLlmFuturesBtn"),
            runLlmFuturesBtn: $("runLlmFuturesBtn"),
            llmFuturesSymbolsInput: $("llmFuturesSymbolsInput"),
            llmFuturesModelSelect: $("llmFuturesModelSelect"),
            llmFuturesIntervalInput: $("llmFuturesIntervalInput"),
            llmFuturesMaxPositionPctInput: $("llmFuturesMaxPositionPctInput"),
            llmFuturesMaxLeverageInput: $("llmFuturesMaxLeverageInput"),
            llmFuturesAutoLeverageInput: $("llmFuturesAutoLeverageInput"),
            llmFuturesMaxNotionalInput: $("llmFuturesMaxNotionalInput"),
            llmFuturesMaxMarginInput: $("llmFuturesMaxMarginInput"),
            llmFuturesMinConfidenceInput: $("llmFuturesMinConfidenceInput"),
            llmFuturesAutoSizeInput: $("llmFuturesAutoSizeInput"),
            llmFuturesTradingAgentsInput: $("llmFuturesTradingAgentsInput"),
            llmFuturesFiveAlignInput: $("llmFuturesFiveAlignInput"),
            llmFuturesStopReversalInput: $("llmFuturesStopReversalInput"),
            llmFuturesStopOnLossInput: $("llmFuturesStopOnLossInput"),
            llmFuturesMaxLossPctInput: $("llmFuturesMaxLossPctInput"),
            llmFuturesTradePlanStrictInput: $("llmFuturesTradePlanStrictInput"),
            llmFuturesEnforcePlanStopInput: $("llmFuturesEnforcePlanStopInput"),
            llmFuturesEnforcePlanTargetsInput: $("llmFuturesEnforcePlanTargetsInput"),
            llmFuturesStatus: $("llmFuturesStatus"),
            llmFuturesResults: $("llmFuturesResults"),
            liveSummaryCards: $("liveSummaryCards"),
            livePnlChart: $("livePnlChart"),
            livePnlHint: $("livePnlHint"),
            liveOpenPositions: $("liveOpenPositions"),
            liveTradeTable: $("liveTradeTable"),
            loadSpotAccountBtn: $("loadSpotAccountBtn"),
            loadFuturesAccountBtn: $("loadFuturesAccountBtn"),
            accountSnapshot: $("accountSnapshot"),
            loadEarnBtn: $("loadEarnBtn"),
            earnSnapshot: $("earnSnapshot"),
            submitSpotOrderBtn: $("submitSpotOrderBtn"),
            spotSymbolInput: $("spotSymbolInput"),
            spotSideSelect: $("spotSideSelect"),
            spotUsdInput: $("spotUsdInput"),
            spotMaxUsdInput: $("spotMaxUsdInput"),
            spotConfirmInput: $("spotConfirmInput"),
            spotOrderResult: $("spotOrderResult"),
            submitFuturesTestBtn: $("submitFuturesTestBtn"),
            submitFuturesBtn: $("submitFuturesBtn"),
            submitFuturesOrderBtn: $("submitFuturesOrderBtn"),
            submitTransferBtn: $("submitTransferBtn"),
            futuresAccountSelect: $("futuresAccountSelect"),
            transferAmountInput: $("transferAmountInput"),
            transferMaxAmountInput: $("transferMaxAmountInput"),
            transferConfirmInput: $("transferConfirmInput"),
            transferResult: $("transferResult"),
            futuresSymbolInput: $("futuresSymbolInput"),
            futuresSideSelect: $("futuresSideSelect"),
            futuresContractsInput: $("futuresContractsInput"),
            futuresLeverageInput: $("futuresLeverageInput"),
            futuresMarginModeSelect: $("futuresMarginModeSelect"),
            futuresPositionModeSelect: $("futuresPositionModeSelect"),
            futuresReduceOnlyInput: $("futuresReduceOnlyInput"),
            futuresMaxNotionalInput: $("futuresMaxNotionalInput"),
            futuresMaxMarginInput: $("futuresMaxMarginInput"),
            futuresConfirmInput: $("futuresConfirmInput"),
            futuresResult: $("futuresResult"),
        };
        this._liveChart = null;
        this._lastLiveSummaryData = null;
        this._liveResizeObserver = null;
        this._liveAutomationTimer = null;
        this._positionAlertsTimer = null;
        this._applyingArenaPreset = false;
    }

    async init() {
        this.bindEvents();
        document.addEventListener("dashboard-theme-change", () => {
            if (this._lastLiveSummaryData) this.renderLivePnlChart(this._lastLiveSummaryData);
        });
        this.initAgentArenaPresets();
        await Promise.all([
            this.loadLiveSummary(),
            this.loadKucoinAccounts(),
            this.loadLiveAutomationStatus(),
            this.loadVsContext(),
            this.loadPositionAlerts(),
        ]);
        this._positionAlertsTimer = setInterval(() => this.loadPositionAlerts(), 45000);
    }

    bindEvents() {
        const el = this.elements;
        el.refreshLiveBtn?.addEventListener("click", () => {
            this.loadLiveSummary();
            this.loadVsContext();
        });
        el.refreshVsContextBtn?.addEventListener("click", () => {
            this.loadVsContext();
            this.loadPositionAlerts();
        });
        el.refreshPositionAlertsBtn?.addEventListener("click", () => this.loadPositionAlerts());
        el.llmFuturesSymbolsInput?.addEventListener("change", () => {
            this.loadVsContext();
            this.loadPositionAlerts();
        });
        el.futuresAccountSelect?.addEventListener("change", () => this.loadPositionAlerts());
        el.startLiveAutomationBtn?.addEventListener("click", () => this.startLiveAutomation());
        el.stopLiveAutomationBtn?.addEventListener("click", () => this.stopLiveAutomation());
        el.liveAutomationStatusBtn?.addEventListener("click", () => this.loadLiveAutomationStatus());
        el.loadSpotAccountBtn?.addEventListener("click", () => this.loadAccount("spot"));
        el.loadFuturesAccountBtn?.addEventListener("click", () => this.loadAccount("futures"));
        el.futuresAccountSelect?.addEventListener("change", () => this.saveFuturesAccountSelection());
        el.loadEarnBtn?.addEventListener("click", () => this.loadEarn());
        el.submitSpotOrderBtn?.addEventListener("click", () => this.submitSpotOrder());
        el.submitTransferBtn?.addEventListener("click", () => this.submitTransferToFutures());
        el.submitFuturesTestBtn?.addEventListener("click", () => this.submitFuturesTestOrder());
        el.submitFuturesOrderBtn?.addEventListener("click", () => this.submitFuturesOrder());
        el.submitFuturesBtn?.addEventListener("click", () => this.submitFuturesRoundtrip());
        el.analyzeLlmFuturesBtn?.addEventListener("click", () => this.runLlmFutures(false));
        el.runLlmFuturesBtn?.addEventListener("click", () => this.runLlmFutures(true));
        this.bindAgentArenaPresetEvents();
    }

    initAgentArenaPresets() {
        const preset = this.elements.agentArenaPresetSelect?.value || "hybrid_default";
        this.applyAgentArenaPreset(preset);
    }

    bindAgentArenaPresetEvents() {
        const el = this.elements;
        el.agentArenaPresetSelect?.addEventListener("change", () => this.onAgentArenaPresetChange());
        const onManualChange = () => {
            if (this._applyingArenaPreset) return;
            if (el.agentArenaPresetSelect) el.agentArenaPresetSelect.value = "custom";
            if (el.agentArenaAdvanced) el.agentArenaAdvanced.open = true;
            this.updateAgentArenaPresetSummary();
        };
        el.agentArenaAgentsSelect?.querySelectorAll("input[type='checkbox']").forEach(input => {
            input.addEventListener("change", onManualChange);
        });
        el.agentArenaActiveSelect?.querySelectorAll("input[type='checkbox']").forEach(input => {
            input.addEventListener("change", onManualChange);
        });
    }

    onAgentArenaPresetChange() {
        const presetId = this.elements.agentArenaPresetSelect?.value || "hybrid_default";
        this.applyAgentArenaPreset(presetId);
        if (this.elements.agentArenaAdvanced) {
            this.elements.agentArenaAdvanced.open = presetId === "custom";
        }
    }

    applyAgentArenaPreset(presetId) {
        const el = this.elements;
        const preset = ARENA_AGENT_PRESETS[presetId];
        this._applyingArenaPreset = true;
        try {
            if (preset) {
                this.syncCheckboxGroup(el.agentArenaAgentsSelect, preset.agents);
                this.syncCheckboxGroup(el.agentArenaActiveSelect, preset.executionAgents);
            }
            this.updateAgentArenaPresetSummary();
        } finally {
            this._applyingArenaPreset = false;
        }
    }

    getSelectedArenaAgents() {
        const el = this.elements;
        return Array.from(el.agentArenaAgentsSelect?.querySelectorAll("input[type='checkbox']:checked") || []).map(option => option.value);
    }

    getSelectedExecutionAgents() {
        const el = this.elements;
        return Array.from(el.agentArenaActiveSelect?.querySelectorAll("input[type='checkbox']:checked") || []).map(option => option.value);
    }

    formatAgentLabelList(agentIds) {
        if (!agentIds.length) return "无";
        return agentIds.map(id => ARENA_AGENT_LABELS[id] || id).join("、");
    }

    updateAgentArenaPresetSummary() {
        const el = this.elements;
        if (!el.agentArenaPresetSummary) return;
        const agents = this.getSelectedArenaAgents();
        const executionAgents = this.getSelectedExecutionAgents();
        el.agentArenaPresetSummary.textContent = `共识：${this.formatAgentLabelList(agents)} · 执行：${this.formatAgentLabelList(executionAgents)}`;
    }

    detectAgentArenaPreset(agents, executionAgents) {
        const agentKey = [...agents].sort().join(",");
        const execKey = [...executionAgents].sort().join(",");
        for (const [presetId, preset] of Object.entries(ARENA_AGENT_PRESETS)) {
            const pAgents = [...preset.agents].sort().join(",");
            const pExec = [...preset.executionAgents].sort().join(",");
            if (pAgents === agentKey && pExec === execKey) return presetId;
        }
        return "custom";
    }

    liveAutomationPayload(execute = true) {
        const el = this.elements;
        const pipeline = el.liveAutomationPipelineSelect?.value || "hybrid";
        return {
            pipeline,
            ...this.llmFuturesPayload(execute),
            ...this.agentArenaPayload(),
        };
    }

    /** 主开关：是否提交真实合约单（无需用户输入 CONFIRM） */
    isAutoLiveEnabled() {
        return !!this.elements.llmFuturesAutoLiveInput?.checked;
    }

    syncAutoLiveControls(cfg) {
        const el = this.elements;
        if (!el.llmFuturesAutoLiveInput || !cfg || !Object.keys(cfg).length) return;
        const pipeline = cfg.pipeline || el.liveAutomationPipelineSelect?.value || "hybrid";
        const machine = cfg.machine_auto !== false;
        const arenaLive = (cfg.arena || {}).live_enabled !== false;
        let on = machine;
        if (pipeline === "hybrid") on = on && arenaLive;
        el.llmFuturesAutoLiveInput.checked = on;
    }

    llmFuturesPayload(execute) {
        const el = this.elements;
        const autoLive = this.isAutoLiveEnabled();
        const allowLiveOrders = autoLive && execute;
        const maxPositionPct = Number(el.llmFuturesMaxPositionPctInput?.value || 10) / 100;
        const autoPositionSize = el.llmFuturesAutoSizeInput ? !!el.llmFuturesAutoSizeInput.checked : true;
        return {
            ...this.futuresAccountPayload(),
            symbols: el.llmFuturesSymbolsInput?.value || "BTC,ETH,HYPE",
            intervalSeconds: Number(el.llmFuturesIntervalInput?.value || 60),
            maxRounds: Number(el.agentArenaMaxRoundsInput?.value || 0),
            model: el.llmFuturesModelSelect?.value || "deepseek/deepseek-v4-pro",
            maxPositionPctPerSymbol: maxPositionPct,
            positionPctPerSymbol: maxPositionPct,
            autoPositionSize,
            maxLeverage: Number(el.llmFuturesMaxLeverageInput?.value || 10),
            autoLeverage: el.llmFuturesAutoLeverageInput ? !!el.llmFuturesAutoLeverageInput.checked : true,
            leverage: Number(el.llmFuturesMaxLeverageInput?.value || 10),
            maxNotionalUsd: Number(el.llmFuturesMaxNotionalInput?.value || 30),
            maxMarginUsd: Number(el.llmFuturesMaxMarginInput?.value || 15),
            minConfidence: Number(el.llmFuturesMinConfidenceInput?.value || 55),
            onlyReady: false,
            requireFiveSignalAlign: el.llmFuturesFiveAlignInput ? !!el.llmFuturesFiveAlignInput.checked : true,
            stopOnReversal: el.llmFuturesStopReversalInput ? !!el.llmFuturesStopReversalInput.checked : true,
            stopOnLoss: el.llmFuturesStopOnLossInput ? !!el.llmFuturesStopOnLossInput.checked : true,
            maxUnrealizedLossPct: Number(el.llmFuturesMaxLossPctInput?.value || 30),
            maxUnrealizedLossUsd: 0,
            tradePlanStrict: el.llmFuturesTradePlanStrictInput ? !!el.llmFuturesTradePlanStrictInput.checked : true,
            enforceTradePlanStop: el.llmFuturesEnforcePlanStopInput ? !!el.llmFuturesEnforcePlanStopInput.checked : true,
            enforceTradePlanTargets: el.llmFuturesEnforcePlanTargetsInput ? !!el.llmFuturesEnforcePlanTargetsInput.checked : false,
            useTradingAgents: !!el.llmFuturesTradingAgentsInput?.checked,
            autoLive,
            machineAuto: allowLiveOrders,
            confirmLive: allowLiveOrders ? "CONFIRM" : "",
            execute,
        };
    }

    formatTradePlanShort(plan) {
        if (!plan || !Object.keys(plan).length) return "-";
        const el = (k) => (plan[k] != null && plan[k] > 0 ? this.formatNumber(plan[k]) : "");
        const entry = el("entryLow") && el("entryHigh") ? `${el("entryLow")}~${el("entryHigh")}` : "";
        const stop = el("stop") ? `SL ${el("stop")}` : "";
        const tp = el("target1") ? `TP ${el("target1")}` : "";
        return [entry, stop, tp].filter(Boolean).join(" · ") || "-";
    }

    formatVsInsightShort(vs) {
        if (!vs || !vs.available) return "-";
        const hits = vs.signalHits || {};
        const parts = [];
        if (hits.risk) parts.push("风险榜");
        if (hits.chance) parts.push("机会榜");
        if (hits.funds) parts.push("异动");
        const regime = String(vs.marketRegimeLabel || "").replace(/^待确认$/, "方向未定");
        if (regime) parts.push(regime);
        // VS 列展示链上/榜单状态，与「自动实盘」无关
        return parts.length ? parts.join("/") : (vs.primaryAlert || "无榜单命中").slice(0, 40);
    }

    buildFiveSignalsList(row) {
        return DashboardUtils.buildFiveSignalsList(row);
    }

    formatFiveSignalsHtml(row) {
        return DashboardUtils.formatFiveSignalsHtml(row, { gate: true });
    }

    /** 入场门禁列（紧凑四步条） */
    formatGateCellHtml(row) {
        return DashboardUtils.formatEntryGateCellHtml(row);
    }

    formatGateDetailNote(row) {
        const align = row.fiveSignalAlignment || row.entryGateAlignment || {};
        const gateReason = DashboardUtils.sanitizeGateText(String(row.gateReason || "").trim());
        const alignReason = DashboardUtils.sanitizeGateText(String(align.reason || "").trim());
        if (gateReason && gateReason !== alignReason) {
            return gateReason.slice(0, 160);
        }
        const plan = row.tradePlan;
        if (plan && (plan.entryLow || plan.entryHigh)) {
            return `计划 ${this.formatNumber(plan.entryLow)}~${this.formatNumber(plan.entryHigh)}`;
        }
        return "-";
    }

    async loadVsContext() {
        const el = this.elements;
        const symbols = (el.llmFuturesSymbolsInput?.value || "BTC,ETH").trim();
        if (el.liveVsMarketBanner) {
            el.liveVsMarketBanner.textContent = "加载 ValueScan 追踪摘要...";
        }
        try {
            const resp = await fetch(
                `/api/dashboard/live/valuescan-context?symbols=${encodeURIComponent(symbols)}`
            );
            const data = await this.parseJsonResponse(resp);
            if (!data.ok) throw new Error(data.message || "VS 上下文加载失败");
            this.renderVsContext(data);
        } catch (err) {
            if (el.liveVsMarketBanner) {
                el.liveVsMarketBanner.innerHTML = `<span class="change-down">${this.escapeHtml(err.message)}</span>`;
            }
            if (el.liveVsSymbolCards) el.liveVsSymbolCards.innerHTML = "";
        }
    }

    renderVsSseStatus(worker) {
        const el = this.elements;
        if (!el.liveVsSseStatus || !worker) return;
        const mkt = worker.marketConnected ? '<span class="sse-on">大盘流已连接</span>' : '<span class="sse-off">大盘流未连接</span>';
        const sig = worker.signalConnected ? '<span class="sse-on">信号流已连接</span>' : '<span class="sse-off">信号流未连接</span>';
        const watch = worker.watchTokenCount != null ? `订阅 ${worker.watchTokenCount} 个代币` : "";
        const err = worker.lastError ? ` · ${this.escapeHtml(String(worker.lastError).slice(0, 80))}` : "";
        el.liveVsSseStatus.innerHTML = `${mkt} · ${sig} · ${this.escapeHtml(watch)}${err}`;
    }

    async loadPositionAlerts() {
        const el = this.elements;
        const symbols = (el.llmFuturesSymbolsInput?.value || "").trim();
        const accountId = el.futuresAccountSelect?.value || "";
        if (el.livePositionAlerts) {
            el.livePositionAlerts.innerHTML = "<div class='signal-loading'>匹配持仓与 ValueScan 信号...</div>";
        }
        try {
            const params = new URLSearchParams();
            if (accountId) params.set("accountId", accountId);
            if (symbols) params.set("symbols", symbols);
            const resp = await fetch(`/api/dashboard/live/position-vs-alerts?${params}`);
            const data = await this.parseJsonResponse(resp);
            if (!data.ok) throw new Error(data.message || "告警加载失败");
            this.renderPositionAlerts(data);
        } catch (err) {
            if (el.livePositionAlerts) {
                el.livePositionAlerts.innerHTML = `<div class="backtest-error">${this.escapeHtml(err.message)}</div>`;
            }
        }
    }

    renderPositionAlerts(data) {
        const el = this.elements;
        if (!el.livePositionAlerts) return;
        const alerts = data.alerts || [];
        const positions = data.positions || [];
        if (!positions.length) {
            el.livePositionAlerts.innerHTML = "<div class='backtest-no-trades'>当前无合约持仓；开仓后将自动匹配 ValueScan 风险/机会告警</div>";
            return;
        }
        if (!alerts.length) {
            el.livePositionAlerts.innerHTML = `<div class='backtest-no-trades'>${positions.length} 个持仓暂无 VS 高风险告警</div>`;
            return;
        }
        const actionLabels = {
            reduce_or_stop: "建议减仓/止损",
            trail_stop_or_add: "移动止盈或关注加仓",
            take_profit: "建议止盈",
            watch: "持续观察",
            limit_buy_near_support: "支撑位附近挂单",
        };
        let html = `<div class="live-alert-list">`;
        alerts.forEach((a) => {
            const sev = a.severity || "medium";
            const side = a.positionSide ? ` · ${a.positionSide}` : "";
            const pnl = a.unrealizedPnlPct != null ? ` · 浮盈${Number(a.unrealizedPnlPct).toFixed(2)}%` : "";
            const act = actionLabels[a.suggestedAction] || a.suggestedAction || "";
            html += `<article class="live-alert-item severity-${this.escapeHtml(sev)}">`;
            html += `<div class="live-alert-title">${this.escapeHtml(a.symbol)}${this.escapeHtml(side)} — ${this.escapeHtml(a.title || "")}</div>`;
            html += `<div>${this.escapeHtml(a.detail || "")}</div>`;
            html += `<div class="live-alert-meta">${this.escapeHtml(act)}${this.escapeHtml(pnl)} · ${this.escapeHtml(a.vsSource || "")}</div>`;
            html += `</article>`;
        });
        html += `</div>`;
        el.livePositionAlerts.innerHTML = html;
    }

    renderVsContext(data) {
        const el = this.elements;
        const regime = data.marketRegimeLabel || "待确认";
        const regimeCls = data.marketRegime === "bullish" ? "change-up"
            : data.marketRegime === "bearish" ? "change-down" : "";
        if (data.sseWorker) this.renderVsSseStatus(data.sseWorker);
        if (el.liveVsMarketBanner) {
            el.liveVsMarketBanner.innerHTML =
                `<span class="live-vs-regime ${regimeCls}">BTC/ETH 大盘 · ${this.escapeHtml(regime)}</span>` +
                `<span>常驻 SSE 推送 + LLM 入场门禁；下方为监控币追踪与持仓守护告警。</span>`;
        }
        if (!el.liveVsSymbolCards) return;
        const symbols = data.symbols || {};
        const keys = Object.keys(symbols);
        if (!keys.length) {
            el.liveVsSymbolCards.innerHTML = "<div class='backtest-no-trades'>暂无 ValueScan 数据</div>";
            return;
        }
        let html = "";
        keys.forEach((sym) => {
            const d = symbols[sym] || {};
            const bias = d.actionBias || "neutral";
            const cardCls = bias === "risk_off" ? "risk-off" : bias === "bullish" ? "bullish" : "";
            const plan = d.suggestedPlan || {};
            const planText = this.formatTradePlanShort(plan);
            const alerts = (d.alerts || []).slice(0, 2).map(a => this.escapeHtml(a)).join("<br>");
            html += `<article class="live-vs-symbol-card ${cardCls}"><h3>${this.escapeHtml(sym)}</h3>`;
            html += `<div class="live-vs-alert">${alerts || this.escapeHtml(d.primaryAlert || "-")}</div>`;
            html += `<div class="live-vs-plan">${this.escapeHtml(planText)}</div></article>`;
        });
        el.liveVsSymbolCards.innerHTML = html;
    }

    renderLlmFuturesResults(data) {
        const el = this.elements;
        const results = data.results || [];
        if (el.llmFuturesStatus) {
            const closed = data.stopped || 0;
            const rev = data.signalExit || 0;
            const loss = data.lossCut || 0;
            el.llmFuturesStatus.textContent = `完成：开仓 ${data.opened || data.executed || 0} · 平仓 ${closed}（反转 ${rev} · 浮亏 ${loss}） · 跳过 ${data.skipped || 0} · 失败 ${data.failed || 0}`;
        }
        if (!el.llmFuturesResults) return;
        if (!results.length) {
            el.llmFuturesResults.innerHTML = "<div class='backtest-no-trades'>无结果</div>";
            return;
        }
        let html = `<div class="bt-trades-header">LLM 信号合约结果</div><div class="bt-trades-table"><div class="bt-trades-head live-agent-head live-agent-head--wide"><span>币种</span><span>信号</span><span>入场门禁</span><span>交易计划</span><span>VS</span><span>动作</span><span>状态</span><span>说明</span></div>`;
        results.forEach((row) => {
            const dims = row.fiveSignalAlignment?.dimensions || {};
            const dimText = Object.entries(dims).map(([name, direction]) => `${name}:${direction}`).join(" ");
            const lev = row.leverage != null ? `${row.leverage}x` : "-";
            const posPct = row.positionPct != null ? `${(Number(row.positionPct) * 100).toFixed(1)}%` : "-";
            const actionClass = row.side === "buy" ? "signal-buy" : row.side === "sell" ? "signal-sell" : "";
            const planText = this.formatTradePlanShort(row.tradePlan);
            const vsText = this.formatVsInsightShort(row.valuescanInsights);
            html += `<div class="bt-trades-row live-agent-row live-agent-row--wide"><span>${this.escapeHtml(row.symbol || "-")}</span><span>${this.escapeHtml(row.signal || "-")} · ${this.escapeHtml(lev)} · ${this.escapeHtml(posPct)}</span><span>${this.escapeHtml(dimText || "-")}</span><span>${this.escapeHtml(planText)}</span><span>${this.escapeHtml(vsText || "-")}</span><span class="${actionClass}">${this.escapeHtml(row.action || row.side || "-")}</span><span>${this.escapeHtml(row.status || "-")}</span><span>${this.escapeHtml((row.reason || row.summary || row.planReason || "-").slice(0, 200))}</span></div>`;
        });
        el.llmFuturesResults.innerHTML = html + "</div>";
    }

    async runLlmFutures(execute) {
        const el = this.elements;
        if (execute && !this.isAutoLiveEnabled()) {
            if (el.llmFuturesStatus) {
                el.llmFuturesStatus.innerHTML = "<div class=\"backtest-error\">「单次执行」需开启「自动实盘」才会真实下单；请勾选或改用「仅分析」。</div>";
            }
            return;
        }
        const button = execute ? el.runLlmFuturesBtn : el.analyzeLlmFuturesBtn;
        const pipeline = el.liveAutomationPipelineSelect?.value || "hybrid";
        const loadingText = execute
            ? `正在执行 (${pipeline})...`
            : `正在分析 (${pipeline})...`;
        if (el.llmFuturesStatus) el.llmFuturesStatus.textContent = loadingText;
        if (el.llmFuturesResults) el.llmFuturesResults.innerHTML = `<div class="signal-loading">${this.escapeHtml(loadingText)}</div>`;
        if (button) button.disabled = true;
        try {
            const url = pipeline === "llm_futures"
                ? "/api/dashboard/live/llm-futures-run"
                : "/api/dashboard/live/automation/run";
            const resp = await fetch(url, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(this.liveAutomationPayload(execute)),
            });
            const data = await this.parseJsonResponse(resp);
            if (!data.ok) throw new Error(data.message || "实盘自动化失败");
            this.renderLiveAutomationRound(data);
            if (execute) await this.loadAccount("futures");
        } catch (err) {
            if (el.llmFuturesStatus) el.llmFuturesStatus.innerHTML = `<div class="backtest-error">${this.escapeHtml(err.message)}</div>`;
            if (el.llmFuturesResults) el.llmFuturesResults.innerHTML = `<div class="backtest-error">${this.escapeHtml(err.message)}</div>`;
        } finally {
            if (button) button.disabled = false;
        }
    }

    renderLiveAutomationRound(data) {
        const pipeline = data.pipeline || "llm_futures";
        if (data.llmGate?.length) {
            this.renderLlmGateResults(data.llmGate, data.arenaApprovedSymbols);
        }
        if (data.arena) {
            this.renderAgentArenaSignals(data.arena.signals || []);
        }
        if (data.llmFutures) {
            this.renderLlmFuturesResults(data.llmFutures);
            return;
        }
        if (pipeline === "llm_futures" && !data.llmFutures) {
            return;
        }
    }

    renderLlmGateResults(rows, arenaApprovedSymbols) {
        const el = this.elements;
        if (!el.llmFuturesResults) return;
        if (!rows.length) {
            el.llmFuturesResults.innerHTML = "<div class='backtest-no-trades'>无门禁结果</div>";
            return;
        }
        const approved = new Set((arenaApprovedSymbols || []).map(s => String(s).toUpperCase()));
        const hasArenaFilter = arenaApprovedSymbols != null;
        const gatedWithSide = rows.filter((r) => r.gateSide);
        const arenaBlocked =
            hasArenaFilter && approved.size === 0 && gatedWithSide.length > 0;
        let html = `<div class="bt-trades-header">入场门禁${hasArenaFilter ? " · Arena 参考 " + approved.size + " 币" : ""}</div>`;
        if (arenaBlocked) {
            html += `<div class="backtest-error" style="margin:8px 0">门禁 ${gatedWithSide.length} 币已通过，但 Arena 共识为 0 — 混合管线不会下单。technical_signal 常为 WEAK_SHORT + exec=hold；确认 hybridArenaMatchMode=direction 或改用 llm_futures。</div>`;
        }
        html += `<div class="bt-trades-table"><div class="bt-trades-head live-agent-head live-agent-head--wide"><span>币种</span><span>信号</span><span>门禁</span><span>交易计划</span><span>VS</span><span>Arena</span><span>置信度</span><span>说明</span></div>`;
        rows.forEach((row) => {
            const sym = String(row.symbol || "").toUpperCase();
            let arenaTag = "-";
            if (hasArenaFilter) {
                if (!row.gateSide) arenaTag = "门禁未过";
                else arenaTag = approved.has(sym) ? "共识通过" : "未共识";
            }
            const q = row.quantFactors;
            const quantHint = q && q.aggregateScore != null
                ? ` · Q${Number(q.aggregateScore) >= 0 ? "+" : ""}${Number(q.aggregateScore).toFixed(2)}`
                : "";
            const planText = this.formatTradePlanShort(row.tradePlan);
            const vsText = this.formatVsInsightShort(row.valuescanInsights);
            const gateHtml = this.formatGateCellHtml(row);
            const detailNote = this.formatGateDetailNote(row);
            const confPct = this.formatPercent(row.confidence, 1);
            html += `<div class="bt-trades-row live-agent-row live-agent-row--wide"><span>${this.escapeHtml(row.symbol || "-")}</span><span>${this.escapeHtml(row.signal || "-")}${this.escapeHtml(quantHint)}</span><span class="live-gate-col">${gateHtml}</span><span>${this.escapeHtml(planText)}</span><span>${this.escapeHtml(vsText || "-")}</span><span>${this.escapeHtml(arenaTag)}</span><span>${confPct}%</span><span>${this.escapeHtml(detailNote)}</span></div>`;
        });
        el.llmFuturesResults.innerHTML = html + "</div>";
    }

    setLiveAutomationRunningUI(running, pipeline = "") {
        const el = this.elements;
        const badge = el.liveAutomationRunningBadge;
        if (badge) {
            badge.hidden = false;
            badge.classList.toggle("live-runner-badge--running", running);
            badge.textContent = running
                ? `定时任务运行中${pipeline ? ` · ${pipeline}` : ""}`
                : "定时任务未启动";
        }
        if (el.startLiveAutomationBtn) el.startLiveAutomationBtn.disabled = !!running;
        if (el.stopLiveAutomationBtn) el.stopLiveAutomationBtn.disabled = !running;
        if (el.llmFuturesStatus) {
            el.llmFuturesStatus.classList.toggle("is-running", !!running);
        }
    }

    async startLiveAutomation() {
        const el = this.elements;
        if (!this.isAutoLiveEnabled()) {
            if (el.llmFuturesStatus) {
                el.llmFuturesStatus.innerHTML = "<div class=\"backtest-error\">请先勾选「自动实盘」再启动定时任务；仅分析请用「仅分析」按钮。</div>";
            }
            return;
        }
        if (el.llmFuturesStatus) el.llmFuturesStatus.textContent = "正在启动实盘自动化...";
        if (el.startLiveAutomationBtn) el.startLiveAutomationBtn.disabled = true;
        try {
            const resp = await fetch("/api/dashboard/live/automation/start", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(this.liveAutomationPayload(true)),
            });
            const data = await this.parseJsonResponse(resp);
            if (!data.ok) throw new Error(data.message || "启动失败");
            this.renderLiveAutomationStatus(data);
        } catch (err) {
            if (el.llmFuturesStatus) {
                el.llmFuturesStatus.classList.remove("is-running");
                el.llmFuturesStatus.innerHTML = `<div class="backtest-error">${this.escapeHtml(err.message)}</div>`;
            }
            this.setLiveAutomationRunningUI(false);
        }
    }

    async stopLiveAutomation() {
        const el = this.elements;
        if (el.stopLiveAutomationBtn) el.stopLiveAutomationBtn.disabled = true;
        try {
            const resp = await fetch("/api/dashboard/live/automation/stop", { method: "POST" });
            const data = await this.parseJsonResponse(resp);
            if (!data.ok) throw new Error(data.message || "停止失败");
            this.renderLiveAutomationStatus(data);
        } catch (err) {
            if (el.llmFuturesStatus) el.llmFuturesStatus.innerHTML = `<div class="backtest-error">${this.escapeHtml(err.message)}</div>`;
        } finally {
            if (el.stopLiveAutomationBtn) el.stopLiveAutomationBtn.disabled = false;
        }
    }

    async loadLiveAutomationStatus() {
        const el = this.elements;
        try {
            const resp = await fetch("/api/dashboard/live/automation/status");
            const data = await this.parseJsonResponse(resp);
            if (!data.ok) throw new Error(data.message || "状态读取失败");
            this.renderLiveAutomationStatus(data);
        } catch (err) {
            if (el.llmFuturesStatus) {
                el.llmFuturesStatus.classList.remove("is-running");
                el.llmFuturesStatus.innerHTML = `<div class="backtest-error">${this.escapeHtml(err.message)}</div>`;
            }
        }
    }

    formatRoundProgress(data) {
        const completed = Number(data.rounds || 0);
        const current = Number(data.current_round || 0);
        const roundStatus = String(data.round_status || "");
        if (roundStatus === "running" && current > 0) {
            const elapsed = this.formatRoundElapsed(data.last_started_at);
            const elapsedSuffix = elapsed ? ` · 已耗时 ${elapsed}` : "";
            return `已完成 ${completed} · <span class="change-up">分析中 第 ${current} 轮${elapsedSuffix}</span>`;
        }
        return `轮次 ${completed}`;
    }

    formatRoundElapsed(startedAt) {
        if (!startedAt) return "";
        const started = new Date(startedAt);
        if (!Number.isFinite(started.getTime())) return "";
        const seconds = Math.max(0, Math.floor((Date.now() - started.getTime()) / 1000));
        if (seconds < 60) return `${seconds}s`;
        const minutes = Math.floor(seconds / 60);
        const remain = seconds % 60;
        return remain ? `${minutes}m ${remain}s` : `${minutes}m`;
    }

    renderLiveAutomationStatus(data) {
        const el = this.elements;
        const cfg = data.config || {};
        const latest = data.latest || {};
        const running = !!data.running;
        const roundProgress = this.formatRoundProgress(data);
        const analyzing = String(data.round_status || "") === "running";
        if (this._liveAutomationTimer) {
            clearInterval(this._liveAutomationTimer);
            this._liveAutomationTimer = null;
        }
        if (running) {
            this._liveAutomationTimer = setInterval(() => this.loadLiveAutomationStatus(), 5000);
        }
        const pipeline = cfg.pipeline || latest.pipeline || "hybrid";
        this.setLiveAutomationRunningUI(running, pipeline);
        if (el.liveAutomationPipelineSelect && cfg.pipeline) {
            el.liveAutomationPipelineSelect.value = cfg.pipeline;
        }
        if (el.llmFuturesStatus) {
            const symbols = Array.isArray(cfg.symbols) ? cfg.symbols.join(",") : (cfg.symbols || "-");
            const model = cfg.model || cfg.arena?.model || "-";
            const arena = cfg.arena || {};
            const executionAgents = (arena.execution_agents || []).join(",") || "-";
            const autoLive = cfg.machine_auto !== false
                && (pipeline !== "hybrid" || arena.live_enabled !== false);
            const execHint = autoLive ? "真实下单开" : "仅分析";
            const runningLabel = running ? '<span class="change-up">● 运行中</span>' : '<span class="change-down">● 已停止</span>';
            el.llmFuturesStatus.innerHTML = `${runningLabel} · 管线 ${this.escapeHtml(pipeline)} · ${this.escapeHtml(symbols)} · 模型 ${this.escapeHtml(this.formatModelName(model))} · ${this.escapeHtml(execHint)} · 执行 Agent ${this.escapeHtml(executionAgents)} · 间隔 ${this.escapeHtml(String(cfg.interval_seconds || "-"))}s · ${roundProgress}${data.last_error ? ` · 错误 ${this.escapeHtml(data.last_error)}` : ""}`;
        }
        const latencyLabel = analyzing ? "上轮耗时" : "最近耗时";
        const latencySub = analyzing
            ? `本轮 ${this.formatRoundElapsed(data.last_started_at) || "分析中..."}`
            : "ms";
        const latencyValue = this.formatNumber(latest.latency_ms || 0);
        if (el.agentArenaCards) {
            el.agentArenaCards.innerHTML = `
                <div class="bt-metric-card"><div class="bt-metric-label">状态</div><div class="bt-metric-value ${running ? "change-up" : ""}">${analyzing ? "分析中" : (running ? "运行中" : "停止")}</div><div class="bt-metric-sub">${analyzing ? `第 ${data.current_round || "-"} 轮 LLM` : "统一后台"}</div></div>
                <div class="bt-metric-card"><div class="bt-metric-label">管线</div><div class="bt-metric-value">${this.escapeHtml(pipeline)}</div><div class="bt-metric-sub">${roundProgress}</div></div>
                <div class="bt-metric-card"><div class="bt-metric-label">${latencyLabel}</div><div class="bt-metric-value ${analyzing ? "change-up" : ""}">${latencyValue}</div><div class="bt-metric-sub">${this.escapeHtml(latencySub)}</div></div>
                <div class="bt-metric-card"><div class="bt-metric-label">错误</div><div class="bt-metric-value ${data.last_error ? "change-down" : ""}">${data.last_error ? "有" : "无"}</div><div class="bt-metric-sub">${this.escapeHtml(data.last_error || "-").slice(0, 80)}</div></div>`;
        }
        const topModel = cfg.model || cfg.arena?.model || cfg.arena?.deepseek_model;
        if (el.llmFuturesModelSelect && topModel) el.llmFuturesModelSelect.value = topModel;
        if (el.llmFuturesSymbolsInput && cfg.symbols) {
            el.llmFuturesSymbolsInput.value = Array.isArray(cfg.symbols) ? cfg.symbols.join(",") : cfg.symbols;
        }
        if (el.llmFuturesIntervalInput && cfg.interval_seconds != null) {
            el.llmFuturesIntervalInput.value = cfg.interval_seconds;
        }
        if (el.agentArenaMaxRoundsInput && cfg.max_rounds != null) {
            el.agentArenaMaxRoundsInput.value = cfg.max_rounds;
        }
        if (el.llmFuturesMaxLeverageInput) {
            const cap = cfg.max_leverage ?? cfg.maxLeverage ?? cfg.leverage;
            if (cap != null) el.llmFuturesMaxLeverageInput.value = cap;
        }
        if (el.llmFuturesAutoLeverageInput && cfg.auto_leverage != null) {
            el.llmFuturesAutoLeverageInput.checked = !!cfg.auto_leverage;
        } else if (el.llmFuturesAutoLeverageInput && cfg.autoLeverage != null) {
            el.llmFuturesAutoLeverageInput.checked = !!cfg.autoLeverage;
        }
        if (el.llmFuturesMaxPositionPctInput) {
            const pct = cfg.max_position_pct_per_symbol ?? cfg.maxPositionPctPerSymbol ?? cfg.position_pct_per_symbol;
            if (pct != null) {
                const n = Number(pct);
                el.llmFuturesMaxPositionPctInput.value = n <= 1 ? n * 100 : n;
            }
        }
        if (el.llmFuturesAutoSizeInput && cfg.auto_position_size != null) {
            el.llmFuturesAutoSizeInput.checked = !!cfg.auto_position_size;
        } else if (el.llmFuturesAutoSizeInput && cfg.autoPositionSize != null) {
            el.llmFuturesAutoSizeInput.checked = !!cfg.autoPositionSize;
        }
        const tps = cfg.trade_plan_strict ?? cfg.tradePlanStrict;
        if (el.llmFuturesTradePlanStrictInput && tps != null) {
            el.llmFuturesTradePlanStrictInput.checked = !!tps;
        }
        const eps = cfg.enforce_trade_plan_stop ?? cfg.enforceTradePlanStop;
        if (el.llmFuturesEnforcePlanStopInput && eps != null) {
            el.llmFuturesEnforcePlanStopInput.checked = !!eps;
        }
        const ept = cfg.enforce_trade_plan_targets ?? cfg.enforceTradePlanTargets;
        if (el.llmFuturesEnforcePlanTargetsInput && ept != null) {
            el.llmFuturesEnforcePlanTargetsInput.checked = !!ept;
        }
        this.syncAutoLiveControls(cfg);
        if (cfg.arena) this.syncAgentArenaControls(cfg.arena);
        if (latest.llmGate) {
            this.renderLlmGateResults(latest.llmGate, latest.arenaApprovedSymbols);
        }
        if (
            pipeline === "hybrid"
            && latest.gatedSymbols?.length
            && Array.isArray(latest.arenaApprovedSymbols)
            && latest.arenaApprovedSymbols.length === 0
            && el.llmFuturesStatus
        ) {
            const note =
                latest.message
                || "混合管线：入场门禁已通过但 Arena 未共识，本轮未下单";
            const prev = el.llmFuturesStatus.innerHTML || "";
            if (!prev.includes("Arena 未共识") && !prev.includes("Arena 共识为 0")) {
                el.llmFuturesStatus.innerHTML =
                    `${prev}<div class="backtest-error" style="margin-top:6px">${this.escapeHtml(note)}</div>`;
            }
        }
        if (latest.arena) {
            this.renderAgentArenaSignals(latest.arena.signals || []);
        }
        if (latest.llmFutures) {
            this.renderLlmFuturesResults(latest.llmFutures);
        } else if (latest.results) {
            this.renderLlmFuturesResults(latest);
        }
    }

    async loadLiveSummary() {
        const el = this.elements;
        if (el.liveSummaryCards) el.liveSummaryCards.innerHTML = "<div class='backtest-loading'>读取实盘成交日志...</div>";
        try {
            const resp = await fetch("/api/dashboard/live/summary?days=90");
            const data = await this.parseJsonResponse(resp);
            if (!data.ok) throw new Error(data.message || "读取失败");
            this._lastLiveSummaryData = data;
            this.renderLiveSummary(data);
            this.renderLivePnlChart(data);
            this.renderLiveTrades(data.recent_trades || []);
        } catch (err) {
            if (el.liveSummaryCards) el.liveSummaryCards.innerHTML = `<div class="backtest-error">实盘统计读取失败: ${this.escapeHtml(err.message)}</div>`;
        }
    }

    agentArenaPayload() {
        const agents = this.getSelectedArenaAgents();
        const executionAgents = this.getSelectedExecutionAgents();
        const el = this.elements;
        return {
            symbols: el.llmFuturesSymbolsInput?.value || "BTC",
            quote: "USDT",
            agents: agents.length ? agents : ["trend_hunter", "claude_agent", "dashboard_deepseek"],
            executionAgents,
            intervalSeconds: Number(el.llmFuturesIntervalInput?.value || 60),
            maxRounds: Number(el.agentArenaMaxRoundsInput?.value || 0),
            agentMode: "llm",
            live: this.isAutoLiveEnabled(),
            includeAccount: !!el.agentArenaAccountInput?.checked,
            includeRag: !!el.agentArenaRagInput?.checked,
            ragSize: 1,
            includeMicrostructure: !!el.agentArenaMicroInput?.checked,
            includeValuescanMessages: true,
            includeSignalEvidence: true,
            model: el.llmFuturesModelSelect?.value || "deepseek/deepseek-v4-pro",
        };
    }

    syncAgentArenaControls(cfg) {
        const el = this.elements;
        if (!cfg || !Object.keys(cfg).length) return;
        if (el.agentArenaMaxRoundsInput && cfg.max_rounds != null) el.agentArenaMaxRoundsInput.value = cfg.max_rounds;

        if (el.agentArenaAccountInput && cfg.include_account != null) el.agentArenaAccountInput.checked = !!cfg.include_account;
        if (el.agentArenaRagInput && cfg.include_rag != null) el.agentArenaRagInput.checked = !!cfg.include_rag;
        if (el.agentArenaMicroInput && cfg.include_microstructure != null) el.agentArenaMicroInput.checked = !!cfg.include_microstructure;
        const model = cfg.model || cfg.deepseek_model || cfg.default_model;
        if (el.llmFuturesModelSelect && model) el.llmFuturesModelSelect.value = model;
        const agents = cfg.agents || [];
        const executionAgents = cfg.execution_agents || [];
        this.syncCheckboxGroup(el.agentArenaAgentsSelect, agents);
        this.syncCheckboxGroup(el.agentArenaActiveSelect, executionAgents);
        const presetId = this.detectAgentArenaPreset(agents, executionAgents);
        if (el.agentArenaPresetSelect) el.agentArenaPresetSelect.value = presetId;
        if (el.agentArenaAdvanced) el.agentArenaAdvanced.open = presetId === "custom";
        this.updateAgentArenaPresetSummary();
    }

    syncCheckboxGroup(container, values) {
        if (!container || !Array.isArray(values)) return;
        const selected = new Set(values.map(value => String(value)));
        container.querySelectorAll("input[type='checkbox']").forEach(input => { input.checked = selected.has(input.value); });
    }

    renderAgentArenaSignals(signals) {
        const el = this.elements;
        if (!el.agentArenaSignals) return;
        if (!signals.length) {
            el.agentArenaSignals.innerHTML = "<div class='backtest-no-trades'>等待第一轮 Agent 信号</div>";
            return;
        }
        let html = `<div class="bt-trades-header">最近一轮 Agent 信号</div><div class="bt-trades-table"><div class="bt-trades-head live-agent-head"><span>Agent</span><span>币种</span><span>动作</span><span>方向</span><span>分数</span><span>置信度</span><span>理由</span><span>风险</span></div>`;
        signals.forEach(signal => {
            const action = signal.execution_action || signal.action || "hold";
            const actionClass = ["buy", "cover", "LONG"].includes(action) ? "change-up" : (["sell", "short", "SHORT"].includes(action) ? "change-down" : "");
            html += `<div class="bt-trades-row live-agent-row"><span>${this.escapeHtml(signal.agent_name || "-")}</span><span>${this.escapeHtml(signal.symbol || "-")}</span><span class="${actionClass}">${this.escapeHtml(action)}</span><span>${this.escapeHtml(signal.direction || "-")}</span><span>${this.formatNumber(signal.score || 0)}</span><span>${this.formatNumber((signal.confidence || 0) * 100)}%</span><span>${this.escapeHtml((signal.entry_reason || []).join("；") || "-").slice(0, 180)}</span><span>${this.escapeHtml((signal.risk_flags || []).join("；") || "-").slice(0, 140)}</span></div>`;
        });
        el.agentArenaSignals.innerHTML = html + "</div>";
    }

    renderLiveSummary(data) {
        const el = this.elements;
        const counts = data.status_counts || {};
        const filled = (counts.filled || 0) + (counts.closed || 0) + (counts.partially_filled || 0);
        const failed = (counts.failed || 0) + (counts.rejected || 0);
        const pnlClass = (data.realized_pnl_usd || 0) >= 0 ? "change-up" : "change-down";
        if (el.liveSummaryCards) {
            el.liveSummaryCards.innerHTML = `
                <div class="bt-metric-card"><div class="bt-metric-label">实盘记录</div><div class="bt-metric-value">${data.live_records || 0}</div><div class="bt-metric-sub">dry-run ${data.dry_run_records || 0}</div></div>
                <div class="bt-metric-card"><div class="bt-metric-label">已成交</div><div class="bt-metric-value change-up">${filled}</div><div class="bt-metric-sub">失败/拒绝 ${failed}</div></div>
                <div class="bt-metric-card"><div class="bt-metric-label">成交金额</div><div class="bt-metric-value">${this.formatNumber(data.filled_usd || 0)}</div><div class="bt-metric-sub">请求 ${this.formatNumber(data.requested_usd || 0)} USDT</div></div>
                <div class="bt-metric-card"><div class="bt-metric-label">已实现盈亏</div><div class="bt-metric-value ${pnlClass}">${(data.realized_pnl_usd || 0) >= 0 ? "+" : ""}${this.formatNumber(data.realized_pnl_usd || 0)}</div><div class="bt-metric-sub">FIFO 现货已平仓</div></div>
                <div class="bt-metric-card"><div class="bt-metric-label">收益率</div><div class="bt-metric-value ${pnlClass}">${this.formatNumber(data.performance?.realized_return_pct || 0)}%</div><div class="bt-metric-sub">日志资金基数 ${this.formatNumber(data.performance?.capital_base_usd || 0)} USDT</div></div>
                <div class="bt-metric-card"><div class="bt-metric-label">Sharpe</div><div class="bt-metric-value">${data.performance?.sharpe_ratio == null ? "-" : this.formatNumber(data.performance.sharpe_ratio)}</div><div class="bt-metric-sub">已平仓批次 ${data.performance?.closed_lots || 0}</div></div>
                <div class="bt-metric-card"><div class="bt-metric-label">最大回撤</div><div class="bt-metric-value change-down">-${this.formatNumber(data.performance?.max_drawdown_pct || 0)}%</div><div class="bt-metric-sub">胜率 ${this.formatNumber(data.performance?.win_rate_pct || 0)}%</div></div>
                <div class="bt-metric-card"><div class="bt-metric-label">手续费</div><div class="bt-metric-value">${this.formatNumber(data.fee_total || 0)}</div><div class="bt-metric-sub">标的 ${this.escapeHtml((data.symbols || []).join(", ") || "-")}</div></div>`;
        }
        if (el.liveOpenPositions) {
            const positions = data.open_positions || [];
            const rows = positions.length ? positions.map(p => `<div class="live-position-row"><span>${this.escapeHtml(p.symbol)}</span><span>${this.formatNumber(p.qty)}</span><span>${this.formatNumber(p.cost_usd)} USDT</span><span>${this.formatNumber(p.avg_price)}</span></div>`).join("") : "<div class='live-empty'>暂无可由日志计算出的未平仓现货批次</div>";
            el.liveOpenPositions.innerHTML = `<div class="live-panel-title">日志内未平仓批次</div><div class="live-position-head"><span>标的</span><span>数量</span><span>成本</span><span>均价</span></div>${rows}<div class="live-note">${this.escapeHtml(data.pnl_note || "")}</div>`;
        }
    }

    renderLivePnlChart(data) {
        const el = this.elements;
        if (!el.livePnlChart) return;
        const curve = data.realized_curve || [];
        if (el.livePnlHint) el.livePnlHint.style.display = curve.length ? "none" : "";
        el.livePnlChart.innerHTML = "";
        if (typeof LightweightCharts === "undefined") {
            el.livePnlChart.innerHTML = "<div class='backtest-error'>图表库未加载</div>";
            return;
        }
        const chart = LightweightCharts.createChart(el.livePnlChart, this.chartOptions(el.livePnlChart, 260));
        const series = chart.addLineSeries({ color: "#00D4AA", lineWidth: 2, title: "已实现盈亏" });
        series.setData(curve.map(p => ({ time: p.time, value: Number(p.value || 0) })));
        chart.timeScale().fitContent();
        this._liveChart = chart;
        this.observeResize(el.livePnlChart, chart);
    }

    renderLiveTrades(trades) {
        const el = this.elements;
        if (!el.liveTradeTable) return;
        if (!trades.length) {
            el.liveTradeTable.innerHTML = "<div class='backtest-no-trades'>暂无实盘交易日志</div>";
            return;
        }
        const fmtTime = (value) => this.formatBeijingTime(value);
        let html = `<div class="bt-trades-header">最近交易 (${trades.length})</div><div class="bt-trades-table"><div class="bt-trades-head live-trades-head"><span>时间</span><span>来源</span><span>账户</span><span>标的</span><span>动作</span><span>状态</span><span>请求</span><span>成交</span><span>均价</span><span>订单</span></div>`;
        trades.forEach(t => {
            const statusClass = ["filled", "closed", "partially_filled"].includes(String(t.status).toLowerCase()) ? "change-up" : (String(t.status).includes("fail") || String(t.status).includes("reject") ? "change-down" : "");
            html += `<div class="bt-trades-row live-trades-row"><span>${fmtTime(t.timestamp)}</span><span>${this.escapeHtml(t.source || "-")}</span><span>${this.escapeHtml(t.account_id || "-")}</span><span>${this.escapeHtml(t.symbol || "-")}</span><span>${this.escapeHtml(t.action || "-")}</span><span class="${statusClass}">${this.escapeHtml(t.status || "-")}</span><span>${this.formatNumber(t.order_usd || 0)}</span><span>${this.formatNumber(t.filled_usd || 0)}</span><span>${this.formatNumber(t.filled_price || 0)}</span><span>${this.escapeHtml(t.order_id || t.error || t.reason || "-")}</span></div>`;
        });
        el.liveTradeTable.innerHTML = html + "</div>";
    }

    selectedFuturesAccountId() {
        const select = this.elements.futuresAccountSelect;
        const fallback = this._futuresAccountLockedId || "claude";
        const id = (select?.value || fallback).trim().toLowerCase() || fallback;
        this.saveFuturesAccountSelection(id);
        return id;
    }

    saveFuturesAccountSelection(accountId) {
        const id = (accountId || this.elements.futuresAccountSelect?.value || this._futuresAccountLockedId || "claude").trim().toLowerCase() || "claude";
        localStorage.setItem("liveFuturesAccountId", id);
    }

    futuresAccountPayload() {
        return { accountId: this.selectedFuturesAccountId() };
    }

    async loadKucoinAccounts() {
        const select = this.elements.futuresAccountSelect;
        if (!select) return;
        try {
            const resp = await fetch("/api/dashboard/live/kucoin-accounts?scope=futures");
            const data = await this.parseJsonResponse(resp);
            if (!data.ok || !Array.isArray(data.accounts) || !data.accounts.length) return;
            const defaultId = String(data.default_account_id || data.accounts[0].account_id || "claude").toLowerCase();
            this._futuresAccountLockedId = defaultId;
            localStorage.setItem("liveFuturesAccountId", defaultId);
            const locked = data.accounts.length === 1 || data.accounts.every((item) => item.locked);
            select.innerHTML = data.accounts.map((account) => {
                const id = String(account.account_id || defaultId).toLowerCase();
                const tail = account.api_key_tail ? ` · ****${account.api_key_tail}` : "";
                return `<option value="${this.escapeHtml(id)}" selected>${this.escapeHtml(id)}${this.escapeHtml(tail)}</option>`;
            }).join("");
            select.value = defaultId;
            select.disabled = locked;
            select.title = locked ? "合约实盘已锁定为个人账户" : "";
        } catch (_) {
            this._futuresAccountLockedId = "claude";
            select.value = "claude";
        }
    }

    async loadAccount(market) {
        const el = this.elements;
        if (el.accountSnapshot) el.accountSnapshot.textContent = `读取${market === "futures" ? "合约" : "现货"}账户中...`;
        const symbols = market === "futures" ? "KCS/USDT:USDT,BTC/USDT:USDT" : "KCS/USDT,BTC/USDT,ETH/USDT";
        const accountQuery = market === "futures"
            ? `&accountId=${encodeURIComponent(this.selectedFuturesAccountId())}`
            : "";
        try {
            const resp = await fetch(`/api/dashboard/live/account?market=${encodeURIComponent(market)}&symbols=${encodeURIComponent(symbols)}${accountQuery}`);
            const data = await this.parseJsonResponse(resp);
            if (!data.ok) throw new Error(data.message || "读取失败");
            const accounts = (data.accounts && data.accounts.length) ? data.accounts : [{ account_id: "default", account_profile: data.account_profile || {}, balance: data.balance || {}, positions: data.positions || [], open_order_count: data.open_order_count || 0 }];
            const sections = accounts.map(account => {
                const profile = account.account_profile || {};
                const assets = account.balance?.assets || [];
                const totalUsdt = account.total_usdt_value;
                const rows = assets.map(a => {
                    const assetLabel = a.account_type ? `${a.asset} (${a.account_type})` : a.asset;
                    const usdtVal = a.usdt_value != null ? this.formatNumber(a.usdt_value) : "-";
                    const pct = a.pct != null ? `${a.pct}%` : "-";
                    return `<div class="live-account-row"><span>${this.escapeHtml(assetLabel)}</span><span>${this.formatNumber(a.free)}</span><span>${this.formatNumber(a.total)}</span><span>${this.formatNumber(a.used)}</span><span>${usdtVal}</span><span>${pct}</span></div>`;
                }).join("") || "<div class='live-empty'>未读到非零资产</div>";
                const totalRow = totalUsdt != null ? `<div class="live-account-row live-account-total"><span>合计</span><span></span><span></span><span></span><span>${this.formatNumber(totalUsdt)}</span><span>100%</span></div>` : "";
                const positions = (account.positions || []).slice(0, 8).map(p => `<div class="live-json-line">${this.escapeHtml(JSON.stringify({ symbol: p.symbol, amount: p.amount || p.contracts, notional: p.notional, side: p.side }))}</div>`).join("");
                const profileText = `${account.account_id || profile.account_id || "default"} · API ****${profile.api_key_tail || "-"} · ${profile.execution_provider || "-"} · ${profile.sandbox ? "sandbox" : "live endpoint"}`;
                return `<div class="live-note">${this.escapeHtml(profileText)}</div><div class="live-account-head"><span>资产</span><span>可用</span><span>数量</span><span>占用</span><span>折合USDT</span><span>占比</span></div>${rows}${totalRow}<div class="live-note">Open orders: ${account.open_order_count || 0}</div>${positions}`;
            }).join("<div class='live-account-separator'></div>");
            el.accountSnapshot.innerHTML = sections;
        } catch (err) {
            if (el.accountSnapshot) el.accountSnapshot.innerHTML = `<div class="backtest-error">账户读取失败: ${this.escapeHtml(err.message)}</div>`;
        }
    }

    async loadEarn() {
        const el = this.elements;
        if (el.earnSnapshot) el.earnSnapshot.textContent = "读取 Earn 产品和持仓中...";
        try {
            const resp = await fetch("/api/dashboard/live/earn?currency=KCS");
            const data = await this.parseJsonResponse(resp);
            if (!data.ok) throw new Error(data.message || "读取失败");
            el.earnSnapshot.innerHTML = `<div class="live-note">${this.escapeHtml(data.write_note || "")}</div><pre>${this.escapeHtml(JSON.stringify({ holdings: data.holdings, savings: data.savings, kcs_staking: data.kcs_staking }, null, 2)).slice(0, 5000)}</pre>`;
        } catch (err) {
            if (el.earnSnapshot) el.earnSnapshot.innerHTML = `<div class="backtest-error">Earn 读取失败: ${this.escapeHtml(err.message)}</div>`;
        }
    }

    async submitSpotOrder() {
        const el = this.elements;
        const payload = {
            symbol: el.spotSymbolInput?.value || "KCS/USDT",
            side: el.spotSideSelect?.value || "sell",
            usd: Number(el.spotUsdInput?.value || 1),
            maxUsd: Number(el.spotMaxUsdInput?.value || 2),
            confirmLive: el.spotConfirmInput?.value || "",
        };
        await this.postJson("/api/dashboard/live/spot-order", payload, el.spotOrderResult, el.submitSpotOrderBtn, "提交现货订单中...");
        await this.loadLiveSummary();
    }

    async submitFuturesRoundtrip() {
        const el = this.elements;
        const payload = {
            ...this.futuresAccountPayload(),
            symbol: el.futuresSymbolInput?.value || "BTC/USDT:USDT",
            side: el.futuresSideSelect?.value || "buy",
            contracts: Number(el.futuresContractsInput?.value || 1),
            leverage: Number(el.futuresLeverageInput?.value || 10),
            marginMode: el.futuresMarginModeSelect?.value || "CROSS",
            positionMode: el.futuresPositionModeSelect?.value || "HEDGE",
            maxNotionalUsd: Number(el.futuresMaxNotionalInput?.value || 100),
            maxMarginUsd: Number(el.futuresMaxMarginInput?.value || 10),
            confirmLive: el.futuresConfirmInput?.value || "",
        };
        await this.postJson("/api/dashboard/live/futures-roundtrip", payload, el.futuresResult, el.submitFuturesBtn, "提交合约回环中...");
        await this.loadLiveSummary();
    }

    async submitFuturesOrder() {
        const el = this.elements;
        const payload = {
            ...this.futuresAccountPayload(),
            symbol: el.futuresSymbolInput?.value || "BTC/USDT:USDT",
            side: el.futuresSideSelect?.value || "buy",
            contracts: Number(el.futuresContractsInput?.value || 1),
            leverage: Number(el.futuresLeverageInput?.value || 10),
            marginMode: el.futuresMarginModeSelect?.value || "CROSS",
            positionMode: el.futuresPositionModeSelect?.value || "HEDGE",
            reduceOnly: String(el.futuresReduceOnlyInput?.value || "false") === "true",
            maxNotionalUsd: Number(el.futuresMaxNotionalInput?.value || 100),
            maxMarginUsd: Number(el.futuresMaxMarginInput?.value || 10),
            confirmLive: el.futuresConfirmInput?.value || "",
        };
        await this.postJson("/api/dashboard/live/futures-order", payload, el.futuresResult, el.submitFuturesOrderBtn, "提交合约订单中...");
        await this.loadLiveSummary();
    }

    async submitFuturesTestOrder() {
        const el = this.elements;
        const payload = {
            ...this.futuresAccountPayload(),
            symbol: el.futuresSymbolInput?.value || "BTC/USDT:USDT",
            side: el.futuresSideSelect?.value || "buy",
            contracts: Number(el.futuresContractsInput?.value || 1),
            leverage: Number(el.futuresLeverageInput?.value || 10),
            marginMode: el.futuresMarginModeSelect?.value || "CROSS",
            positionMode: el.futuresPositionModeSelect?.value || "HEDGE",
        };
        await this.postJson("/api/dashboard/live/futures-order-test", payload, el.futuresResult, el.submitFuturesTestBtn, "执行合约能力自检中...");
    }

    async submitTransferToFutures() {
        const el = this.elements;
        const payload = {
            ...this.futuresAccountPayload(),
            currency: "USDT",
            amount: Number(el.transferAmountInput?.value || 0),
            maxAmount: Number(el.transferMaxAmountInput?.value || 10),
            confirmLive: el.transferConfirmInput?.value || "",
        };
        await this.postJson("/api/dashboard/live/transfer-futures", payload, el.transferResult, el.submitTransferBtn, "划转 USDT 到合约账户中...");
        await this.loadAccount("futures");
    }

    async postJson(url, payload, outputEl, buttonEl, loadingText) {
        if (outputEl) outputEl.textContent = loadingText;
        if (buttonEl) buttonEl.disabled = true;
        try {
            const resp = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
            const data = await this.parseJsonResponse(resp);
            if (!data.ok) throw new Error(data.message || data.reason || "请求失败");
            if (outputEl) outputEl.innerHTML = `<pre>${this.escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
        } catch (err) {
            if (outputEl) outputEl.innerHTML = `<div class="backtest-error">${this.escapeHtml(err.message)}</div>`;
        } finally {
            if (buttonEl) buttonEl.disabled = false;
        }
    }

    chartOptions(container, height) {
        if (typeof DashboardTheme !== "undefined") {
            return DashboardTheme.chartOptions(container.clientWidth, height);
        }
        return ChartTheme.baseOptions(container.clientWidth, height);
    }

    observeResize(container, chart) {
        if (this._liveResizeObserver) this._liveResizeObserver.disconnect();
        this._liveResizeObserver = new ResizeObserver(() => {
            if (container.clientWidth > 0) chart.applyOptions({ width: container.clientWidth });
        });
        this._liveResizeObserver.observe(container);
    }

    async parseJsonResponse(resp) {
        const text = await resp.text();
        let data = {};
        try { data = text ? JSON.parse(text) : {}; } catch (_) { data = { ok: false, message: text || resp.statusText }; }
        if (!resp.ok && data.ok !== false) data.ok = false;
        return data;
    }

    escapeHtml(value) {
        return String(value == null ? "" : value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    formatModelName(model) {
        if (typeof DashboardUtils !== "undefined" && typeof DashboardUtils.formatModelName === "function") {
            return DashboardUtils.formatModelName(model);
        }
        const value = String(model || "");
        if (value.includes("deepseek-v4-flash")) return "DeepSeek V4 Flash";
        if (value.includes("deepseek-v4-pro")) return "DeepSeek V4 Pro";
        if (value.includes("deepseek-v4")) return "DeepSeek V4";
        if (value.includes("deepseek-chat")) return "DeepSeek Chat (V3)";
        if (value.includes("deepseek-reasoner")) return "DeepSeek Reasoner";
        if (value.includes("Qwen3.5-27B")) return "Qwen 3.5 27B";
        return value || "-";
    }

    formatNumber(value, digits = 4) {
        const num = Number(value || 0);
        if (!Number.isFinite(num)) return "0";
        if (Math.abs(num) >= 1000) return num.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
        if (Math.abs(num) >= 1) return num.toLocaleString("zh-CN", { maximumFractionDigits: digits });
        return num.toLocaleString("zh-CN", { maximumFractionDigits: 8 });
    }

    formatBeijingTime(value, includeSeconds = false) {
        if (!value) return "-";
        const date = value instanceof Date ? value : new Date(value);
        if (!Number.isFinite(date.getTime())) return "-";
        const options = {
            timeZone: "Asia/Shanghai",
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
            hour12: false,
        };
        if (includeSeconds) options.second = "2-digit";
        return date.toLocaleString("zh-CN", options);
    }

    formatBeijingTimestamp(seconds, includeSeconds = false) {
        const value = Number(seconds || 0);
        if (!Number.isFinite(value) || value <= 0) return "-";
        return this.formatBeijingTime(new Date(value * 1000), includeSeconds);
    }
}

if (typeof DashboardUtils !== "undefined") {
    Object.keys(DashboardUtils).forEach(key => {
        if (!LiveTradingPage.prototype[key]) LiveTradingPage.prototype[key] = DashboardUtils[key];
    });
}

document.addEventListener("DOMContentLoaded", () => { new LiveTradingPage().init(); });
