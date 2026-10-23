import { useEffect, useRef } from 'react'
import { PrecedentRow } from '@/features/cards/PrecedentsCard'
import { cn } from '@/lib/cn'
import type { PrecedentsCard } from '@/types/agent'

export default function PrecedentsCanvas({ card, focus }: { card: PrecedentsCard; focus?: string }) {
  const sel = useRef<HTMLLIElement>(null)
  useEffect(() => { sel.current?.scrollIntoView({ block: 'center', behavior: 'smooth' }) }, [focus])
  return (
    <div className="h-full overflow-y-auto px-4 py-3">
      <p className="mb-2 text-sm text-ink-muted">{card.subtitle}. Showing each judgment’s closest passage; the full text is at the source.</p>
      <ul className="divide-y divide-border">
        {(card.results ?? []).map((h) => (
          <li key={h.ref} ref={h.ref === focus ? sel : undefined} className={cn('-mx-2 rounded-lg px-2', h.ref === focus && 'bg-accent-soft/50')}>
            <ul><PrecedentRow hit={h} compact={false} /></ul>
          </li>
        ))}
      </ul>
      {card.disclaimer && <p className="mt-4 rounded-lg bg-sunken px-3 py-2 text-xs text-ink-muted">{card.disclaimer.text}</p>}
    </div>
  )
}
