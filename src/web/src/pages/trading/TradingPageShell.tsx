import type { CSSProperties, ReactNode } from "react";
import { MonoNumber, QuantGlowCard } from "../../quant-atelier";
import "./trading.css";

export type Tone = "profit" | "loss" | "neutral" | "ai";

interface TradingPageShellProps {
  eyebrow: string;
  title: string;
  description: string;
  actions?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
}

interface SectionHeaderProps {
  title: string;
  description?: string;
  action?: ReactNode;
}

interface MetricTileProps {
  label: string;
  value: number | string | ReactNode;
  subtle?: string;
  tone?: Tone;
  kind?: "usd" | "pct" | "plain" | "qty";
  precision?: number;
  showSign?: boolean;
}

export function TradingPageShell({
  eyebrow,
  title,
  description,
  actions,
  aside,
  children,
}: TradingPageShellProps) {
  return (
    <div className="trading-shell">
      <section className={`trading-hero${aside ? "" : " trading-hero-single"}`}>
        <div className="trading-heading">
          <div>
            <div className="trading-eyebrow">{eyebrow}</div>
            <div className="trading-title-row">
              <div>
                <h1>{title}</h1>
                <p className="trading-description">{description}</p>
              </div>
              {actions && <div className="trading-actions">{actions}</div>}
            </div>
          </div>
        </div>
        {aside && <div className="trading-hero-aside">{aside}</div>}
      </section>
      {children}
    </div>
  );
}

export function SectionHeader({ title, description, action }: SectionHeaderProps) {
  return (
    <div className="trading-section-title">
      <div>
        <h2>{title}</h2>
        {description && <p>{description}</p>}
      </div>
      {action}
    </div>
  );
}

export function StatusPill({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`trading-status-pill trading-pill-${tone}`}>{children}</span>;
}

export function MetricTile({
  label,
  value,
  subtle,
  tone = "neutral",
  kind = "plain",
  precision,
  showSign,
}: MetricTileProps) {
  const numericTone =
    tone === "profit" || tone === "loss" || tone === "neutral" ? tone : "neutral";

  return (
    <div className="trading-metric-tile">
      <div className="trading-metric-label">{label}</div>
      {typeof value === "number" ? (
        <MonoNumber
          value={value}
          kind={kind}
          tone={numericTone}
          size="lg"
          precision={precision}
          showSign={showSign}
        />
      ) : typeof value === "string" ? (
        <strong className={`trading-metric-value trading-tone-${tone}`}>{value}</strong>
      ) : (
        value
      )}
      {subtle && <span className="trading-metric-subtle">{subtle}</span>}
    </div>
  );
}

export function SignalRow({
  title,
  meta,
  badge,
  style,
}: {
  title: string;
  meta: string;
  badge?: ReactNode;
  style?: CSSProperties;
}) {
  return (
    <div className="trading-list-row" style={style}>
      <div>
        <strong>{title}</strong>
        <span>{meta}</span>
      </div>
      {badge}
    </div>
  );
}

export function ScoreRail({ value }: { value: number }) {
  const width = Math.max(0, Math.min(100, value));
  return (
    <div className="trading-score-rail" aria-label={`score ${width}`}>
      <span style={{ width: `${width}%` }} />
    </div>
  );
}

export function Sparkline({ values, tone = "profit" }: { values: number[]; tone?: Tone }) {
  const width = 260;
  const height = 72;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = max - min || 1;
  const points = values
    .map((value, index) => {
      const x = (index / Math.max(values.length - 1, 1)) * width;
      const y = height - ((value - min) / spread) * (height - 10) - 5;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <svg className="trading-sparkline" viewBox={`0 0 ${width} ${height}`} role="img">
      <polyline
        points={points}
        fill="none"
        stroke={`var(--qa-${tone})`}
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="3"
      />
      <line
        x1="0"
        x2={width}
        y1={height - 8}
        y2={height - 8}
        stroke="rgba(148, 163, 184, 0.22)"
      />
    </svg>
  );
}

export { QuantGlowCard };
