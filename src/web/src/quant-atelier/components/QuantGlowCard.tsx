/**
 * QuantGlowCard — phosphor card with optional "live" breathing border.
 *
 * Distinct from the WorkDAO GlowCard; the latter is preserved for
 * legacy pages while this one matches the Quant Atelier token system.
 */

import type { CSSProperties, ReactNode } from 'react'

interface QuantGlowCardProps {
  children: ReactNode
  variant?: 'default' | 'live' | 'critical'
  title?: ReactNode
  badge?: ReactNode
  onClick?: () => void
  className?: string
  style?: CSSProperties
}

export function QuantGlowCard({
  children,
  variant = 'default',
  title,
  badge,
  onClick,
  className,
  style,
}: QuantGlowCardProps) {
  return (
    <article
      className={`qa-glow-card ${variant === "critical" ? "qa-glow-critical" : ""} ${className ?? ""} ${variant === "live" ? "qa-breathe" : ""}`}
      onClick={onClick}
      style={{
        cursor: onClick ? "pointer" : "default",
        ...style,
      }}
    >
      {(title || badge) && (
        <header
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
            marginBottom: 16,
          }}
        >
          <div style={{ flex: 1 }}>{title}</div>
          {badge && <div>{badge}</div>}
        </header>
      )}
      {children}
    </article>
  )
}

export default QuantGlowCard
