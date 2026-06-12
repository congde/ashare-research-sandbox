import type { CSSProperties } from "react";

interface DataPoint {
  label: string;
  value: number;
}

interface SparkBarChartProps {
  data: DataPoint[];
  color?: string;
  height?: number;
  style?: CSSProperties;
}

/** Lightweight SVG bar chart — no external dependency */
export function SparkBarChart({
  data,
  color = "#00d4ff",
  height = 80,
  style,
}: SparkBarChartProps) {
  if (!data || data.length === 0) return null;

  const max = Math.max(...data.map((d) => d.value), 0.00001);
  const W = 600;
  const H = height - 24; // leave room for labels
  const barW = Math.min(36, Math.max(4, (W / data.length) * 0.55));
  const gap = W / data.length;

  return (
    <div style={{ width: "100%", ...style }}>
      <svg
        viewBox={`0 0 ${W} ${H + 24}`}
        preserveAspectRatio="xMidYMid meet"
        style={{ width: "100%", height }}
      >
        <defs>
          <linearGradient id={`bar-grad-${color.replace("#", "")}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.9} />
            <stop offset="100%" stopColor={color} stopOpacity={0.35} />
          </linearGradient>
        </defs>
        {/* baseline */}
        <line x1={0} y1={H} x2={W} y2={H} stroke="rgba(255,255,255,0.08)" strokeWidth={1} />

        {data.map((d, i) => {
          const bh = Math.max(2, (d.value / max) * H);
          const x = i * gap + gap / 2 - barW / 2;
          const y = H - bh;
          const isLast = i === data.length - 1;
          return (
            <g key={i}>
              <rect
                x={x} y={y} width={barW} height={bh}
                rx={3} ry={3}
                fill={`url(#bar-grad-${color.replace("#", "")})`}
              />
              {/* x-axis label: first, last, and every ~5th */}
              {(i === 0 || isLast || i % Math.ceil(data.length / 6) === 0) && (
                <text
                  x={i * gap + gap / 2}
                  y={H + 16}
                  textAnchor="middle"
                  fontSize={9}
                  fill="rgba(255,255,255,0.35)"
                >
                  {d.label.slice(5)} {/* show MM-DD */}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

interface SparkLineProps {
  data: DataPoint[];
  color?: string;
  height?: number;
  style?: CSSProperties;
}

/** Lightweight SVG sparkline with area fill */
export function SparkLine({
  data,
  color = "#22d3ee",
  height = 56,
  style,
}: SparkLineProps) {
  if (!data || data.length < 2) return null;

  const max = Math.max(...data.map((d) => d.value), 0.00001);
  const min = Math.min(...data.map((d) => d.value));
  const range = max - min || 1;
  const W = 200;
  const H = height - 4;

  const pts = data.map((d, i) => ({
    x: (i / (data.length - 1)) * W,
    y: H - ((d.value - min) / range) * H,
  }));

  const linePath = pts.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  const areaPath = `${linePath} L${W},${H} L0,${H} Z`;

  return (
    <div style={{ width: "100%", ...style }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        style={{ width: "100%", height, display: "block" }}
      >
        <defs>
          <linearGradient id={`area-${color.replace("#", "")}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.3} />
            <stop offset="100%" stopColor={color} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <path d={areaPath} fill={`url(#area-${color.replace("#", "")})`} />
        <path d={linePath} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" />
      </svg>
    </div>
  );
}
