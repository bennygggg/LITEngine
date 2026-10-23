import type { HTMLAttributes } from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/cn'

const badge = cva('inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5 text-2xs font-medium leading-none', {
  variants: {
    tone: {
      neutral: 'border-border bg-sunken text-ink-muted',
      outline: 'border-border-strong bg-transparent text-ink-muted',
      accent: 'border-transparent bg-accent-soft text-accent',
      favorable: 'border-transparent bg-tier-favorable/12 text-tier-favorable',
      uncertain: 'border-transparent bg-tier-uncertain/12 text-tier-uncertain',
      unfavorable: 'border-transparent bg-tier-unfavorable/12 text-tier-unfavorable',
    },
  },
  defaultVariants: { tone: 'neutral' },
})

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badge> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badge({ tone }), className)} {...props} />
}
