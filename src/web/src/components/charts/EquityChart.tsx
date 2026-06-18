import { LineStyle, createChart, type IChartApi, type LineData } from "lightweight-charts";
import { useEffect, useRef } from "react";
import { useThemeMode } from "../../contexts/ThemeContext";
import type { RollingEquityPoint, RollingTrade } from "../../types";
import { baseChartOptions, chartPalette } from "./chartTheme";
import { rollingTradesToMarkers } from "./series";
import "./trading-chart.css";

export interface EquityChartProps {
  equityCurve: RollingEquityPoint[];
  trades?: RollingTrade[];
  height?: number;
  className?: string;
}

export default function EquityChart({
  equityCurve,
  trades = [],
  height = 280,
  className,
}: EquityChartProps) {
  const { mode } = useThemeMode();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || equityCurve.length === 0) {
      return;
    }

    container.replaceChildren();
    const colors = chartPalette();
    const width = Math.max(container.clientWidth, 120);
    const chart = createChart(container, baseChartOptions(width, height));
    chartRef.current = chart;

    const equitySeries = chart.addLineSeries({
      color: colors.equity,
      lineWidth: 2,
      title: "权益",
      priceLineVisible: false,
      lastValueVisible: true,
    });
    equitySeries.setData(
      equityCurve.map((point) => ({
        time: point.ts,
        value: point.equity,
      })) as LineData[],
    );

    const hasDrawdown = equityCurve.some((point) => point.drawdown > 0);
    if (hasDrawdown) {
      const ddSeries = chart.addLineSeries({
        color: colors.down,
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        title: "回撤%",
        priceScaleId: "drawdown",
        priceLineVisible: false,
        lastValueVisible: false,
      });
      chart.priceScale("drawdown").applyOptions({
        scaleMargins: { top: 0.72, bottom: 0 },
        borderColor: colors.border,
      });
      ddSeries.setData(
        equityCurve.map((point) => ({
          time: point.ts,
          value: -point.drawdown,
        })) as LineData[],
      );
    }

    const markers = rollingTradesToMarkers(trades);
    if (markers.length) {
      equitySeries.setMarkers(markers);
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
  }, [equityCurve, trades, mode, height]);

  if (!equityCurve.length) {
    return (
      <div className={`trading-chart trading-chart-empty ${className ?? ""}`}>
        暂无权益曲线数据
      </div>
    );
  }

  return (
    <div className={`trading-chart trading-chart-standard ${className ?? ""}`} style={{ height }}>
      <div ref={containerRef} className="trading-chart-canvas" />
    </div>
  );
}
