/**
 * Single-chart K-line stack — price, volume, MACD, RSI, KDJ fused in one pane.
 */
(function (global) {
    const DEFAULT_INDICATORS = {
        ma20: true,
        ma60: true,
        boll: true,
        volume: true,
        macd: true,
        rsi: true,
        kdj: true,
        tradePlan: true,
    };

    const TRADE_PLAN_LINES = [
        { key: "support", title: "支撑", color: "#26a69a", lineWidth: 1, lineStyle: 2 },
        { key: "resistance", title: "阻力", color: "#ef5350", lineWidth: 1, lineStyle: 2 },
        { key: "entryLow", title: "入场低", color: "#42a5f5", lineWidth: 1, lineStyle: 2 },
        { key: "entryHigh", title: "入场高", color: "#42a5f5", lineWidth: 1, lineStyle: 2 },
        { key: "stop", title: "止损", color: "#ff7043", lineWidth: 2, lineStyle: 0 },
        { key: "target1", title: "目标1", color: "#66bb6a", lineWidth: 1, lineStyle: 2 },
        { key: "target2", title: "目标2", color: "#43a047", lineWidth: 1, lineStyle: 2 },
    ];

    const BAND_HEIGHT = 0.11;
    const BAND_GAP = 0.008;

    class KlineChartStack {
        constructor(options = {}) {
            this.mainEl = options.mainEl || null;
            this.legendEl = options.legendEl || null;
            this.hintEl = options.hintEl || null;
            this.toTime = typeof options.toTime === "function" ? options.toTime : (ts) => Number(ts || 0);
            this.mainHeight = options.mainHeight || 520;
            this.indicators = { ...DEFAULT_INDICATORS, ...(options.indicators || {}) };
            this.mainChart = null;
            this.series = {};
            this._lastCandles = [];
            this._tradePlan = null;
            this._tradePlanLines = [];
        }

        init() {
            const ChartTheme = global.ChartTheme;
            if (!this.mainEl || !global.LightweightCharts || !ChartTheme) {
                if (this.hintEl) this.hintEl.textContent = "图表库加载失败，请刷新页面重试。";
                return false;
            }
            const width = Math.max(320, this.mainEl.clientWidth || 320);
            this.mainChart = global.LightweightCharts.createChart(this.mainEl, ChartTheme.baseOptions(width, this.mainHeight));

            this.series.candle = this.mainChart.addCandlestickSeries(ChartTheme.candleSeriesOptions());
            this.series.ma20 = this.mainChart.addLineSeries({ color: ChartTheme.MA20, lineWidth: 2, priceLineVisible: false });
            this.series.ma60 = this.mainChart.addLineSeries({ color: ChartTheme.MA60, lineWidth: 2, priceLineVisible: false });
            this.series.bbUpper = this.mainChart.addLineSeries({ color: ChartTheme.BOLL, lineWidth: 1, lineStyle: 2, priceLineVisible: false });
            this.series.bbMiddle = this.mainChart.addLineSeries({ color: ChartTheme.BOLL, lineWidth: 1, priceLineVisible: false });
            this.series.bbLower = this.mainChart.addLineSeries({ color: ChartTheme.BOLL, lineWidth: 1, lineStyle: 2, priceLineVisible: false });

            this.series.volume = this.mainChart.addHistogramSeries({
                priceFormat: { type: "volume" },
                priceScaleId: "volume",
                priceLineVisible: false,
            });

            this.series.macdLine = this.mainChart.addLineSeries({ color: ChartTheme.MACD_LINE, lineWidth: 1.5, priceScaleId: "macd", priceLineVisible: false });
            this.series.macdSignal = this.mainChart.addLineSeries({ color: ChartTheme.MACD_SIGNAL, lineWidth: 1.5, priceScaleId: "macd", priceLineVisible: false });
            this.series.macdHist = this.mainChart.addHistogramSeries({
                priceScaleId: "macd",
                priceLineVisible: false,
                priceFormat: { type: "price", minMove: 0.00001, precision: 5 },
            });

            this.series.rsiLine = this.mainChart.addLineSeries({ color: ChartTheme.RSI_LINE, lineWidth: 1, priceScaleId: "rsi", priceLineVisible: false, lastValueVisible: true });
            this.series.rsiUpper = this.mainChart.addLineSeries({ color: ChartTheme.RSI_UPPER, lineWidth: 1, lineStyle: 2, priceScaleId: "rsi", priceLineVisible: false, lastValueVisible: false });
            this.series.rsiLower = this.mainChart.addLineSeries({ color: ChartTheme.RSI_LOWER, lineWidth: 1, lineStyle: 2, priceScaleId: "rsi", priceLineVisible: false, lastValueVisible: false });

            this.series.kdjK = this.mainChart.addLineSeries({ color: ChartTheme.KDJ_K, lineWidth: 1, priceScaleId: "kdj", priceLineVisible: false, lastValueVisible: true });
            this.series.kdjD = this.mainChart.addLineSeries({ color: ChartTheme.KDJ_D, lineWidth: 1, priceScaleId: "kdj", priceLineVisible: false, lastValueVisible: true });
            this.series.kdjJ = this.mainChart.addLineSeries({ color: ChartTheme.KDJ_J, lineWidth: 1, priceScaleId: "kdj", priceLineVisible: false, lastValueVisible: true });

            this._updateScaleLayout();
            this.updateLegend();
            return true;
        }

        _activeLowerBands() {
            const ind = this.indicators;
            const bands = [];
            if (ind.volume) bands.push("volume");
            if (ind.macd) bands.push("macd");
            if (ind.rsi) bands.push("rsi");
            if (ind.kdj) bands.push("kdj");
            return bands;
        }

        _updateScaleLayout() {
            if (!this.mainChart) return;
            const bands = this._activeLowerBands();
            const lowerTotal = bands.length > 0
                ? bands.length * BAND_HEIGHT + (bands.length - 1) * BAND_GAP + 0.03
                : 0.06;

            this.mainChart.priceScale("right").applyOptions({
                scaleMargins: { top: 0.03, bottom: lowerTotal },
            });

            let bandTop = 1 - lowerTotal + 0.015;
            bands.forEach((bandId) => {
                const top = bandTop;
                const bottom = Math.max(0.01, 1 - top - BAND_HEIGHT);
                bandTop += BAND_HEIGHT + BAND_GAP;
                const isOsc = bandId === "rsi" || bandId === "kdj";
                this.mainChart.priceScale(bandId).applyOptions({
                    scaleMargins: { top, bottom },
                    borderVisible: false,
                    visible: isOsc,
                    autoScale: bandId !== "rsi" && bandId !== "kdj",
                });
            });

            ["volume", "macd", "rsi", "kdj"].forEach((id) => {
                if (!bands.includes(id)) {
                    this.mainChart.priceScale(id).applyOptions({
                        scaleMargins: { top: 1, bottom: 0 },
                        visible: false,
                    });
                }
            });
        }

        setIndicators(partial) {
            this.indicators = { ...this.indicators, ...partial };
            this._updateScaleLayout();
            this.updateLegend();
            this._renderTradePlanLines();
            const needsRerender = Object.keys(partial).some((k) => k !== "tradePlan");
            if (needsRerender && this._lastCandles.length) this.render(this._lastCandles);
        }

        setTradePlan(plan) {
            this._tradePlan = plan && typeof plan === "object" ? plan : null;
            this._renderTradePlanLines();
            this.updateLegend();
        }

        clearTradePlan() {
            this.setTradePlan(null);
        }

        _removeTradePlanLines() {
            if (!this._tradePlanLines.length || !this.series.candle) return;
            this._tradePlanLines.forEach((line) => {
                try { this.series.candle.removePriceLine(line); } catch (_err) { /* ignore */ }
            });
            this._tradePlanLines = [];
        }

        _renderTradePlanLines() {
            this._removeTradePlanLines();
            if (!this.indicators.tradePlan || !this._tradePlan || !this.series.candle) return;
            TRADE_PLAN_LINES.forEach((spec) => {
                const price = Number(this._tradePlan[spec.key]);
                if (!Number.isFinite(price) || price <= 0) return;
                const line = this.series.candle.createPriceLine({
                    price,
                    color: spec.color,
                    lineWidth: spec.lineWidth,
                    lineStyle: spec.lineStyle,
                    axisLabelVisible: true,
                    title: spec.title,
                });
                this._tradePlanLines.push(line);
            });
        }

        getIndicators() {
            return { ...this.indicators };
        }

        updateLegend() {
            if (!this.legendEl) return;
            const ChartTheme = global.ChartTheme || {};
            const items = [];
            if (this.indicators.ma20) items.push(`<span class="legend-item"><span class="legend-line" style="background:${ChartTheme.MA20 || "#2962ff"}"></span>MA20</span>`);
            if (this.indicators.ma60) items.push(`<span class="legend-item"><span class="legend-line" style="background:${ChartTheme.MA60 || "#f59e0b"}"></span>MA60</span>`);
            if (this.indicators.boll) items.push(`<span class="legend-item"><span class="legend-line legend-dashed" style="background:#9ca3af"></span>BOLL</span>`);
            if (this.indicators.volume) items.push(`<span class="legend-item"><span class="legend-bar legend-bar-up"></span>成交量</span>`);
            if (this.indicators.macd) items.push(`<span class="legend-item"><span class="legend-line" style="background:${ChartTheme.MACD_LINE || "#3a7bd5"}"></span>MACD</span>`);
            if (this.indicators.rsi) items.push(`<span class="legend-item"><span class="legend-line" style="background:${ChartTheme.RSI_LINE || "#90caf9"}"></span>RSI</span>`);
            if (this.indicators.kdj) items.push(`<span class="legend-item"><span class="legend-line" style="background:${ChartTheme.KDJ_K || "#90caf9"}"></span>KDJ</span>`);
            if (this.indicators.tradePlan && this._tradePlan) {
                items.push(`<span class="legend-item"><span class="legend-line" style="background:#42a5f5"></span>交易计划</span>`);
            }
            this.legendEl.innerHTML = items.length ? items.join("") : `<span class="legend-item legend-empty">未选择指标</span>`;
        }

        _applySeries(series, enabled, data) {
            if (!series) return;
            series.setData(enabled ? (data || []) : []);
        }

        resize() {
            if (this.mainChart && this.mainEl) {
                this.mainChart.applyOptions({
                    width: Math.max(320, this.mainEl.clientWidth || 320),
                    height: Math.max(400, this.mainEl.clientHeight || this.mainHeight),
                });
            }
        }

        clearSeries() {
            Object.values(this.series).forEach((s) => { if (s && s.setData) s.setData([]); });
        }

        render(candles) {
            const ChartIndicators = global.ChartIndicators;
            if (!this.mainChart || !this.series.candle || !ChartIndicators) return;
            const normalized = ChartIndicators.normalizeCandles(candles);
            this._lastCandles = normalized;
            if (!normalized.length) {
                this.clearSeries();
                if (this.hintEl) this.hintEl.textContent = "暂无 K 线数据";
                return;
            }
            const sorted = [...normalized].sort((a, b) => a.tsSec - b.tsSec);
            const ind = this.indicators;

            this.series.candle.setData(sorted.map((c) => ({
                time: this.toTime(c.tsSec),
                open: c.open,
                high: c.high,
                low: c.low,
                close: c.close,
            })));

            this._applySeries(this.series.ma20, ind.ma20, ChartIndicators.buildMovingAverageData(sorted, 20, this.toTime));
            this._applySeries(this.series.ma60, ind.ma60, ChartIndicators.buildMovingAverageData(sorted, 60, this.toTime));

            const bb = ChartIndicators.buildBollingerBands(sorted, this.toTime);
            this._applySeries(this.series.bbUpper, ind.boll, bb.upper);
            this._applySeries(this.series.bbMiddle, ind.boll, bb.middle);
            this._applySeries(this.series.bbLower, ind.boll, bb.lower);
            this._applySeries(this.series.volume, ind.volume, ChartIndicators.buildVolumeData(sorted, this.toTime));

            const macd = ChartIndicators.buildMacdData(sorted, this.toTime);
            this._applySeries(this.series.macdLine, ind.macd, macd.macdLine);
            this._applySeries(this.series.macdSignal, ind.macd, macd.signalLine);
            this._applySeries(this.series.macdHist, ind.macd, macd.histogram);

            const rsi = ChartIndicators.buildRsiData(sorted, this.toTime);
            this._applySeries(this.series.rsiLine, ind.rsi, rsi.rsi);
            this._applySeries(this.series.rsiUpper, ind.rsi, rsi.upper);
            this._applySeries(this.series.rsiLower, ind.rsi, rsi.lower);

            const kdj = ChartIndicators.buildKdjData(sorted, this.toTime);
            this._applySeries(this.series.kdjK, ind.kdj, kdj.k);
            this._applySeries(this.series.kdjD, ind.kdj, kdj.d);
            this._applySeries(this.series.kdjJ, ind.kdj, kdj.j);

            if (this.hintEl) this.hintEl.textContent = "";
            this.mainChart.timeScale().fitContent();
            this._renderTradePlanLines();
        }
    }

    global.KlineChartStack = KlineChartStack;
    global.KLINE_DEFAULT_INDICATORS = DEFAULT_INDICATORS;
})(typeof window !== "undefined" ? window : globalThis);
