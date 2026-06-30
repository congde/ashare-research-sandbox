import { useEffect, useRef } from "react";
import {
  ColorType,
  CrosshairMode,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  createChart,
} from "lightweight-charts";

import type { KlineCandle, TradePlan } from "../../types";
import "./trading-chart.css";

type ChartMode = "light" | "dark";

interface KlineAnalysisChartProps {
  candles: KlineCandle[];
  tradePlan?: TradePlan | null;
  showMa20?: boolean;
  showMa60?: boolean;
  showVolume?: boolean;
  showPriceLines?: boolean;
  height?: number;
  mode?: ChartMode;
  className?: string;
}

function beijingTime(tsSec: number) {
  return (Math.floor(tsSec) + 8 * 3600) as LineData["time"];
}

function sma(values: number[], window: number): Array<number | null> {
  return values.map((_, index) => {
    if (index + 1 < window) return null;
    const sample = values.slice(index + 1 - window, index + 1);
    return sample.reduce((sum, item) => sum + item, 0) / window;
  });
}

function formatPriceLine(value?: number | null) {
  if (value == null || Number.isNaN(value)) return undefined;
  return value;
}

export function KlineAnalysisChart({
  candles,
  tradePlan,
  showMa20 = true,
  showMa60 = true,
  showVolume = true,
  showPriceLines = true,
  height = 420,
  mode = "dark",
  className,
}: KlineAnalysisChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !candles.length) return;

    const colors =
      mode === "dark"
        ? {
            background: "#0f1419",
            text: "#9aa7b8",
            grid: "rgba(148, 163, 184, 0.08)",
            border: "rgba(148, 163, 184, 0.2)",
            up: "#22c55e",
            down: "#ef4444",
            ma20: "#60a5fa",
            ma60: "#f59e0b",
            volumeUp: "rgba(34, 197, 94, 0.45)",
            volumeDown: "rgba(239, 68, 68, 0.45)",
          }
        : {
            background: "#ffffff",
            text: "#64748b",
            grid: "rgba(100, 116, 139, 0.08)",
            border: "rgba(100, 116, 139, 0.2)",
            up: "#16a34a",
            down: "#dc2626",
            ma20: "#2563eb",
            ma60: "#d97706",
            volumeUp: "rgba(22, 163, 74, 0.35)",
            volumeDown: "rgba(220, 38, 38, 0.35)",
          };

    const chart = createChart(container, {
      width: container.clientWidth,
      height,
      layout: {
        background: { type: ColorType.Solid, color: colors.background },
        textColor: colors.text,
      },
      grid: {
        vertLines: { color: colors.grid },
        horzLines: { color: colors.grid },
      },
      rightPriceScale: { borderColor: colors.border },
      timeScale: { borderColor: colors.border, timeVisible: true, secondsVisible: false },
      crosshair: { mode: CrosshairMode.Normal },
    });
    chartRef.current = chart;

    const candleSeries = chart.addCandlestickSeries({
      upColor: colors.up,
      downColor: colors.down,
      borderUpColor: colors.up,
      borderDownColor: colors.down,
      wickUpColor: colors.up,
      wickDownColor: colors.down,
    });

    const candleData: CandlestickData[] = candles.map((item) => ({
      time: beijingTime(item.tsSec),
      open: item.open,
      high: item.high,
      low: item.low,
      close: item.close,
    }));
    candleSeries.setData(candleData);

    const closes = candles.map((item) => item.close);
    if (showMa20) {
      const ma20 = sma(closes, 20);
      const line = chart.addLineSeries({
        color: colors.ma20,
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      line.setData(
        ma20
          .map((value, index) => (value == null ? null : { time: beijingTime(candles[index].tsSec), value }))
          .filter(Boolean) as LineData[],
      );
    }
    if (showMa60) {
      const ma60 = sma(closes, 60);
      const line = chart.addLineSeries({
        color: colors.ma60,
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      line.setData(
        ma60
          .map((value, index) => (value == null ? null : { time: beijingTime(candles[index].tsSec), value }))
          .filter(Boolean) as LineData[],
      );
    }

    let volumeSeries: ISeriesApi<"Histogram"> | null = null;
    if (showVolume) {
      volumeSeries = chart.addHistogramSeries({
        priceFormat: { type: "volume" },
        priceScaleId: "volume",
      });
      chart.priceScale("volume").applyOptions({
        scaleMargins: { top: 0.8, bottom: 0 },
      });
      volumeSeries.setData(
        candles.map((item) => ({
          time: beijingTime(item.tsSec),
          value: item.volume,
          color: item.close >= item.open ? colors.volumeUp : colors.volumeDown,
        })) as HistogramData[],
      );
    }

    if (showPriceLines && tradePlan) {
      const lines = [
        { price: tradePlan.entryLow, title: "入场低", color: "#3b82f6" },
        { price: tradePlan.stopLoss, title: "支撑/止损", color: "#6366f1" },
        { price: tradePlan.target1, title: "目标1", color: "#22c55e" },
        { price: tradePlan.target2, title: "目标2", color: "#16a34a" },
      ];
      for (const entry of lines) {
        const price = formatPriceLine(entry.price);
        if (price != null) {
          candleSeries.createPriceLine({
            price,
            color: entry.color,
            lineWidth: 1,
            lineStyle: 2,
            axisLabelVisible: true,
            title: entry.title,
          });
        }
      }
    }

    chart.timeScale().fitContent();

    const resizeObserver = new ResizeObserver(() => {
      if (container.clientWidth > 0) {
        chart.applyOptions({ width: container.clientWidth });
        chart.timeScale().fitContent();
      }
    });
    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [candles, tradePlan, showMa20, showMa60, showVolume, showPriceLines, height, mode]);

  if (!candles.length) {
    return <div className={`trading-chart trading-chart-empty ${className ?? ""}`}>暂无 K 线数据</div>;
  }

  return (
    <div className={`trading-chart trading-chart-standard ${className ?? ""}`} style={{ height }}>
      <div ref={containerRef} className="trading-chart-canvas" />
    </div>
  );
}
