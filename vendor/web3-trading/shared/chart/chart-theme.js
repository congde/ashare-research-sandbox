/**
 * Shared chart theme — single source for Python templates + frontend constants.
 * Color tokens also live in chart-theme.json (keep both in sync).
 */
(function (global) {
    const ChartTheme = {
        BG: "#1e222d",
        TEXT: "#d9d9d9",
        GRID: "#2e3241",
        BORDER: "#2e3241",
        CANDLE_UP: "#ff5555",
        CANDLE_DOWN: "#32a852",
        MA20: "#2962ff",
        MA60: "#f59e0b",
        BOLL: "rgba(140, 148, 170, 0.65)",
        MACD_LINE: "#3a7bd5",
        MACD_SIGNAL: "#ff9800",
        RSI_LINE: "#90caf9",
        RSI_UPPER: "#ef5350",
        RSI_LOWER: "#26a69a",
        KDJ_K: "#90caf9",
        KDJ_D: "#f48fb1",
        KDJ_J: "#80deea",
        LINE_PALETTE: ["#2962ff", "#ff9800", "#ef5350", "#8b5cf6", "#26a69a", "#e91e63", "#6c7284", "#ffd700"],

        crosshairMode() {
            return global.LightweightCharts?.CrosshairMode?.Normal ?? 1;
        },

        baseOptions(width, height, extra = {}) {
            return {
                width,
                height,
                layout: { background: { color: this.BG }, textColor: this.TEXT },
                grid: { vertLines: { color: this.GRID }, horzLines: { color: this.GRID } },
                crosshair: {
                    mode: this.crosshairMode(),
                    vertLine: { color: "#555", style: 1, visible: true, labelVisible: false },
                    horzLine: { color: "#555", style: 1, visible: true, labelVisible: true },
                },
                rightPriceScale: { borderColor: this.BORDER },
                timeScale: {
                    borderColor: this.BORDER,
                    timeVisible: true,
                    secondsVisible: false,
                    barSpacing: 6,
                    rightOffset: 10,
                },
                ...extra,
            };
        },

        candleSeriesOptions() {
            return {
                upColor: this.CANDLE_UP,
                downColor: this.CANDLE_DOWN,
                borderVisible: false,
                wickUpColor: this.CANDLE_UP,
                wickDownColor: this.CANDLE_DOWN,
            };
        },

        macdSubOptions(width, height = 140) {
            return this.subChartOptions(width, height);
        },

        subChartOptions(width, height = 140) {
            return this.baseOptions(width, height, {
                rightPriceScale: { borderColor: this.BORDER, scaleMargins: { top: 0.1, bottom: 0.1 } },
                timeScale: {
                    borderColor: this.BORDER,
                    timeVisible: false,
                    secondsVisible: false,
                    visible: false,
                    borderVisible: false,
                    barSpacing: 6,
                    rightOffset: 10,
                },
            });
        },

        macdHistColor(value) {
            return value >= 0 ? "rgba(255, 85, 85, 0.65)" : "rgba(50, 168, 82, 0.65)";
        },

        volumeColor(isUp) {
            return isUp ? "rgba(255, 85, 85, 0.55)" : "rgba(50, 168, 82, 0.55)";
        },
    };

    global.ChartTheme = ChartTheme;
})(typeof window !== "undefined" ? window : globalThis);
