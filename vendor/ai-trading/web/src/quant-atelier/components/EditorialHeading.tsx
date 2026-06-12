/**
 * EditorialHeading — Reckless Italic display title with hairline rule.
 *
 * The signature look of Quant Atelier section headers. Use sparingly —
 * one hero per page max, otherwise the editorial weight loses impact.
 */

import type { ReactNode } from 'react'

interface EditorialHeadingProps {
  children: ReactNode
  level?: 1 | 2 | 3
  rule?: boolean
  align?: 'left' | 'center'
  className?: string
}

const SIZE_BY_LEVEL: Record<NonNullable<EditorialHeadingProps['level']>, number> = {
  1: 80,
  2: 56,
  3: 40,
}

const LINE_HEIGHT_BY_LEVEL: Record<NonNullable<EditorialHeadingProps['level']>, number> = {
  1: 0.95,
  2: 1.0,
  3: 1.05,
}

export function EditorialHeading({
  children,
  level = 2,
  rule = true,
  align = 'left',
  className,
}: EditorialHeadingProps) {
  const Tag = `h${level}` as 'h1' | 'h2' | 'h3'

  return (
    <div
      className={className}
      style={{ textAlign: align, marginBottom: rule ? 24 : 16 }}
    >
      <Tag
        className="qa-display"
        style={{
          fontFamily: 'var(--qa-font-display)',
          fontStyle: 'italic',
          fontWeight: 400,
          fontSize: SIZE_BY_LEVEL[level],
          lineHeight: LINE_HEIGHT_BY_LEVEL[level],
          letterSpacing: '-0.03em',
          color: 'var(--qa-text-1)',
          margin: 0,
        }}
      >
        {children}
      </Tag>
      {rule && (
        <hr
          aria-hidden
          style={{
            border: 0,
            height: 1,
            background:
              align === 'center'
                ? 'linear-gradient(to right, transparent, var(--qa-line-strong), transparent)'
                : 'linear-gradient(to right, var(--qa-line-strong), transparent)',
            margin: '12px 0 0',
            width: align === 'center' ? '40%' : '100%',
            marginInline: align === 'center' ? 'auto' : 0,
          }}
        />
      )}
    </div>
  )
}

export default EditorialHeading
