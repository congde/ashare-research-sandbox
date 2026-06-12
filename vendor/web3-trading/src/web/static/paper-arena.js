/**
 * Live Paper Arena — real-time multi-strategy simulation on /backtest.
 * Merged into BacktestPage; depends on dashboard-utils.js.
 */
const PaperArenaMixin = {
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
    },

    formatBeijingTimestamp(seconds, includeSeconds = false) {
        const value = Number(seconds || 0);
        if (!Number.isFinite(value) || value <= 0) return "-";
        return this.formatBeijingTime(new Date(value * 1000), includeSeconds);
    },

    _initPaperArenaState() {
        this._paperSessionId = localStorage.getItem("paperArenaSessionId") || "";
        this._paperArenaTimer = null;
        this._paperChart = null;
        this._paperResizeObserver = null;
    },

    bindPaperArenaEvents() {
        const el = this.elements;
        el.resetPaperArenaBtn?.addEventListener("click", () => this.runPaperArena(true));
        el.runPaperArenaBtn?.addEventListener("click", () => this.runPaperArena(false));
        el.startPaperArenaLoopBtn?.addEventListener("click", () => this.startPaperArenaLoop());
        el.stopPaperArenaLoopBtn?.addEventListener("click", () => this.stopPaperArenaLoop());
    },

    _restorePaperSettings() {
        const el = this.elements;
        try {
            const saved = JSON.parse(localStorage.getItem("paperArenaSettings") || "{}");
            if (saved.symbol && el.paperSymbolInput) el.paperSymbolInput.value = saved.symbol;
            if (saved.type && el.paperTypeSelect) el.paperTypeSelect.value = saved.type;
            if (saved.interval && el.paperIntervalInput) el.paperIntervalInput.value = saved.interval;
            if (saved.limit && el.paperLimitSelect) el.paperLimitSelect.value = saved.limit;
            if (saved.marketType && el.paperMarketTypeSelect) el.paperMarketTypeSelect.value = saved.marketType;
            if (saved.initialCash && el.paperInitialCashInput) el.paperInitialCashInput.value = saved.initialCash;
            if (saved.allocationPct && el.paperAllocationInput) el.paperAllocationInput.value = saved.allocationPct;
            if (saved.slippagePct && el.paperSlippageInput) el.paperSlippageInput.value = saved.slippagePct;
            if (saved.commissionPct && el.paperCommissionInput) el.paperCommissionInput.value = saved.commissionPct;
            if (saved.stopLoss && el.paperStopLossInput) el.paperStopLossInput.value = saved.stopLoss;
            if (saved.takeProfit && el.paperTakeProfitInput) el.paperTakeProfitInput.value = saved.takeProfit;
            if (saved.trailingStop && el.paperTrailingStopInput) el.paperTrailingStopInput.value = saved.trailingStop;
            if (saved.maxHoldBars && el.paperMaxHoldBarsInput) el.paperMaxHoldBarsInput.value = saved.maxHoldBars;
            if (saved.allowShort !== undefined && el.paperAllowShortInput) el.paperAllowShortInput.checked = !!saved.allowShort;
            if (saved.strategies && Array.isArray(saved.strategies) && el.paperStrategiesSelect) {
                const savedSet = new Set(saved.strategies);
                el.paperStrategiesSelect.querySelectorAll("input[type='checkbox']").forEach(cb => {
                    cb.checked = savedSet.has(cb.value);
                });
            }
        } catch (_) {}
    },

    _savePaperSettings() {
        const el = this.elements;
        const strategies = Array.from(el.paperStrategiesSelect?.querySelectorAll("input[type='checkbox']:checked") || []).map(cb => cb.value);
        const settings = {
            symbol: el.paperSymbolInput?.value || "",
            type: el.paperTypeSelect?.value || "",
            interval: el.paperIntervalInput?.value || "",
            limit: el.paperLimitSelect?.value || "",
            marketType: el.paperMarketTypeSelect?.value || "",
            initialCash: el.paperInitialCashInput?.value || "",
            allocationPct: el.paperAllocationInput?.value || "",
            slippagePct: el.paperSlippageInput?.value || "",
            commissionPct: el.paperCommissionInput?.value || "",
            stopLoss: el.paperStopLossInput?.value || "",
            takeProfit: el.paperTakeProfitInput?.value || "",
            trailingStop: el.paperTrailingStopInput?.value || "",
            maxHoldBars: el.paperMaxHoldBarsInput?.value || "",
            allowShort: !!el.paperAllowShortInput?.checked,
            strategies,
        };
        localStorage.setItem("paperArenaSettings", JSON.stringify(settings));
    },

    async loadPaperArenaStrategies() {
        const paperSelect = this.elements.paperStrategiesSelect;
        if (!paperSelect) return;
        try {
            const resp = await fetch("/api/dashboard/backtest/strategies");
            const data = await this.parseJsonResponse(resp);
            const strategies = data.strategies || [];
            if (!strategies.length) return;
            paperSelect.innerHTML = strategies.map(s =>
                `<label class="live-strategy-check"><input type="checkbox" value="${this.escapeHtml(s.name)}" checked><span>${this.escapeHtml(s.displayName || s.name)}</span></label>`
            ).join("");
        } catch (_) {
            paperSelect.innerHTML = `<label class="live-strategy-check"><input type="checkbox" value="technical_signal" checked><span>技术信号策略</span></label><label class="live-strategy-check"><input type="checkbox" value="buy_and_hold" checked><span>买入持有基准</span></label>`;
        }
    },

    async runPaperArena(reset = false) {
        const el = this.elements;
        const strategies = Array.from(el.paperStrategiesSelect?.querySelectorAll("input[type='checkbox']:checked") || []).map(option => option.value);
        if (!strategies.length) {
            if (el.paperArenaTable) el.paperArenaTable.innerHTML = "<div class='backtest-error'>请选择至少一个策略</div>";
            return;
        }
        if (reset) this._paperSessionId = "";
        if (el.paperArenaCards) el.paperArenaCards.innerHTML = `<div class='backtest-loading'>${reset ? "正在重置模拟盘..." : "正在处理最新K线..."}</div>`;
        if (reset && el.paperArenaTable) el.paperArenaTable.innerHTML = "";
        if (reset && el.paperArenaTrades) el.paperArenaTrades.innerHTML = "";
        if (el.paperSessionStatus) el.paperSessionStatus.textContent = reset ? "正在创建新模拟盘" : "正在读取当前行情";
        if (el.runPaperArenaBtn) el.runPaperArenaBtn.disabled = true;
        if (el.resetPaperArenaBtn) el.resetPaperArenaBtn.disabled = true;
        this._savePaperSettings();
        try {
            const payload = {
                sessionId: this._paperSessionId,
                reset: reset || !this._paperSessionId,
                symbol: el.paperSymbolInput?.value || "BTC-USDT",
                type: el.paperTypeSelect?.value || "1hour",
                warmupLimit: Number(el.paperLimitSelect?.value || 300),
                marketType: el.paperMarketTypeSelect?.value || "spot",
                initialCash: Number(el.paperInitialCashInput?.value || 10000),
                allocationPct: Number(el.paperAllocationInput?.value || 0.2),
                slippagePct: Number(el.paperSlippageInput?.value || 0.05),
                commissionPct: Number(el.paperCommissionInput?.value || 0.1),
                stopLoss: Number(el.paperStopLossInput?.value || 3),
                takeProfit: Number(el.paperTakeProfitInput?.value || 5),
                trailingStop: Number(el.paperTrailingStopInput?.value || 0),
                maxHoldBars: Number(el.paperMaxHoldBarsInput?.value || 0),
                allowShort: !!el.paperAllowShortInput?.checked,
                strategies,
            };
            const resp = await fetch("/api/dashboard/live/paper-arena/session/tick", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            const data = await this.parseJsonResponse(resp);
            if (!data.ok) throw new Error(data.message || "模拟盘运行失败");
            this._paperSessionId = data.session_id || "";
            if (this._paperSessionId) localStorage.setItem("paperArenaSessionId", this._paperSessionId);
            this.renderPaperArena(data);
        } catch (err) {
            if (el.paperArenaCards) el.paperArenaCards.innerHTML = `<div class="backtest-error">模拟盘失败: ${this.escapeHtml(err.message)}</div>`;
            if (el.paperSessionStatus) el.paperSessionStatus.textContent = `模拟盘失败: ${err.message}`;
        } finally {
            if (el.runPaperArenaBtn) el.runPaperArenaBtn.disabled = false;
            if (el.resetPaperArenaBtn) el.resetPaperArenaBtn.disabled = false;
        }
    },

    paperArenaPayload(reset = false) {
        const el = this.elements;
        const strategies = Array.from(el.paperStrategiesSelect?.querySelectorAll("input[type='checkbox']:checked") || []).map(option => option.value);
        return {
            sessionId: reset ? "" : this._paperSessionId,
            reset: reset || !this._paperSessionId,
            symbol: el.paperSymbolInput?.value || "BTC-USDT",
            type: el.paperTypeSelect?.value || "1hour",
            intervalSeconds: Number(el.paperIntervalInput?.value || 20),
            warmupLimit: Number(el.paperLimitSelect?.value || 300),
            marketType: el.paperMarketTypeSelect?.value || "spot",
            initialCash: Number(el.paperInitialCashInput?.value || 10000),
            allocationPct: Number(el.paperAllocationInput?.value || 0.2),
            slippagePct: Number(el.paperSlippageInput?.value || 0.05),
            commissionPct: Number(el.paperCommissionInput?.value || 0.1),
            stopLoss: Number(el.paperStopLossInput?.value || 3),
            takeProfit: Number(el.paperTakeProfitInput?.value || 5),
            trailingStop: Number(el.paperTrailingStopInput?.value || 0),
            maxHoldBars: Number(el.paperMaxHoldBarsInput?.value || 0),
            allowShort: !!el.paperAllowShortInput?.checked,
            strategies,
        };
    },

    async startPaperArenaLoop() {
        const el = this.elements;
        const strategies = Array.from(el.paperStrategiesSelect?.querySelectorAll("input[type='checkbox']:checked") || []).map(option => option.value);
        if (!strategies.length) {
            if (el.paperSessionStatus) el.paperSessionStatus.textContent = "请选择至少一个策略";
            return;
        }
        if (el.paperSessionStatus) el.paperSessionStatus.textContent = "正在启动规则策略后台模拟盘...";
        if (el.startPaperArenaLoopBtn) el.startPaperArenaLoopBtn.disabled = true;
        this._savePaperSettings();
        try {
            const resp = await fetch("/api/dashboard/live/paper-arena/session/start", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(this.paperArenaPayload(true)),
            });
            const data = await this.parseJsonResponse(resp);
            if (!data.ok) throw new Error(data.message || "启动失败");
            await this.renderPaperArenaRunnerStatus(data);
        } catch (err) {
            if (el.paperSessionStatus) el.paperSessionStatus.innerHTML = `<div class="backtest-error">后台模拟盘启动失败: ${this.escapeHtml(err.message)}</div>`;
        } finally {
            if (el.startPaperArenaLoopBtn) el.startPaperArenaLoopBtn.disabled = false;
        }
    },

    async stopPaperArenaLoop() {
        const el = this.elements;
        if (el.paperSessionStatus) el.paperSessionStatus.textContent = "正在停止规则策略后台模拟盘...";
        if (el.stopPaperArenaLoopBtn) el.stopPaperArenaLoopBtn.disabled = true;
        try {
            const resp = await fetch("/api/dashboard/live/paper-arena/session/stop", { method: "POST" });
            const data = await this.parseJsonResponse(resp);
            if (!data.ok) throw new Error(data.message || "停止失败");
            this.clearPaperArenaTimer();
            if (data.latest) this.renderPaperArena(data.latest);
            if (el.paperSessionStatus) el.paperSessionStatus.textContent = "规则策略后台模拟盘已停止";
        } catch (err) {
            if (el.paperSessionStatus) el.paperSessionStatus.innerHTML = `<div class="backtest-error">后台模拟盘停止失败: ${this.escapeHtml(err.message)}</div>`;
        } finally {
            if (el.stopPaperArenaLoopBtn) el.stopPaperArenaLoopBtn.disabled = false;
        }
    },

    clearPaperArenaTimer() {
        if (this._paperArenaTimer) {
            clearInterval(this._paperArenaTimer);
            this._paperArenaTimer = null;
        }
    },

    schedulePaperArenaStatusPolling() {
        this.clearPaperArenaTimer();
        this._paperArenaTimer = setInterval(() => this.loadPaperArenaStatus({ silent: true }), 5000);
    },

    async loadPaperArenaStatus(options = {}) {
        const el = this.elements;
        if (!el.paperSessionStatus) return;
        try {
            const resp = await fetch("/api/dashboard/live/paper-arena/session/status");
            const data = await this.parseJsonResponse(resp);
            if (!data.ok) throw new Error(data.message || "状态读取失败");
            await this.renderPaperArenaRunnerStatus(data, options);
        } catch (err) {
            if (!options.silent) {
                const restored = await this.loadStoredPaperArenaSession();
                if (!restored) {
                    el.paperSessionStatus.innerHTML = `<div class="backtest-error">规则策略模拟盘状态读取失败: ${this.escapeHtml(err.message)}</div>`;
                }
            }
        }
    },

    async renderPaperArenaRunnerStatus(data, options = {}) {
        const el = this.elements;
        const cfg = data.config || {};
        const latest = data.latest || null;
        const running = !!data.running;
        if (running) this.schedulePaperArenaStatusPolling();
        else this.clearPaperArenaTimer();

        if (latest && latest.session_id) {
            this._paperSessionId = latest.session_id;
            localStorage.setItem("paperArenaSessionId", this._paperSessionId);
            this.renderPaperArena(latest, { running, config: cfg, last_finished_at: data.last_finished_at, last_error: data.last_error });
            return true;
        }

        if (!running && this._paperSessionId) {
            const restored = await this.loadStoredPaperArenaSession();
            if (restored) return true;
        }

        if (el.paperSessionStatus && !options.silent) {
            if (running) {
                el.paperSessionStatus.textContent = `规则策略后台模拟盘运行中 · 间隔 ${cfg.interval_seconds || "-"}s · 等待第一轮结果`;
            } else if (this._paperSessionId) {
                el.paperSessionStatus.textContent = `规则策略后台模拟盘未运行 · 已记录 Session ${this._paperSessionId}`;
            }
        }
        return false;
    },

    async loadStoredPaperArenaSession() {
        if (!this._paperSessionId) return false;
        try {
            const resp = await fetch(`/api/dashboard/live/paper-arena/session?sessionId=${encodeURIComponent(this._paperSessionId)}`);
            const data = await this.parseJsonResponse(resp);
            if (!data.ok) throw new Error(data.message || "Session 读取失败");
            this.renderPaperArena(data);
            return true;
        } catch (err) {
            localStorage.removeItem("paperArenaSessionId");
            this._paperSessionId = "";
            return false;
        }
    },

    renderPaperArena(data, runnerMeta = {}) {
        const el = this.elements;
        const rows = data.leaderboard || [];
        const best = rows[0] || {};
        const assumptions = data.assumptions || {};
        const latest = data.latest_candle || {};
        const latestText = this.formatBeijingTimestamp(latest.time);
        const running = runnerMeta.running != null ? runnerMeta.running : null;
        const runningLabel = running === true ? '<span class="change-up">● 运行中</span>' : (running === false ? '<span class="change-down">● 已停止</span>' : '');
        const intervalLabel = runnerMeta.config?.interval_seconds ? ` · 间隔 ${runnerMeta.config.interval_seconds}s` : "";
        const lastFinished = runnerMeta.last_finished_at ? ` · 最近完成 ${this.formatBeijingTime(runnerMeta.last_finished_at, true)}` : "";
        if (el.paperSessionStatus) {
            const status = data.processed_now ? `已处理 ${data.processed_now} 根新K线` : "当前K线已处理，等待下一根闭合";
            el.paperSessionStatus.innerHTML = `${runningLabel} Session ${this.escapeHtml(data.session_id || "-")} · ${status} · 最新K线 ${this.escapeHtml(latestText)}${intervalLabel}${lastFinished} · 轮次 ${data.processed_bars || 0}`;
        }
        if (el.paperArenaCards) {
            el.paperArenaCards.innerHTML = `
                <div class="bt-metric-card"><div class="bt-metric-label">当前领先</div><div class="bt-metric-value">${this.escapeHtml(best.displayName || best.name || "-")}</div><div class="bt-metric-sub">${this.formatNumber(best.total_return_pct || 0)}%</div></div>
                <div class="bt-metric-card"><div class="bt-metric-label">已处理轮次</div><div class="bt-metric-value">${data.processed_bars || 0}</div><div class="bt-metric-sub">${this.escapeHtml(data.symbol || "")} · ${this.escapeHtml(data.type || "")}</div></div>
                <div class="bt-metric-card"><div class="bt-metric-label">初始资金</div><div class="bt-metric-value">${this.formatNumber(assumptions.initial_cash || 0)}</div><div class="bt-metric-sub">仓位 ${this.formatNumber((assumptions.allocation_pct || 0) * 100)}%</div></div>
                <div class="bt-metric-card"><div class="bt-metric-label">成交假设</div><div class="bt-metric-value">${this.formatNumber(assumptions.slippage_pct || 0)}%</div><div class="bt-metric-sub">手续费 ${this.formatNumber(assumptions.commission_pct || 0)}%</div></div>`;
        }
        this.renderPaperArenaChart(data);
        this.renderPaperArenaTable(data);
        this.renderPaperArenaLatestSignals(data);
        this.renderPaperArenaTrades(data);
    },

    _paperChartOptions(container, height) {
        return ChartTheme.baseOptions(container.clientWidth, height);
    },

    renderPaperArenaChart(data) {
        const el = this.elements;
        if (!el.paperArenaChart) return;
        el.paperArenaChart.innerHTML = "";
        if (el.paperArenaHint) el.paperArenaHint.style.display = "none";
        if (typeof LightweightCharts === "undefined") {
            el.paperArenaChart.innerHTML = "<div class='backtest-error'>图表库未加载</div>";
            return;
        }
        const colors = ChartTheme.LINE_PALETTE;
        const chart = LightweightCharts.createChart(el.paperArenaChart, this._paperChartOptions(el.paperArenaChart, 340));
        (data.results || []).forEach((row, index) => {
            const color = colors[index % colors.length];
            const series = chart.addLineSeries({ color, lineWidth: 2, title: row.displayName || row.name });
            series.setData((row.equity_curve || []).map(p => ({ time: p.time, value: Number(p.value || 0) })));
            const markers = (row.trades || []).slice(-120).map(t => ({
                time: t.time,
                position: t.action === "entry" ? "belowBar" : "aboveBar",
                color: t.action === "entry" ? "#16a34a" : "#dc2626",
                shape: t.action === "entry" ? "arrowUp" : "arrowDown",
            }));
            if (series.setMarkers) series.setMarkers(markers);
        });
        chart.timeScale().fitContent();
        this._paperChart = chart;
        if (this._paperResizeObserver) this._paperResizeObserver.disconnect();
        this._paperResizeObserver = new ResizeObserver(() => {
            if (el.paperArenaChart.clientWidth > 0) chart.applyOptions({ width: el.paperArenaChart.clientWidth });
        });
        this._paperResizeObserver.observe(el.paperArenaChart);
    },

    renderPaperArenaTable(data) {
        const el = this.elements;
        if (!el.paperArenaTable) return;
        let html = `<div class="bt-trades-header">模拟盘排行榜 — ${this.escapeHtml(data.symbol || "")}</div><div class="bt-trades-table"><div class="bt-trades-head live-paper-head"><span>#</span><span>策略</span><span>收益</span><span>权益</span><span>回撤</span><span>Sharpe</span><span>胜率</span><span>盈亏比</span><span>开仓/平仓</span></div>`;
        (data.leaderboard || []).forEach(row => {
            const ret = Number(row.total_return_pct || 0);
            const entryTrades = Number(row.entry_trades ?? 0);
            const closedTrades = Number(row.closed_trades ?? row.total_trades ?? 0);
            html += `<div class="bt-trades-row live-paper-row"><span>${row.rank || "-"}</span><span>${this.escapeHtml(row.displayName || row.name)}</span><span class="${ret >= 0 ? "change-up" : "change-down"}">${ret >= 0 ? "+" : ""}${this.formatNumber(ret)}%</span><span>${this.formatNumber(row.final_equity || 0)}</span><span class="change-down">-${this.formatNumber(row.max_drawdown_pct || 0)}%</span><span>${this.formatNumber(row.sharpe_ratio || 0)}</span><span>${this.formatNumber(row.win_rate_pct || 0)}%</span><span>${this.formatNumber(row.profit_factor || 0)}</span><span>${entryTrades}/${closedTrades}</span></div>`;
        });
        el.paperArenaTable.innerHTML = html + "</div>";
    },

    renderPaperArenaLatestSignals(data) {
        const el = this.elements;
        if (!el.paperArenaTrades) return;
        const latestSignals = [];
        (data.results || []).forEach(row => {
            const signals = row.signals || [];
            const lastSig = signals.length ? signals[signals.length - 1] : null;
            const pos = row.open_position || null;
            latestSignals.push({ name: row.displayName || row.name, signal: lastSig, position: pos });
        });
        if (!latestSignals.length) return;
        const fmtTime = (sec) => this.formatBeijingTimestamp(sec);
        let html = `<div class="bt-trades-header">各策略最新判断（最近K线）</div><div class="bt-trades-table"><div class="bt-trades-head live-paper-signals-head"><span>策略</span><span>时间</span><span>信号</span><span>评分</span><span>持仓</span><span>方向</span><span>入场价</span></div>`;
        latestSignals.forEach(item => {
            const sig = item.signal || {};
            const pos = item.position || {};
            const action = sig.action || "无";
            const actionClass = (action === "LONG" || action === "BUY") ? "change-up" : (action === "SHORT" || action === "SELL" ? "change-down" : "");
            const posDir = pos.direction || "-";
            const posDirClass = posDir === "LONG" ? "change-up" : (posDir === "SHORT" ? "change-down" : "");
            html += `<div class="bt-trades-row live-paper-signals-row"><span>${this.escapeHtml(item.name)}</span><span>${sig.time ? fmtTime(sig.time) : "-"}</span><span class="${actionClass}">${this.escapeHtml(action)}</span><span>${sig.score != null ? this.formatNumber(sig.score) : "-"}</span><span class="${posDirClass}">${pos.direction ? pos.direction : "空仓"}</span><span>${pos.direction || "-"}</span><span>${pos.entry_price ? this.formatNumber(pos.entry_price) : "-"}</span></div>`;
        });
        const tradesEl = el.paperArenaTrades;
        const signalsContainer = document.getElementById("paperArenaLatestSignals");
        if (signalsContainer) {
            signalsContainer.innerHTML = html + "</div>";
        } else {
            const div = document.createElement("div");
            div.id = "paperArenaLatestSignals";
            div.innerHTML = html + "</div>";
            tradesEl.parentNode.insertBefore(div, tradesEl);
        }
    },

    renderPaperArenaTrades(data) {
        const el = this.elements;
        if (!el.paperArenaTrades) return;
        const trades = [];
        (data.results || []).forEach(row => {
            (row.trades || []).forEach(trade => trades.push({ ...trade, strategy: row.displayName || row.name }));
        });
        trades.sort((a, b) => (b.time || 0) - (a.time || 0));
        if (!trades.length) {
            el.paperArenaTrades.innerHTML = "<div class='backtest-no-trades'>暂无模拟成交</div>";
            return;
        }
        const fmtTime = (sec) => this.formatBeijingTimestamp(sec);
        let html = `<div class="bt-trades-header">最近模拟成交</div><div class="bt-trades-table"><div class="bt-trades-head live-paper-trades-head"><span>时间</span><span>策略</span><span>动作</span><span>方向</span><span>价格</span><span>PnL</span><span>原因</span></div>`;
        trades.slice(0, 80).forEach(trade => {
            const pnl = Number(trade.pnl_pct || 0);
            html += `<div class="bt-trades-row live-paper-trades-row"><span>${fmtTime(trade.time)}</span><span>${this.escapeHtml(trade.strategy)}</span><span>${this.escapeHtml(trade.action || "-")}</span><span>${this.escapeHtml(trade.direction || "-")}</span><span>${this.formatNumber(trade.price || 0)}</span><span class="${pnl >= 0 ? "change-up" : "change-down"}">${trade.action === "exit" ? `${pnl >= 0 ? "+" : ""}${this.formatNumber(pnl)}%` : "-"}</span><span>${this.escapeHtml(trade.reason || "-")}</span></div>`;
        });
        el.paperArenaTrades.innerHTML = html + "</div>";
    },
};
