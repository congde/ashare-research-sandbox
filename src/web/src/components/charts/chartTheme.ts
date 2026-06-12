import type { DeepPartial, ChartOptions } from "lightweight-charts";

export function isLightTheme() {
  return document.documentElement.dataset.theme === "light";
}

export function chartPalette() {
  const light = isLightTheme();
  return {
    text: light ? "#5d695f" : "#8b92a5",
    grid: light ? "rgba(23, 33, 24, 0.06)" : "rgba(255, 255, 255, 0.06)",
    border: light ? "rgba(23, 33, 24, 0.08)" : "rgba(255, 255, 255, 0.08)",
    crosshair: light ? "rgba(29, 106, 138, 0.35)" : "rgba(34, 211, 238, 0.35)",
    up: light ? "#275d47" : "#00ffa3",
    down: light ? "#b84a2d" : "#ff2d75",
    maShort: "#22d3ee",
    maLong: "#f59e0b",
    equity: light ? "#1d6a8a" : "#22d3ee",
  };
}

export function baseChartOptions(width: number, height: number): DeepPartial<ChartOptions> {
  const colors = chartPalette();
  return {
    width,
    height,
    layout: {
      background: { color: "transparent" },
      textColor: colors.text,
      fontFamily: '"JetBrains Mono", "SF Mono", Consolas, monospace',
      fontSize: 11,
    },
    grid: {
      vertLines: { color: colors.grid },
      horzLines: { color: colors.grid },
    },
    rightPriceScale: {
      borderColor: colors.border,
      scaleMargins: { top: 0.12, bottom: 0.08 },
    },
    timeScale: {
      borderColor: colors.border,
      timeVisible: true,
      secondsVisible: false,
      fixLeftEdge: true,
      fixRightEdge: true,
    },
    crosshair: {
      vertLine: { color: colors.crosshair, labelBackgroundColor: colors.maShort },
      horzLine: { color: colors.crosshair, labelBackgroundColor: colors.maShort },
    },
    handleScroll: { vertTouchDrag: false },
  };
}
