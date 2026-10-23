import { cn } from '@/lib/cn'

export function Spinner({ className }: { className?: string }) {
  return <span role="status" aria-label="Working" className={cn('inline-block size-3.5 animate-spin rounded-full border-2 border-border-strong border-t-ink', className)} />
}
