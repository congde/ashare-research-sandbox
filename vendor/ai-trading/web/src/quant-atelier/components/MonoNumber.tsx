/**
 * MonoNumber — phosphor-glowing tabular number for PNL / metrics.
 *
 * Profit gets profit-glow text shadow, loss gets loss-glow.
 * Locale-aware thousand separator. Optional sign and unit.
 */

import { useMemo, type CSSProperties } from 'react'

type Kind = 'usd' | 'pct' | 'plain' | 'qty'
type Tone = 'auto' | 'profit' | 'loss' | 'neutral' | 'mute'

interface MonoNumberProps {
  value: number
  kind?: Kind
  tone?: Tone
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl'
  showSign?: boolean
  precision?: number
  locale?: string
  className?: string
  style?: CSSProperties
  ariaLabel?: string
}

const SIZE_PX: Record<NonNullable<MonoNumberProps['size']>, number> = {
  xs: 11,
  sm: 13,
  md: 18,
  lg: 24,
  xl: 32,
}

function resolveTone(value: number, tone: Tone): Tone {
  if (tone !== 'auto') return tone
  if (value > 0) return 'profit'
  if (value < 0) return 'loss'
  return 'mute'
}

function formatValue(
  value: number,
  kind: Kind,
  showSign: boolean,
  precision: number | undefined,
  locale: string,
): string {
  const abs = Math.abs(value)
  const sign = value > 0 ? '+' : value < 0 ? '−' : ''
  const prefix = showSign ? sign : value < 0 ? '−' : ''

  if (kind === 'usd') {
    const fmt = new Intl.NumberFormat(locale, {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: precision ?? 2,
      maximumFractionDigits: precision ?? 2,
    })
    return prefix + fmt.format(abs).replace(/^-/, '')
  }

  if (kind === 'pct') {
    return `${prefix}${abs.toFixed(precision ?? 2)}%`
  }

  if (kind === 'qty') {
    return `${prefix}${abs.toLocaleString(locale, {
      minimumFractionDigits: precision ?? 0,
      maximumFractionDigits: precision ?? 8,
    })}`
  }

  return `${prefix}${abs.toLocaleString(locale, {
    minimumFractionDigits: precision ?? 0,
    maximumFractionDigits: precision ?? 4,
  })}`
}

export function MonoNumber({
  value,
  kind = 'plain',
  tone = 'auto',
  size = 'md',
  showSign = false,
  precision,
  locale = 'en-US',
  className,
  style,
  ariaLabel,
}: MonoNumberProps) {
  const finalTone = resolveTone(value, tone)
  const formatted = useMemo(
    () => formatValue(value, kind, showSign, precision, locale),
    [value, kind, showSign, precision, locale],
  )

  const color =
    finalTone === 'profit'
      ? 'var(--qa-profit)'
      : finalTone === 'loss'
        ? 'var(--qa-loss)'
        : finalTone === 'neutral'
          ? 'var(--qa-neutral)'
          : finalTone === 'mute'
            ? 'var(--qa-text-2)'
            : 'var(--qa-text-1)'

  const textShadow =
    finalTone === 'profit'
      ? 'var(--qa-profit-glow)'
      : finalTone === 'loss'
        ? 'var(--qa-loss-glow)'
        : finalTone === 'neutral'
          ? 'var(--qa-neutral-glow)'
          : 'none'

  return (
    <span
      className={`qa-mono ${className ?? ''}`}
      role="text"
      aria-label={ariaLabel ?? formatted}
      style={{
        color,
        textShadow,
        fontSize: SIZE_PX[size],
        lineHeight: 1.05,
        fontWeight: size === 'xl' || size === 'lg' ? 500 : 400,
        letterSpacing: size === 'xl' ? '-0.02em' : 0,
        ...style,
      }}
    >
      {formatted}
    </span>
  )
}

export default MonoNumber
