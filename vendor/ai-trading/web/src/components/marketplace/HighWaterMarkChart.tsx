/**
 * HighWaterMarkChart — equity-curve + high-water-mark step line.
 *
 * Sprint S16 PR-2. Pure SVG, no chart library dependency. Renders:
 *   - Equity curve (cumulative_pnl_usd over time) as a polyline.
 *   - HWM step line (high_water_mark_usd as it evolves period to
 *     period) as a dashed monotonic-up polyline.
 *   - Axis ticks: first / last date + 0 / max-PnL labels.
 *
 * Reads `PerformanceReport[]` directly (Decimal-as-string), parses
 * once with Number() for plotting. Designed for the `/employment/:id`
 * Hero card per S16 plan §UI-UX 详情页.
 *
 * Empty-state: shows a "no data yet" muted message instead of an
 * empty rectangle — first-week employments have no reports.
 */

import { useMemo } from "react";

import type { PerformanceReport } from "../../types";

export interface HighWaterMarkChartProps {
  reports: PerformanceReport[];
  /** SVG viewport width in pixels. Default 640. */
  width?: number;
  /** SVG viewport height in pixels. Default 240. */
  height?: number;
  /** Aria-label for accessibility. */
  label?: string;
}

const PADDING = { top: 16, right: 32, bottom: 24, left: 56 };

/**
 * Build SVG coordinate transformers from data extents + viewport.
 * Returns x(t) and y(value) mappers, plus the data extents themselves.
 */
function buildScales(
  reports: PerformanceReport[],
  width: number,
  height: number,
) {
  const innerW = width - PADDING.left - PADDING.right;
  const innerH = height - PADDING.top - PADDING.bottom;

  const xs = reports.map((r) => new Date(r.period_end).getTime());
  const ys = reports.flatMap((r) => [
    Number(r.cumulative_pnl_usd),
    Number(r.high_water_mark_usd),
  ]);

  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const yMinRaw = Math.min(0, ...ys);
  const yMaxRaw = Math.max(0, ...ys);
  // Pad y so the curve never hugs the top edge.
  const yPad = Math.max((yMaxRaw - yMinRaw) * 0.1, 1);
  const yMin = yMinRaw - yPad;
  const yMax = yMaxRaw + yPad;

  const xRange = xMax - xMin || 1;
  const yRange = yMax - yMin || 1;

  return {
    x: (t: number) => PADDING.left + ((t - xMin) / xRange) * innerW,
    y: (v: number) =>
      PADDING.top + innerH - ((v - yMin) / yRange) * innerH,
    extents: { xMin, xMax, yMin, yMax },
  };
}

function formatUsd(value: number): string {
  const sign = value < 0 ? "-" : "";
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${sign}${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${sign}${(abs / 1_000).toFixed(1)}k`;
  return `${sign}${abs.toFixed(0)}`;
}

function formatDate(ts: number): string {
  const d = new Date(ts);
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${m}/${day}`;
}

export function HighWaterMarkChart({
  reports,
  width = 640,
  height = 240,
  label = "Equity curve with high-water mark",
}: HighWaterMarkChartProps) {
  const sorted = useMemo(
    () =>
      [...reports].sort(
        (a, b) =>
          new Date(a.period_end).getTime() - new Date(b.period_end).getTime(),
      ),
    [reports],
  );

  if (sorted.length === 0) {
    return (
      <div
        role="img"
        aria-label={label}
        className="hwm-chart hwm-chart-empty"
        style={{
          width,
          height,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--text-3)",
          border: "1px dashed var(--bg-elevated)",
          borderRadius: 8,
        }}
        data-testid="hwm-chart-empty"
      >
        No settlements yet — chart updates after the first weekly close.
      </div>
    );
  }

  const scales = buildScales(sorted, width, height);
  const equityPoints = sorted
    .map((r) => `${scales.x(new Date(r.period_end).getTime())},${scales.y(Number(r.cumulative_pnl_usd))}`)
    .join(" ");
  const hwmPoints = sorted
    .map((r) => `${scales.x(new Date(r.period_end).getTime())},${scales.y(Number(r.high_water_mark_usd))}`)
    .join(" ");

  const { xMin, xMax, yMin, yMax } = scales.extents;

  return (
    <svg
      role="img"
      aria-label={label}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      data-testid="hwm-chart"
      style={{ background: "var(--bg-surface)", borderRadius: 8 }}
    >
      {/* zero line */}
      <line
        x1={PADDING.left}
        y1={scales.y(0)}
        x2={width - PADDING.right}
        y2={scales.y(0)}
        stroke="var(--bg-elevated)"
        strokeWidth={1}
      />
      {/* equity curve */}
      <polyline
        points={equityPoints}
        fill="none"
        stroke="var(--primary)"
        strokeWidth={2}
        data-testid="hwm-chart-equity"
      />
      {/* HWM step line */}
      <polyline
        points={hwmPoints}
        fill="none"
        stroke="var(--cyan)"
        strokeWidth={1.5}
        strokeDasharray="4 4"
        data-testid="hwm-chart-hwm"
      />
      {/* Y-axis labels */}
      <text
        x={PADDING.left - 8}
        y={scales.y(yMax)}
        textAnchor="end"
        fontSize="11"
        fill="var(--text-3)"
        fontFamily="JetBrains Mono, monospace"
      >
        {formatUsd(yMax)}
      </text>
      <text
        x={PADDING.left - 8}
        y={scales.y(yMin)}
        textAnchor="end"
        fontSize="11"
        fill="var(--text-3)"
        fontFamily="JetBrains Mono, monospace"
      >
        {formatUsd(yMin)}
      </text>
      {/* X-axis labels */}
      <text
        x={PADDING.left}
        y={height - 8}
        textAnchor="start"
        fontSize="11"
        fill="var(--text-3)"
        fontFamily="JetBrains Mono, monospace"
      >
        {formatDate(xMin)}
      </text>
      <text
        x={width - PADDING.right}
        y={height - 8}
        textAnchor="end"
        fontSize="11"
        fill="var(--text-3)"
        fontFamily="JetBrains Mono, monospace"
      >
        {formatDate(xMax)}
      </text>
    </svg>
  );
}
