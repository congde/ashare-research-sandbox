import { useEffect, useRef } from "react";
import {
  CrosshairMode,
  createChart,
  type CandlestickData,
  type IChartApi,
  type LineData,
  type Time,
} from "lightweight-charts";
import { useThemeMode } from "../../contexts/ThemeContext";
import type { CurvePoint, RollingEquityPoint, RollingTrade } from "../../types";
import { baseChartOptions, chartPalette } from "./chartTheme";
import { dailyChartLocalization, formatChartTimeLabel, toChartTime } from "./chartTime";
import { curveToCandles, rollingTradesToMarkers } from "./series";
import "./trading-chart.css";

export interface BacktestComboChartProps {
  curve: CurvePoint[];
  equityCurve: RollingEquityPoint[];
  trades?: RollingTrade[];
  height?: number;
  className?: string;
}

/** K-line (top, right axis) + equity (bottom, left axis); wheel to zoom, drag to pan. */
export default function BacktestComboChart({
  curve,
  equityCurve,
  trades = [],
  height = 420,
  className,
}: BacktestComboChartProps) {
  const { mode } = useThemeMode();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || curve.length === 0) {
      return;
    }

    container.replaceChildren();
    const colors = chartPalette();
    const width = Math.max(container.clientWidth, 120);
    const chart = createChart(container, {
      ...baseChartOptions(width, height),
      localization: dailyChartLocalization,
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: colors.crosshair },
        horzLine: { color: colors.crosshair },
      },
      timeScale: {
        borderColor: colors.border,
        timeVisible: false,
        secondsVisible: false,
        fixLeftEdge: false,
        fixRightEdge: false,
        rightOffset: 8,
        tickMarkFormatter: (time: Time) => formatChartTimeLabel(time),
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: false,
      },
      handleScale: {
        axisPressedMouseMove: { time: true, price: true },
        axisDoubleClickReset: true,
        mouseWheel: true,
        pinch: true,
      },
      leftPriceScale: {
        visible: true,
        borderColor: colors.border,
      },
    });
    chartRef.current = chart;

    chart.priceScale("right").applyOptions({
      scaleMargins: { top: 0.04, bottom: 0.44 },
      borderColor: colors.border,
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: colors.up,
      downColor: colors.down,
      borderUpColor: colors.up,
      borderDownColor: colors.down,
      wickUpColor: colors.up,
      wickDownColor: colors.down,
      title: "K线",
      priceScaleId: "right",
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    });
    candleSeries.setData(curveToCandles(curve) as CandlestickData[]);

    const markers = rollingTradesToMarkers(trades);
    if (markers.length) {
      candleSeries.setMarkers(markers);
    }

    if (equityCurve.length) {
      chart.priceScale("left").applyOptions({
        scaleMargins: { top: 0.58, bottom: 0.04 },
        borderColor: colors.border,
      });

      const equitySeries = chart.addLineSeries({
        color: colors.equity,
        lineWidth: 2,
        title: "权益",
        priceScaleId: "left",
        priceLineVisible: false,
        lastValueVisible: true,
        priceFormat: { type: "price", precision: 2, minMove: 0.01 },
      });
      equitySeries.setData(
        equityCurve.map((point) => ({
          time: toChartTime(point.ts),
          value: point.equity,
        })) as LineData[],
      );
    }

    chart.timeScale().fitContent();

    const resizeObserver = new ResizeObserver(() => {
      if (container.clientWidth > 0) {
        chart.applyOptions({ width: container.clientWidth });
      }
    });
    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [curve, equityCurve, trades, mode, height]);

  if (!curve.length) {
    return (
      <div className={`trading-chart trading-chart-empty ${className ?? ""}`}>
        暂无回测图表数据
      </div>
    );
  }

  return (
    <div className={`trading-chart trading-chart-standard ${className ?? ""}`} style={{ height }}>
      <div ref={containerRef} className="trading-chart-canvas" />
    </div>
  );
}
