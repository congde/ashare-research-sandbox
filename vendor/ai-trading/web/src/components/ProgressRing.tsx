interface ProgressRingProps {
  percent: number;
  color?: string;
  size?: number;
  label?: string;
  title?: string;
}

const CIRCUMFERENCE = 2 * Math.PI * 30; // r=30

export default function ProgressRing({
  percent,
  color = "#22d3ee",
  size = 80,
  label,
  title,
}: ProgressRingProps) {
  const clamped = Math.max(0, Math.min(100, percent));
  const dash = (clamped / 100) * CIRCUMFERENCE;

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
      <svg width={size} height={size} viewBox="0 0 80 80">
        {/* glow filter */}
        <defs>
          <filter id={`ring-glow-${color.replace("#", "")}`}>
            <feGaussianBlur stdDeviation="2" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* track */}
        <circle
          cx="40" cy="40" r="30"
          fill="none"
          stroke="rgba(255,255,255,0.06)"
          strokeWidth="5"
        />

        {/* progress */}
        <circle
          cx="40" cy="40" r="30"
          fill="none"
          stroke={color}
          strokeWidth="5"
          strokeLinecap="round"
          strokeDasharray={`${dash} ${CIRCUMFERENCE}`}
          strokeDashoffset={CIRCUMFERENCE * 0.25}
          filter={`url(#ring-glow-${color.replace("#", "")})`}
          style={{ transition: "stroke-dasharray 0.6s ease" }}
          transform="rotate(-90 40 40)"
        />

        {/* center value */}
        <text
          x="40" y="37"
          textAnchor="middle"
          fill={color}
          fontSize="14"
          fontWeight="700"
          fontFamily='"JetBrains Mono", monospace'
        >
          {clamped}%
        </text>
        {label && (
          <text
            x="40" y="52"
            textAnchor="middle"
            fill="rgba(255,255,255,0.45)"
            fontSize="8"
          >
            {label}
          </text>
        )}
      </svg>
      {title && (
        <div style={{ fontSize: 11, color: "var(--text-2)", textAlign: "center" }}>{title}</div>
      )}
    </div>
  );
}
