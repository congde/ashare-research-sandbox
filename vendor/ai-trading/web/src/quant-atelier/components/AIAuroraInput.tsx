/**
 * AIAuroraInput — textarea with a slowly rotating conic-gradient
 * border when the AI agent is actively generating.
 *
 * The effect signals "Strategy Architect is thinking" without
 * blocking the user. Idle state falls back to a subtle 1px line.
 */

import { useId, type ChangeEvent, type KeyboardEvent } from 'react'

interface AIAuroraInputProps {
  value: string
  onChange: (value: string) => void
  onSubmit?: (value: string) => void
  placeholder?: string
  generating?: boolean
  disabled?: boolean
  rows?: number
  ariaLabel?: string
  ariaDescribedBy?: string
}

export function AIAuroraInput({
  value,
  onChange,
  onSubmit,
  placeholder = 'Describe your strategy in plain language…',
  generating = false,
  disabled = false,
  rows = 3,
  ariaLabel,
  ariaDescribedBy,
}: AIAuroraInputProps) {
  const id = useId()

  const handleChange = (event: ChangeEvent<HTMLTextAreaElement>) => {
    onChange(event.target.value)
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && onSubmit) {
      event.preventDefault()
      onSubmit(value)
    }
  }

  return (
    <div
      className={generating ? 'qa-aurora' : ''}
      style={{
        position: 'relative',
        padding: 1,
        borderRadius: 8,
        background: generating
          ? 'conic-gradient(from var(--qa-aurora-angle, 0deg), var(--qa-ai), var(--qa-neutral), var(--qa-profit), var(--qa-ai))'
          : 'var(--qa-line-subtle)',
        animation: generating ? 'qa-aurora-rotate 6s linear infinite' : 'none',
      }}
    >
      <textarea
        id={id}
        value={value}
        rows={rows}
        disabled={disabled}
        placeholder={placeholder}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        aria-label={ariaLabel ?? placeholder}
        aria-describedby={ariaDescribedBy}
        style={{
          width: '100%',
          background: 'var(--qa-bg-surface)',
          color: 'var(--qa-text-1)',
          fontFamily: 'var(--qa-font-body)',
          fontSize: 14,
          lineHeight: 1.55,
          padding: '14px 16px',
          border: 'none',
          borderRadius: 7,
          outline: 'none',
          resize: 'vertical',
          minHeight: 56,
        }}
      />
    </div>
  )
}

export default AIAuroraInput
