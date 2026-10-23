import { Skeleton } from '@/design/ui/Skeleton'
import type { CardType } from '@/types/agent'

/** A placeholder in the final card's shape, so the swap to real content moves nothing. */
export function CardSkeleton({ type }: { type: CardType }) {
  const label = { case_profile: 'Reading the case', precedents: 'Searching the library', argument_map: 'Mapping the arguments', outcome: 'Scoring the appeal', scenario: 'Re-scoring', sources: 'Finding passages', needs_input: '', document: '', error: '' }[type]
  return (
    <section aria-busy="true" aria-label={label} className="rounded-lg border border-border bg-surface px-5 py-4 shadow-raised" style={{ minHeight: heights[type] }}>
      <Skeleton className="h-3 w-24" />
      <Skeleton className="mt-3 h-5 w-2/3" />
      <div className="mt-5 space-y-2.5">
        <Skeleton className="h-3.5 w-full" />
        <Skeleton className="h-3.5 w-11/12" />
        <Skeleton className="h-3.5 w-4/5" />
        {type === 'argument_map' && <Skeleton className="mt-4 h-40 w-full" />}
        {type === 'outcome' && <Skeleton className="mt-4 h-16 w-full" />}
      </div>
    </section>
  )
}

const heights: Record<CardType, number> = { case_profile: 220, precedents: 260, argument_map: 340, outcome: 300, scenario: 240, sources: 180, needs_input: 160, document: 80, error: 80 }
