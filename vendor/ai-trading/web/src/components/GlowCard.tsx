import type { ReactNode, CSSProperties } from "react";

type GlowColor = "blue" | "cyan" | "purple" | "green";

interface GlowCardProps {
  title?: ReactNode;
  extra?: ReactNode;
  color?: GlowColor;
  children: ReactNode;
  style?: CSSProperties;
  bodyStyle?: CSSProperties;
  className?: string;
  onClick?: () => void;
}

const COLOR_ICON: Record<GlowColor, string> = {
  blue:   "#22d3ee",
  cyan:   "#00d4ff",
  purple: "#a855f7",
  green:  "#00ff88",
};

export default function GlowCard({
  title,
  extra,
  color = "blue",
  children,
  style,
  bodyStyle,
  className = "",
  onClick,
}: GlowCardProps) {
  const accent = COLOR_ICON[color];

  return (
    <div
      className={`glow-border-${color} tech-panel ${className}`}
      onClick={onClick}
      style={{
        background: "rgba(255,255,255,0.08)",
        backdropFilter: "blur(20px) saturate(1.3)",
        WebkitBackdropFilter: "blur(20px) saturate(1.3)",
        borderRadius: "var(--radius-lg)",
        border: "1px solid rgba(255,255,255,0.12)",
        overflow: "hidden",
        ...style,
      }}
    >
      {title != null && (
        <div className="glow-card-header">
          <div className="glow-card-title">
            <span
              style={{
                display: "inline-block",
                width: 3,
                height: 14,
                borderRadius: 2,
                background: accent,
                boxShadow: `0 0 8px ${accent}`,
                flexShrink: 0,
              }}
            />
            {title}
          </div>
          {extra && (
            <div style={{ fontSize: 12, color: "var(--text-2)" }}>{extra}</div>
          )}
        </div>
      )}
      <div className="glow-card-body" style={bodyStyle}>
        {children}
      </div>
    </div>
  );
}
