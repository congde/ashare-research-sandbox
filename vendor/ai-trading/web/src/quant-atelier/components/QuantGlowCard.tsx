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

const VARIANT_BORDER: Record<NonNullable<QuantGlowCardProps['variant']>, string> = {
  default: 'var(--qa-line-subtle)',
  live: 'var(--qa-line-subtle)',
  critical: 'var(--qa-loss)',
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
      className={`${className ?? ''} ${variant === 'live' ? 'qa-breathe' : ''}`}
      onClick={onClick}
      style={{
        background: 'var(--qa-bg-surface)',
        border: `1px solid ${VARIANT_BORDER[variant]}`,
        borderRadius: 8,
        padding: 24,
        cursor: onClick ? 'pointer' : 'default',
        transition: 'transform 0.2s ease, border-color 0.2s ease',
        animation: variant === 'live' ? 'qa-breathe 4s ease-in-out infinite' : undefined,
        boxShadow:
          variant === 'critical'
            ? '0 0 0 1px var(--qa-loss), 0 0 24px -8px var(--qa-loss)'
            : 'none',
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
