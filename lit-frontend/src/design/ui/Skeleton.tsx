import type { HTMLAttributes } from 'react'
import { cn } from '@/lib/cn'

/** Shimmering placeholder in the final shape of the thing it stands in for (no layout shift). */
export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden
      className={cn(
        'relative overflow-hidden rounded-md bg-border/70',
        "after:absolute after:inset-0 after:-translate-x-full after:animate-[shimmer_1.4s_infinite] after:bg-gradient-to-r after:from-transparent after:via-surface/50 after:to-transparent after:content-['']",
        className,
      )}
      {...props}
    />
  )
}
