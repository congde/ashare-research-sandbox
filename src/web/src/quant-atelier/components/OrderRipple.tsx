/**
 * OrderRipple — emits a scale + fade ripple on click of an order
 * submit button. Disabled under prefers-reduced-motion.
 */

import { useCallback, useState, type CSSProperties, type MouseEvent, type ReactNode } from 'react'

interface OrderRippleProps {
  children: ReactNode
  onClick?: (event: MouseEvent<HTMLButtonElement>) => void
  disabled?: boolean
  tone?: 'profit' | 'loss' | 'neutral'
  ariaLabel?: string
}

interface Ripple {
  id: number
  x: number
  y: number
}

const TONE_TO_COLOR: Record<NonNullable<OrderRippleProps['tone']>, string> = {
  profit: 'var(--qa-profit)',
  loss: 'var(--qa-loss)',
  neutral: 'var(--qa-neutral)',
}

let nextRippleId = 0

export function OrderRipple({
  children,
  onClick,
  disabled = false,
  tone = 'profit',
  ariaLabel,
}: OrderRippleProps) {
  const [ripples, setRipples] = useState<readonly Ripple[]>([])

  const handleClick = useCallback(
    (event: MouseEvent<HTMLButtonElement>) => {
      if (disabled) return
      const rect = event.currentTarget.getBoundingClientRect()
      const newRipple: Ripple = {
        id: ++nextRippleId,
        x: event.clientX - rect.left,
        y: event.clientY - rect.top,
      }
      setRipples((prev) => [...prev, newRipple])
      window.setTimeout(() => {
        setRipples((prev) => prev.filter((r) => r.id !== newRipple.id))
      }, 700)
      onClick?.(event)
    },
    [disabled, onClick],
  )

  const containerStyle: CSSProperties = {
    position: 'relative',
    overflow: 'hidden',
    background: 'transparent',
    color: TONE_TO_COLOR[tone],
    border: `1px solid ${TONE_TO_COLOR[tone]}`,
    padding: '10px 24px',
    fontFamily: 'var(--qa-font-mono)',
    fontWeight: 500,
    fontSize: 13,
    letterSpacing: '0.05em',
    textTransform: 'uppercase',
    cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.4 : 1,
    borderRadius: 4,
    transition: 'transform 0.12s ease, box-shadow 0.2s ease',
  }

  return (
    <button
      type="button"
      disabled={disabled}
      aria-label={ariaLabel}
      onClick={handleClick}
      style={containerStyle}
    >
      <span style={{ position: 'relative', zIndex: 1 }}>{children}</span>
      {ripples.map((r) => (
        <span
          key={r.id}
          aria-hidden
          className="qa-ripple"
          style={{
            position: 'absolute',
            left: r.x,
            top: r.y,
            width: 24,
            height: 24,
            marginLeft: -12,
            marginTop: -12,
            borderRadius: '50%',
            background: TONE_TO_COLOR[tone],
            opacity: 0,
            animation: 'qa-ripple-out 600ms ease-out forwards',
          }}
        />
      ))}
    </button>
  )
}

export default OrderRipple
