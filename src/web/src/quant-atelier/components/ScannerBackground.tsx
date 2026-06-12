/**
 * ScannerBackground — fixed 1-2% opacity scanline overlay.
 *
 * Mount once near the root of the app. Disabled under
 * prefers-reduced-motion via tokens.css.
 */

import type { CSSProperties } from 'react'

interface ScannerBackgroundProps {
  intensity?: number
}

export function ScannerBackground({ intensity = 1 }: ScannerBackgroundProps) {
  const style: CSSProperties = {
    position: 'fixed',
    inset: 0,
    pointerEvents: 'none',
    zIndex: 9999,
    background: 'var(--qa-scanline)',
    opacity: Math.max(0, Math.min(intensity, 2)),
    mixBlendMode: 'overlay',
  }

  return <div aria-hidden style={style} />
}

export default ScannerBackground
