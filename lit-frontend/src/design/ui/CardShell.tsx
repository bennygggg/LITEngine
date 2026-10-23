import type { ReactNode } from 'react'
import { Info, TriangleAlert } from 'lucide-react'
import { cn } from '@/lib/cn'

export interface CardShellProps {
  eyebrow?: string
  title: string
  subtitle?: string
  actions?: ReactNode
  disclaimer?: { level: 'info' | 'caution'; text: string }
  footer?: ReactNode
  className?: string
  children: ReactNode
}

/**
 * The one frame every inline card shares: hairline border, serif title, optional disclaimer strip.
 * Cards never nest inside cards; inner groupings use spacing and dividers.
 */
export function CardShell({ eyebrow, title, subtitle, actions, disclaimer, footer, className, children }: CardShellProps) {
  return (
    <section className={cn('overflow-hidden rounded-md border border-border bg-surface', className)}>
      <header className="flex items-start justify-between gap-4 px-5 pb-3 pt-4">
        <div className="min-w-0">
          {eyebrow && <p className="mb-1 text-xs font-medium text-ink-subtle">{eyebrow}</p>}
          <h3 className="font-display text-lg font-normal leading-snug tracking-tight text-ink">{title}</h3>
          {subtitle && <p className="mt-0.5 text-sm text-ink-muted">{subtitle}</p>}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-1">{actions}</div>}
      </header>
      <div className="px-5 pb-4">{children}</div>
      {disclaimer && (
        <div
          className={cn(
            'flex items-start gap-2 border-t border-border px-5 py-2.5 text-xs',
            disclaimer.level === 'caution' ? 'bg-tier-uncertain/8 text-ink' : 'bg-sunken text-ink-muted',
          )}
        >
          {disclaimer.level === 'caution' ? <TriangleAlert className="mt-px size-3.5 shrink-0 text-tier-uncertain" /> : <Info className="mt-px size-3.5 shrink-0" />}
          <p>{disclaimer.text}</p>
        </div>
      )}
      {footer && <footer className="border-t border-border px-5 py-2.5 text-xs text-ink-muted">{footer}</footer>}
    </section>
  )
}
