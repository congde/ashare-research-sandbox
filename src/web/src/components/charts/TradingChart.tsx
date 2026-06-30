import { useEffect, useRef } from "react";
import {
  CrosshairMode,
  createChart,
  type IChartApi,
  type CandlestickData,
  type LineData,
} from "lightweight-charts";
import { useThemeMode } from "../../contexts/ThemeContext";
import type { CurvePoint, RollingTrade, Trade } from "../../types";
import { baseChartOptions, chartPalette } from "./chartTheme";
import {
  curveToCandles,
  curveToEquitySeries,
  curveToMaSeries,
  rollingTradesToMarkers,
  tradesToMarkers,
} from "./series";
import "./trading-chart.css";

export interface TradingChartProps {
  curve: CurvePoint[];
  trades?: Trade[];
  rollingTrades?: RollingTrade[];
  height?: number;
  variant?: "compact" | "standard" | "mini";
  showEquity?: boolean;
  className?: string;
}

export default function TradingChart({
  curve,
  trades = [],
  rollingTrades = [],
  height,
  variant = "standard",
  showEquity = false,
  className,
}: TradingChartProps) {
  const { mode } = useThemeMode();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);

  const resolvedHeight = height ?? (variant === "mini" ? 52 : variant === "compact" ? 196 : 320);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || curve.length === 0) {
      return;
    }

    container.replaceChildren();
    const colors = chartPalette();
    const width = Math.max(container.clientWidth, 120);
    const chart = createChart(container, {
      ...baseChartOptions(width, resolvedHeight),
      crosshair: {
        mode: variant === "mini" ? CrosshairMode.Hidden : CrosshairMode.Normal,
        vertLine: { visible: variant !== "mini", color: colors.crosshair },
        horzLine: { visible: variant !== "mini", color: colors.crosshair },
      },
      timeScale: {
        ...baseChartOptions(width, resolvedHeight).timeScale,
        visible: variant !== "mini",
      },
      rightPriceScale: {
        ...baseChartOptions(width, resolvedHeight).rightPriceScale,
        visible: variant !== "mini",
      },
      grid: {
        vertLines: { visible: variant !== "mini", color: colors.grid },
        horzLines: { visible: variant !== "mini", color: colors.grid },
      },
      handleScale: variant !== "mini",
      handleScroll: variant !== "mini",
    });

    chartRef.current = chart;

    const candleSeries = chart.addCandlestickSeries({
      upColor: colors.up,
      downColor: colors.down,
      borderUpColor: colors.up,
      borderDownColor: colors.down,
      wickUpColor: colors.up,
      wickDownColor: colors.down,
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    });
    candleSeries.setData(curveToCandles(curve) as CandlestickData[]);

    if (variant !== "mini") {
      const shortMa = curveToMaSeries(curve, "short_ma");
      if (shortMa.length) {
        const shortSeries = chart.addLineSeries({
          color: colors.maShort,
          lineWidth: 2,
          title: "MA短",
          priceLineVisible: false,
          lastValueVisible: false,
        });
        shortSeries.setData(shortMa as LineData[]);
      }

      const longMa = curveToMaSeries(curve, "long_ma");
      if (longMa.length) {
        const longSeries = chart.addLineSeries({
          color: colors.maLong,
          lineWidth: 2,
          title: "MA长",
          priceLineVisible: false,
          lastValueVisible: false,
        });
        longSeries.setData(longMa as LineData[]);
      }
    }

    if (showEquity && variant !== "mini") {
      const equitySeries = chart.addLineSeries({
        color: colors.equity,
        lineWidth: 2,
        title: "权益",
        priceScaleId: "equity",
        priceLineVisible: false,
        lastValueVisible: variant !== "compact",
      });
      chart.priceScale("equity").applyOptions({
        scaleMargins: { top: variant === "compact" ? 0.82 : 0.75, bottom: 0 },
        borderColor: colors.border,
      });
      equitySeries.setData(curveToEquitySeries(curve) as LineData[]);

      const equityMarkers =
        rollingTrades.length > 0
          ? rollingTradesToMarkers(rollingTrades)
          : tradesToMarkers(trades);
      if (equityMarkers.length) {
        equitySeries.setMarkers(equityMarkers);
      }
    }

    const priceMarkers =
      rollingTrades.length > 0
        ? rollingTradesToMarkers(rollingTrades)
        : tradesToMarkers(trades);
    if (priceMarkers.length && variant !== "mini") {
      candleSeries.setMarkers(priceMarkers);
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
  }, [curve, trades, rollingTrades, mode, resolvedHeight, showEquity, variant]);

  if (!curve.length) {
    return <div className={`trading-chart trading-chart-empty ${className ?? ""}`}>暂无 K 线数据</div>;
  }

  return (
    <div
      className={`trading-chart trading-chart-${variant} ${className ?? ""}`}
      style={{ height: resolvedHeight }}
    >
      <div ref={containerRef} className="trading-chart-canvas" />
    </div>
  );
}
