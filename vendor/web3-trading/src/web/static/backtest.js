/**
 * Standalone Backtest Page.
 *
 * Adapted from BacktestMixin — runs independently on /backtest.
 * Depends on: dashboard-utils.js (DashboardUtils)
 */
class BacktestPage {
    constructor() {
        const _el = (id) => document.getElementById(id);
        this.elements = {
            runBacktestBtn: _el("runBacktestBtn"),
            btSymbolInput: _el("btSymbolInput"),
            btKlineType: _el("btKlineType"),
            btLimit: _el("btLimit"),
            btStrategy: _el("btStrategy"),
            btStopLoss: _el("btStopLoss"),
            btTakeProfit: _el("btTakeProfit"),
            btTrailingStop: _el("btTrailingStop"),
            btMaxHoldBars: _el("btMaxHoldBars"),
            btOptimize: _el("btOptimize"),
            backtestMetrics: _el("backtestMetrics"),
            btWalkForward: _el("btWalkForward"),
            backtestEquityChart: _el("backtestEquityChart"),
            backtestEquityHint: _el("backtestEquityHint"),
            backtestTradeTable: _el("backtestTradeTable"),
            btModelSelect: _el("btModelSelect"),
            btLlmAnalyzeBtn: _el("btLlmAnalyzeBtn"),
            btLlmOutput: _el("btLlmOutput"),
            btLlmModelTag: _el("btLlmModelTag"),
            btRecommendBtn: _el("btRecommendBtn"),
            btRecommendOutput: _el("btRecommendOutput"),
            resetPaperArenaBtn: _el("resetPaperArenaBtn"),
            runPaperArenaBtn: _el("runPaperArenaBtn"),
            startPaperArenaLoopBtn: _el("startPaperArenaLoopBtn"),
            stopPaperArenaLoopBtn: _el("stopPaperArenaLoopBtn"),
            paperSymbolInput: _el("paperSymbolInput"),
            paperTypeSelect: _el("paperTypeSelect"),
            paperIntervalInput: _el("paperIntervalInput"),
            paperLimitSelect: _el("paperLimitSelect"),
            paperMarketTypeSelect: _el("paperMarketTypeSelect"),
            paperInitialCashInput: _el("paperInitialCashInput"),
            paperAllocationInput: _el("paperAllocationInput"),
            paperSlippageInput: _el("paperSlippageInput"),
            paperCommissionInput: _el("paperCommissionInput"),
            paperStopLossInput: _el("paperStopLossInput"),
            paperTakeProfitInput: _el("paperTakeProfitInput"),
            paperTrailingStopInput: _el("paperTrailingStopInput"),
            paperMaxHoldBarsInput: _el("paperMaxHoldBarsInput"),
            paperAllowShortInput: _el("paperAllowShortInput"),
            paperStrategiesSelect: _el("paperStrategiesSelect"),
            paperSessionStatus: _el("paperSessionStatus"),
            paperArenaCards: _el("paperArenaCards"),
            paperArenaChart: _el("paperArenaChart"),
            paperArenaHint: _el("paperArenaHint"),
            paperArenaTable: _el("paperArenaTable"),
            paperArenaTrades: _el("paperArenaTrades"),
            runCompareBtn: _el("runCompareBtn"),
            compareSymbolInput: _el("compareSymbolInput"),
            compareTypeSelect: _el("compareTypeSelect"),
            compareLimitSelect: _el("compareLimitSelect"),
            compareStopLossInput: _el("compareStopLossInput"),
            compareTakeProfitInput: _el("compareTakeProfitInput"),
            compareStrategiesSelect: _el("compareStrategiesSelect"),
            strategyCompareChart: _el("strategyCompareChart"),
            strategyCompareHint: _el("strategyCompareHint"),
            strategyCompareTable: _el("strategyCompareTable"),
        };
        this._btData = null;
        this._btChart = null;
        this._btChartRO = null;
        this._initPaperArenaState();
        this._initStrategyCompareState();
    }

    async init() {
        await Promise.all([
            this.loadStrategies(),
            this.loadPaperArenaStrategies(),
            this.loadCompareStrategies(),
        ]);
        this.bindEvents();
        this.bindPaperArenaEvents();
        this.bindStrategyCompareEvents();
        this._restorePaperSettings();
        await this.loadPaperArenaStatus();
        this.hydrateFromQuery();
    }

    async loadStrategies() {
        const el = this.elements;
        if (!el.btStrategy) return;
        const prev = el.btStrategy.value;
        try {
            const resp = await fetch("/api/dashboard/backtest/strategies");
            const data = await this.parseJsonResponse(resp);
            if (!data.ok || !Array.isArray(data.strategies) || !data.strategies.length) return;

            el.btStrategy.innerHTML = data.strategies
                .map((s) => `<option value="${this.escapeHtml(s.name)}">${this.escapeHtml(s.displayName || s.name)}</option>`)
                .join("");

            if (prev && data.strategies.some((s) => s.name === prev)) {
                el.btStrategy.value = prev;
            }
        } catch (_) {
            // Keep static fallback options when strategy endpoint is unavailable.
        }
    }

    hydrateFromQuery() {
        const params = new URLSearchParams(window.location.search || "");
        if (params.get("symbol")) this.elements.btSymbolInput.value = params.get("symbol");
        if (params.get("type")) this.elements.btKlineType.value = params.get("type");
        if (params.get("strategy")) this.elements.btStrategy.value = params.get("strategy");
    }

    bindEvents() {
        const el = this.elements;
        if (el.runBacktestBtn) el.runBacktestBtn.addEventListener("click", () => this.runBacktest());
        if (el.btSymbolInput) el.btSymbolInput.addEventListener("keydown", (e) => { if (e.key === "Enter") this.runBacktest(); });
        if (el.btLlmAnalyzeBtn) el.btLlmAnalyzeBtn.addEventListener("click", () => this.runBtLlmAnalysis());
        if (el.btRecommendBtn) el.btRecommendBtn.addEventListener("click", () => this.runBtRecommend());
        if (el.btModelSelect) {
            el.btModelSelect.addEventListener("change", () => {
                if (el.btLlmModelTag) {
                    const opt = el.btModelSelect.options[el.btModelSelect.selectedIndex];
                    el.btLlmModelTag.textContent = opt ? opt.text : "";
                }
            });
        }
    }

    async runBacktest() {
        const el = this.elements;
        if (!el.backtestMetrics) return;

        const symbol = (el.btSymbolInput?.value || "BTC-USDT").trim().toUpperCase();
        const type = el.btKlineType?.value || "1hour";
        const limit = el.btLimit?.value || "300";
        const stopLoss = el.btStopLoss?.value || "3";
        const takeProfit = el.btTakeProfit?.value || "5";
        const trailingStop = el.btTrailingStop?.value || "0";
        const maxHoldBars = el.btMaxHoldBars?.value || "0";
        const strategy = el.btStrategy?.value || "technical_signal";
        const optimize = el.btOptimize?.checked ? "true" : "false";
        const pair = symbol.includes("-") ? symbol : symbol + "-USDT";

        const loadingMsg = optimize === "true" ? "正在运行 Walk-Forward 优化回测..." : "正在运行回测...";
        el.backtestMetrics.innerHTML = `<div class="backtest-loading">${loadingMsg}</div>`;
        if (el.backtestTradeTable) el.backtestTradeTable.innerHTML = "";
        if (el.backtestEquityHint) el.backtestEquityHint.textContent = "回测运行中...";
        if (el.runBacktestBtn) el.runBacktestBtn.disabled = true;

        try {
            const url = `/api/dashboard/backtest?symbol=${encodeURIComponent(pair)}&type=${encodeURIComponent(type)}&limit=${limit}&stopLoss=${stopLoss}&takeProfit=${takeProfit}&trailingStop=${trailingStop}&maxHoldBars=${maxHoldBars}&strategy=${encodeURIComponent(strategy)}&optimize=${optimize}`;
            const resp = await fetch(url);
            const data = await this.parseJsonResponse(resp);
            if (!data.ok) throw new Error(data.message || "回测失败");

            this._btData = data;
            this._renderWalkForward(data);
            this._renderBacktestMetrics(data);
            this._renderBacktestEquityChart(data);
            this._renderBacktestTrades(data);
            if (el.btLlmAnalyzeBtn) el.btLlmAnalyzeBtn.disabled = false;
            if (el.btRecommendBtn) el.btRecommendBtn.disabled = false;
            if (el.btLlmOutput) el.btLlmOutput.innerHTML = "";
            if (el.btRecommendOutput) el.btRecommendOutput.innerHTML = "";
        } catch (err) {
            el.backtestMetrics.innerHTML = `<div class="backtest-error">回测失败: ${this.escapeHtml(err.message)}</div>`;
            if (el.backtestEquityHint) el.backtestEquityHint.textContent = "回测失败";
        } finally {
            if (el.runBacktestBtn) el.runBacktestBtn.disabled = false;
        }
    }

    _renderWalkForward(data) {
        const el = this.elements;
        if (!el.btWalkForward) return;
        const wf = data.walk_forward;
        if (!wf || !wf.num_windows) { el.btWalkForward.innerHTML = ""; return; }

        const sharpeClass = wf.out_of_sample_sharpe >= 0.5 ? "change-up" : wf.out_of_sample_sharpe >= 0 ? "" : "change-down";
        const retClass = wf.out_of_sample_return >= 0 ? "change-up" : "change-down";
        let windowRows = "";
        (wf.window_results || []).forEach(w => {
            const params = Object.entries(w.bestParams || {}).map(([k, v]) => `${k}=${v}`).join(", ");
            windowRows += `<div class="bt-wf-row"><span>Window ${w.window}</span><span>${w.trainSize}→${w.testSize}</span><span>${w.inSampleSharpe}</span><span class="${w.outOfSampleSharpe >= 0 ? 'change-up' : 'change-down'}">${w.outOfSampleSharpe}</span><span class="${w.outOfSampleReturn >= 0 ? 'change-up' : 'change-down'}">${w.outOfSampleReturn >= 0 ? '+' : ''}${w.outOfSampleReturn}%</span><span class="bt-wf-params">${this.escapeHtml(params)}</span></div>`;
        });
        const bestParams = Object.entries(wf.best_params || {}).map(([k, v]) => `<span class="bt-wf-param-tag">${k}=${v}</span>`).join(" ");
        el.btWalkForward.innerHTML = `<div class="bt-wf-header"><span class="bt-wf-title">Walk-Forward 优化结果</span><span class="bt-wf-meta">${wf.num_windows} 个滚动窗口</span></div><div class="bt-wf-summary"><div class="bt-wf-stat"><div class="bt-wf-stat-label">样本内 Sharpe</div><div class="bt-wf-stat-value">${wf.in_sample_sharpe}</div></div><div class="bt-wf-stat"><div class="bt-wf-stat-label">样本外 Sharpe</div><div class="bt-wf-stat-value ${sharpeClass}">${wf.out_of_sample_sharpe}</div></div><div class="bt-wf-stat"><div class="bt-wf-stat-label">样本外收益</div><div class="bt-wf-stat-value ${retClass}">${wf.out_of_sample_return >= 0 ? '+' : ''}${wf.out_of_sample_return}%</div></div><div class="bt-wf-stat"><div class="bt-wf-stat-label">最优参数</div><div class="bt-wf-stat-params">${bestParams}</div></div></div><div class="bt-wf-detail"><div class="bt-wf-head"><span>#</span><span>Train→Test</span><span>IS Sharpe</span><span>OOS Sharpe</span><span>OOS Return</span><span>Params</span></div>${windowRows}</div>`;
    }

    _renderBacktestMetrics(data) {
        const el = this.elements;
        if (!el.backtestMetrics) return;
        const retClass = data.total_return_pct >= 0 ? "change-up" : "change-down";
        const retSign = data.total_return_pct >= 0 ? "+" : "";
        const wrClass = data.win_rate >= 50 ? "change-up" : data.win_rate >= 40 ? "" : "change-down";
        const pfClass = data.profit_factor >= 1.5 ? "change-up" : data.profit_factor >= 1.0 ? "" : "change-down";
        const sharpeClass = data.sharpe_ratio >= 1.0 ? "change-up" : data.sharpe_ratio >= 0 ? "" : "change-down";
        const sortinoClass = data.sortino_ratio >= 1.0 ? "change-up" : data.sortino_ratio >= 0 ? "" : "change-down";
        const calmarClass = data.calmar_ratio >= 1.0 ? "change-up" : data.calmar_ratio >= 0 ? "" : "change-down";
        const typeLabel = {"15min": "15m", "1hour": "1h", "4hour": "4h", "1day": "1d"}[data.kline_type] || data.kline_type;
        const mc95 = data.monte_carlo_95 == null ? "-" : `${data.monte_carlo_95 >= 0 ? "+" : ""}${data.monte_carlo_95}%`;
        el.backtestMetrics.innerHTML = `<div class="bt-summary-bar"><span class="bt-summary-symbol">${this.escapeHtml(data.symbol)}</span><span class="bt-summary-meta">${typeLabel} · ${data.total_candles} 根K线 · ${data.strategy}</span></div><div class="bt-metrics-grid"><div class="bt-metric-card"><div class="bt-metric-label">总收益</div><div class="bt-metric-value ${retClass}">${retSign}${data.total_return_pct}%</div></div><div class="bt-metric-card"><div class="bt-metric-label">胜率</div><div class="bt-metric-value ${wrClass}">${data.win_rate}%</div></div><div class="bt-metric-card"><div class="bt-metric-label">总交易</div><div class="bt-metric-value">${data.total_trades}</div><div class="bt-metric-sub">${data.winning_trades} 盈 / ${data.losing_trades} 亏</div></div><div class="bt-metric-card"><div class="bt-metric-label">最大回撤</div><div class="bt-metric-value change-down">-${data.max_drawdown_pct}%</div></div><div class="bt-metric-card"><div class="bt-metric-label">夏普比率</div><div class="bt-metric-value ${sharpeClass}">${data.sharpe_ratio}</div></div><div class="bt-metric-card"><div class="bt-metric-label">Sortino</div><div class="bt-metric-value ${sortinoClass}">${data.sortino_ratio ?? 0}</div></div><div class="bt-metric-card"><div class="bt-metric-label">Calmar</div><div class="bt-metric-value ${calmarClass}">${data.calmar_ratio ?? 0}</div></div><div class="bt-metric-card"><div class="bt-metric-label">盈亏比</div><div class="bt-metric-value ${pfClass}">${data.profit_factor >= 999 ? "∞" : data.profit_factor}</div></div><div class="bt-metric-card"><div class="bt-metric-label">平均收益/笔</div><div class="bt-metric-value">${data.avg_trade_pct >= 0 ? "+" : ""}${data.avg_trade_pct}%</div></div><div class="bt-metric-card"><div class="bt-metric-label">平均持仓</div><div class="bt-metric-value">${data.avg_bars_held ?? 0} 根</div></div><div class="bt-metric-card"><div class="bt-metric-label">Monte Carlo 5%</div><div class="bt-metric-value">${mc95}</div></div><div class="bt-metric-card"><div class="bt-metric-label">风控参数</div><div class="bt-metric-sub">SL ${data.stop_loss_pct}% / TP ${data.take_profit_pct}% / TS ${data.trailing_stop_pct ?? 0}% / Hold ${data.max_hold_bars ?? 0}</div></div><div class="bt-metric-card"><div class="bt-metric-label">最佳 / 最差</div><div class="bt-metric-value"><span class="change-up">+${data.best_trade_pct}%</span> / <span class="change-down">${data.worst_trade_pct}%</span></div></div></div>`;
    }

    _renderBacktestEquityChart(data) {
        const el = this.elements;
        if (!el.backtestEquityChart) return;
        const curve = data.equity_curve || [];
        if (!curve.length) { if (el.backtestEquityHint) el.backtestEquityHint.textContent = "无权益曲线数据"; return; }
        if (el.backtestEquityHint) el.backtestEquityHint.style.display = "none";
        el.backtestEquityChart.innerHTML = "";
        if (typeof LightweightCharts === "undefined") { el.backtestEquityChart.innerHTML = "<div class='backtest-error'>图表库未加载</div>"; return; }

        const chart = LightweightCharts.createChart(el.backtestEquityChart, ChartTheme.baseOptions(el.backtestEquityChart.clientWidth, 280));
        const equitySeries = chart.addLineSeries({ color: "#4ea1ff", lineWidth: 2, title: "权益" });
        equitySeries.setData(curve.map(p => ({ time: p.ts, value: p.equity })));
        const ddSeries = chart.addLineSeries({ color: "#ef4444", lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dotted, title: "回撤%", priceScaleId: "dd" });
        chart.priceScale("dd").applyOptions({ scaleMargins: { top: 0.7, bottom: 0 } });
        ddSeries.setData(curve.map(p => ({ time: p.ts, value: -p.drawdown })));

        const trades = data.trades || [];
        const markers = [];
        trades.forEach(t => {
            markers.push({ time: t.entryTs, position: "belowBar", color: t.direction === "LONG" ? "#22c55e" : "#ef4444", shape: t.direction === "LONG" ? "arrowUp" : "arrowDown", text: t.direction === "LONG" ? "买" : "卖" });
            markers.push({ time: t.exitTs, position: "aboveBar", color: t.pnlPct >= 0 ? "#22c55e" : "#ef4444", shape: "circle", text: `${t.pnlPct >= 0 ? "+" : ""}${t.pnlPct}%` });
        });
        markers.sort((a, b) => a.time - b.time);
        if (markers.length) equitySeries.setMarkers(markers);
        chart.timeScale().fitContent();
        this._btChart = chart;
        const ro = new ResizeObserver(() => { if (el.backtestEquityChart.clientWidth > 0) chart.applyOptions({ width: el.backtestEquityChart.clientWidth }); });
        ro.observe(el.backtestEquityChart);
        this._btChartRO = ro;
    }

    _renderBacktestTrades(data) {
        const el = this.elements;
        if (!el.backtestTradeTable) return;
        const trades = data.trades || [];
        if (!trades.length) { el.backtestTradeTable.innerHTML = "<div class='backtest-no-trades'>回测期间无交易信号触发</div>"; return; }
        const fmtTime = (ts) => ts ? new Date(ts * 1000).toLocaleString("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "-";
        let html = `<div class="bt-trades-header">交易记录 (${trades.length} 笔)</div><div class="bt-trades-table"><div class="bt-trades-head"><span>#</span><span>方向</span><span>入场时间</span><span>入场价</span><span>出场时间</span><span>出场价</span><span>收益</span><span>原因</span></div>`;
        trades.forEach((t, i) => {
            const dirClass = t.direction === "LONG" ? "change-up" : "change-down";
            const dirLabel = t.direction === "LONG" ? "做多" : "做空";
            const pnlClass = t.pnlPct >= 0 ? "change-up" : "change-down";
            html += `<div class="bt-trades-row"><span>${i + 1}</span><span class="${dirClass}">${dirLabel}</span><span>${fmtTime(t.entryTs)}</span><span>${this.formatNumber(t.entryPrice)}</span><span>${fmtTime(t.exitTs)}</span><span>${this.formatNumber(t.exitPrice)}</span><span class="${pnlClass}">${t.pnlPct >= 0 ? "+" : ""}${t.pnlPct}%</span><span>${this.escapeHtml(t.exitReason)}</span></div>`;
        });
        el.backtestTradeTable.innerHTML = html + `</div>`;
    }

    async runBtLlmAnalysis() {
        const el = this.elements;
        if (!this._btData || !el.btLlmOutput) return;
        const model = el.btModelSelect?.value || "deepseek/deepseek-v4-flash";
        const data = this._btData;
        const metrics = {
            total_return_pct: data.total_return_pct, max_drawdown_pct: data.max_drawdown_pct,
            win_rate_pct: data.win_rate, sharpe_ratio: data.sharpe_ratio, profit_factor: data.profit_factor,
            total_trades: data.total_trades, avg_return_pct: data.avg_trade_pct,
            stop_loss_pct: data.stop_loss_pct ?? 3, take_profit_pct: data.take_profit_pct ?? 5,
        };
        const trades = (data.trades || []).map(t => ({ direction: t.direction, entry_price: t.entryPrice, exit_price: t.exitPrice, pnl_pct: t.pnlPct, exit_reason: t.exitReason }));
        if (el.btLlmAnalyzeBtn) el.btLlmAnalyzeBtn.disabled = true;
        el.btLlmOutput.innerHTML = '<div class="bt-llm-loading">AI 正在分析回测结果...</div>';
        try {
            const resp = await fetch("/api/dashboard/backtest/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model, metrics, trades, symbol: data.symbol || "" }) });
            const result = await this.parseJsonResponse(resp);
            if (!result.ok) throw new Error(result.message || "分析失败");
            this._renderBtLlmOutput(result.analysis, result.model);
        } catch (err) {
            el.btLlmOutput.innerHTML = `<div class="backtest-error">AI 分析失败: ${this.escapeHtml(err.message)}</div>`;
        } finally {
            if (el.btLlmAnalyzeBtn) el.btLlmAnalyzeBtn.disabled = false;
        }
    }

    _renderBtLlmOutput(markdown, model) {
        const el = this.elements;
        if (!el.btLlmOutput) return;
        let html = this.escapeHtml(markdown);
        html = html.replace(/^### (.+)$/gm, '<h4>$1</h4>').replace(/^## (.+)$/gm, '<h3>$1</h3>').replace(/^# (.+)$/gm, '<h2>$1</h2>');
        html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
        html = html.replace(/(<li>.*<\/li>)/gs, '<ul>$1</ul>').replace(/<\/ul>\s*<ul>/g, '');
        html = html.replace(/\n\n/g, '</p><p>');
        html = '<p>' + html + '</p>';
        html = html.replace(/<p><\/p>/g, '').replace(/<p>(<h[234]>)/g, '$1').replace(/(<\/h[234]>)<\/p>/g, '$1').replace(/<p>(<ul>)/g, '$1').replace(/(<\/ul>)<\/p>/g, '$1');
        if (el.btLlmModelTag) { el.btLlmModelTag.textContent = this.formatModelName(model); el.btLlmModelTag.style.display = ""; }
        el.btLlmOutput.innerHTML = `<div class="bt-llm-content">${html}</div>`;
    }

    async runBtRecommend() {
        const el = this.elements;
        if (!this._btData || !el.btRecommendOutput) return;
        const model = el.btModelSelect?.value || "deepseek/deepseek-v4-flash";
        const data = this._btData;
        const symbol = (el.btSymbolInput?.value || "BTC-USDT").trim().toUpperCase();
        const pair = symbol.includes("-") ? symbol : symbol + "-USDT";
        const klineType = el.btKlineType?.value || "1hour";
        const strategy = el.btStrategy?.value || "technical_signal";
        const metrics = { total_return_pct: data.total_return_pct, max_drawdown_pct: data.max_drawdown_pct, win_rate: data.win_rate, sharpe_ratio: data.sharpe_ratio, profit_factor: data.profit_factor, total_trades: data.total_trades };
        const params = data.walk_forward?.best_params || null;
        if (el.btRecommendBtn) el.btRecommendBtn.disabled = true;
        el.btRecommendOutput.innerHTML = '<div class="bt-recommend-loading"><span class="bt-rec-spinner"></span> 正在获取实时行情并生成买入建议...</div>';
        try {
            const resp = await fetch("/api/dashboard/backtest/recommend", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model, symbol: pair, klineType, strategy, metrics, params }) });
            const result = await this.parseJsonResponse(resp);
            if (!result.ok) throw new Error(result.message || "建议生成失败");
            this._renderBtRecommend(result);
        } catch (err) {
            el.btRecommendOutput.innerHTML = `<div class="backtest-error">买入建议生成失败: ${this.escapeHtml(err.message)}</div>`;
        } finally {
            if (el.btRecommendBtn) el.btRecommendBtn.disabled = false;
        }
    }

    _renderBtRecommend(result) {
        const el = this.elements;
        if (!el.btRecommendOutput) return;
        const action = result.signal?.action || "WAIT";
        const score = result.signal?.score ?? 0;
        let signalClass = "bt-rec-neutral", signalLabel = "观望";
        if (action === "LONG" || action === "WEAK_LONG") { signalClass = "bt-rec-bullish"; signalLabel = action === "LONG" ? "🟢 看多" : "🟡 弱多"; }
        else if (action === "SHORT" || action === "WEAK_SHORT") { signalClass = "bt-rec-bearish"; signalLabel = action === "SHORT" ? "🔴 看空" : "🟠 弱空"; }
        const price = result.price ? this.formatNumber(result.price) : "N/A";
        const rsi = result.rsi != null ? result.rsi.toFixed(1) : "N/A";
        const trend = result.trend || "N/A";
        const fg = result.fearGreed != null ? result.fearGreed : "N/A";
        let html = this.escapeHtml(result.recommendation || "");
        html = html.replace(/^### (.+)$/gm, '<h4>$1</h4>').replace(/^## (.+)$/gm, '<h3>$1</h3>').replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/^- (.+)$/gm, '<li>$1</li>').replace(/(<li>.*<\/li>)/gs, '<ul>$1</ul>').replace(/<\/ul>\s*<ul>/g, '');
        html = html.replace(/\n\n/g, '</p><p>'); html = '<p>' + html + '</p>';
        html = html.replace(/<p><\/p>/g, '').replace(/<p>(<h[234]>)/g, '$1').replace(/(<\/h[234]>)<\/p>/g, '$1').replace(/<p>(<ul>)/g, '$1').replace(/(<\/ul>)<\/p>/g, '$1');
        el.btRecommendOutput.innerHTML = `<div class="bt-rec-card"><div class="bt-rec-header"><span class="bt-rec-title">📊 当前行情建议</span><span class="bt-rec-badge ${signalClass}">${signalLabel} (${score > 0 ? "+" : ""}${score})</span><span class="bt-rec-time">${new Date().toLocaleString("zh-CN", { hour: "2-digit", minute: "2-digit", month: "short", day: "numeric" })}</span></div><div class="bt-rec-stats"><div class="bt-rec-stat"><span class="bt-rec-stat-label">当前价</span><span class="bt-rec-stat-val">${price}</span></div><div class="bt-rec-stat"><span class="bt-rec-stat-label">RSI</span><span class="bt-rec-stat-val">${rsi}</span></div><div class="bt-rec-stat"><span class="bt-rec-stat-label">趋势</span><span class="bt-rec-stat-val">${trend}</span></div><div class="bt-rec-stat"><span class="bt-rec-stat-label">恐贪</span><span class="bt-rec-stat-val">${fg}</span></div></div><div class="bt-rec-body">${html}</div></div>`;
    }
}

// Merge shared utilities
if (typeof DashboardUtils !== "undefined") {
    Object.keys(DashboardUtils).forEach(key => { BacktestPage.prototype[key] = DashboardUtils[key]; });
}
if (typeof PaperArenaMixin !== "undefined") {
    Object.assign(BacktestPage.prototype, PaperArenaMixin);
}
if (typeof StrategyCompareMixin !== "undefined") {
    Object.assign(BacktestPage.prototype, StrategyCompareMixin);
}

document.addEventListener("DOMContentLoaded", () => { new BacktestPage().init(); });
