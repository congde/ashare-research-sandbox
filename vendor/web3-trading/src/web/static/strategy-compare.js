/**
 * Multi-strategy historical compare — used on /backtest.
 * Merged into BacktestPage; depends on dashboard-utils.js.
 */
const StrategyCompareMixin = {
    _initStrategyCompareState() {
        this._compareChart = null;
        this._compareResizeObserver = null;
    },

    bindStrategyCompareEvents() {
        this.elements.runCompareBtn?.addEventListener("click", () => this.runStrategyCompare());
    },

    async loadCompareStrategies() {
        const select = this.elements.compareStrategiesSelect;
        if (!select) return;
        try {
            const resp = await fetch("/api/dashboard/backtest/strategies");
            const data = await this.parseJsonResponse(resp);
            const defaults = new Set(["technical_signal", "ma_crossover", "rsi_mean_reversion", "macd", "buy_and_hold"]);
            const strategies = data.strategies || [];
            if (!strategies.length) return;
            select.innerHTML = strategies.map(s =>
                `<label class="live-strategy-check"><input type="checkbox" value="${this.escapeHtml(s.name)}" ${defaults.has(s.name) ? "checked" : ""}><span>${this.escapeHtml(s.displayName || s.name)}</span></label>`
            ).join("");
        } catch (_) {
            select.innerHTML = `<label class="live-strategy-check"><input type="checkbox" value="technical_signal" checked><span>技术信号策略</span></label><label class="live-strategy-check"><input type="checkbox" value="buy_and_hold" checked><span>买入持有基准</span></label>`;
        }
    },

    async runStrategyCompare() {
        const el = this.elements;
        const strategies = Array.from(el.compareStrategiesSelect?.querySelectorAll("input[type='checkbox']:checked") || []).map(option => option.value);
        if (!strategies.length) {
            if (el.strategyCompareTable) el.strategyCompareTable.innerHTML = "<div class='backtest-error'>请选择至少一个策略</div>";
            return;
        }
        if (el.strategyCompareTable) el.strategyCompareTable.innerHTML = "<div class='backtest-loading'>正在运行多策略对比...</div>";
        if (el.runCompareBtn) el.runCompareBtn.disabled = true;
        try {
            const resp = await fetch("/api/dashboard/live/strategy-compare", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    symbol: el.compareSymbolInput?.value || "BTC-USDT",
                    type: el.compareTypeSelect?.value || "1hour",
                    limit: Number(el.compareLimitSelect?.value || 300),
                    stopLoss: Number(el.compareStopLossInput?.value || 3),
                    takeProfit: Number(el.compareTakeProfitInput?.value || 5),
                    strategies,
                }),
            });
            const data = await this.parseJsonResponse(resp);
            if (!data.ok) throw new Error(data.message || "对比失败");
            this.renderStrategyCompare(data);
        } catch (err) {
            if (el.strategyCompareTable) el.strategyCompareTable.innerHTML = `<div class="backtest-error">策略对比失败: ${this.escapeHtml(err.message)}</div>`;
        } finally {
            if (el.runCompareBtn) el.runCompareBtn.disabled = false;
        }
    },

    renderStrategyCompare(data) {
        const el = this.elements;
        const rows = data.results || [];
        this.renderStrategyCompareChart(rows);
        if (!el.strategyCompareTable) return;
        let html = `<div class="bt-trades-header">策略对比结果 — ${this.escapeHtml(data.symbol || "")}</div><div class="bt-trades-table"><div class="bt-trades-head live-compare-head"><span>策略</span><span>收益</span><span>回撤</span><span>胜率</span><span>交易</span><span>Sharpe</span><span>盈亏比</span></div>`;
        rows.forEach(row => {
            if (row.error) {
                html += `<div class="bt-trades-row live-compare-row"><span>${this.escapeHtml(row.displayName || row.name)}</span><span class="change-down" style="grid-column: span 6;">${this.escapeHtml(row.error)}</span></div>`;
                return;
            }
            const ret = Number(row.total_return_pct || 0);
            html += `<div class="bt-trades-row live-compare-row"><span>${this.escapeHtml(row.displayName || row.name)}</span><span class="${ret >= 0 ? "change-up" : "change-down"}">${ret >= 0 ? "+" : ""}${this.formatNumber(ret)}%</span><span class="change-down">-${this.formatNumber(row.max_drawdown_pct || 0)}%</span><span>${this.formatNumber(row.win_rate || 0)}%</span><span>${row.total_trades || 0}</span><span>${this.formatNumber(row.sharpe_ratio || 0)}</span><span>${this.formatNumber(row.profit_factor || 0)}</span></div>`;
        });
        el.strategyCompareTable.innerHTML = html + "</div>";
    },

    renderStrategyCompareChart(rows) {
        const el = this.elements;
        if (!el.strategyCompareChart) return;
        el.strategyCompareChart.innerHTML = "";
        if (el.strategyCompareHint) el.strategyCompareHint.style.display = "none";
        if (typeof LightweightCharts === "undefined") {
            el.strategyCompareChart.innerHTML = "<div class='backtest-error'>图表库未加载</div>";
            return;
        }
        const colors = ChartTheme.LINE_PALETTE;
        const chart = LightweightCharts.createChart(el.strategyCompareChart, ChartTheme.baseOptions(el.strategyCompareChart.clientWidth, 320));
        rows.filter(row => !row.error).forEach((row, index) => {
            const series = chart.addLineSeries({ color: colors[index % colors.length], lineWidth: 2, title: row.displayName || row.name });
            series.setData((row.equity_curve || []).map(p => ({ time: p.time, value: Number(p.value || 0) })));
        });
        chart.timeScale().fitContent();
        this._compareChart = chart;
        if (this._compareResizeObserver) this._compareResizeObserver.disconnect();
        this._compareResizeObserver = new ResizeObserver(() => {
            if (el.strategyCompareChart.clientWidth > 0) chart.applyOptions({ width: el.strategyCompareChart.clientWidth });
        });
        this._compareResizeObserver.observe(el.strategyCompareChart);
    },
};
