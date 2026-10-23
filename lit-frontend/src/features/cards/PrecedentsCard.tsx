import { ArrowUpRight, ChevronDown, Maximize2 } from 'lucide-react'
import { useState } from 'react'
import { Badge } from '@/design/ui/Badge'
import { Button } from '@/design/ui/Button'
import { CardShell } from '@/design/ui/CardShell'
import { useChatActions } from '@/features/chat/actions'
import { cn } from '@/lib/cn'
import { clamp, courtLabel, yearOf } from '@/lib/format'
import type { PrecedentHit, PrecedentsCard as Card } from '@/types/agent'

/** Relative closeness for the bar only. Cosine is similarity of meaning — never shown as a percent or called a "match". */
export const closeness = (cosine: number) => clamp((cosine - 0.3) / 0.5, 0.04, 1)

export function SimilarityBar({ cosine }: { cosine: number }) {
  return (
    <span className="flex items-center gap-2" title={`Cosine similarity ${cosine.toFixed(3)} — similarity of meaning, not a probability of relevance`}>
      <span className="h-1 w-16 overflow-hidden rounded-full bg-border"><span className="block h-full rounded-full bg-ink-muted" style={{ width: `${closeness(cosine) * 100}%` }} /></span>
      <span className="tnum text-2xs text-ink-subtle">cosine {cosine.toFixed(2)}</span>
    </span>
  )
}

export function PrecedentRow({ hit, onOpen, compact = true }: { hit: PrecedentHit; onOpen?: () => void; compact?: boolean }) {
  // The title is the keyboard-accessible control; the whole row also responds to a mouse click. (A clickable row that
  // contains a link would nest interactive controls, which assistive technology can't operate reliably.)
  return (
    <li>
      <div className={cn('group flex gap-3 py-3', onOpen && 'cursor-pointer')} onClick={onOpen}>
        <span className="mt-0.5 flex h-5 w-7 shrink-0 items-center justify-center rounded border border-transparent bg-accent-soft text-2xs font-semibold tabular-nums text-accent">{hit.ref}</span>
        <div className="min-w-0 flex-1">
          {onOpen ? (
            <button type="button" onClick={(e) => { e.stopPropagation(); onOpen() }} className="text-left font-medium leading-snug text-ink group-hover:underline group-hover:decoration-border-strong group-hover:underline-offset-2">{hit.title}</button>
          ) : (
            <p className="font-medium leading-snug text-ink">{hit.title}</p>
          )}
          <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-ink-muted">
            <span>{courtLabel(hit.court_tier, hit.court)}</span><span aria-hidden>·</span><span className="tnum">{yearOf(hit.date)}</span>
            {(hit.matched_statutes ?? []).length > 0 && <span className="flex gap-1">{(hit.matched_statutes ?? []).slice(0, 3).map((s) => <Badge key={s} tone="outline">{s.replace('Section ', 's.')}</Badge>)}</span>}
          </p>
          {hit.snippet && <p className={cn('mt-1.5 text-sm leading-relaxed text-ink-muted', compact && 'line-clamp-2')}>{hit.snippet}</p>}
          <div className="mt-2 flex items-center justify-between gap-3"><SimilarityBar cosine={hit.cosine} />
            {hit.url && <a href={hit.url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()} className="inline-flex items-center gap-1 text-xs text-ink-muted hover:text-ink">Open source <ArrowUpRight className="size-3" /></a>}
          </div>
        </div>
      </div>
    </li>
  )
}

export function PrecedentsCardView({ card }: { card: Card }) {
  const actions = useChatActions()
  const [all, setAll] = useState(false)
  const results = card.results ?? []
  const shown = all ? results : results.slice(0, 3)
  return (
    <CardShell
      eyebrow="Precedents" title={card.title} subtitle={card.subtitle ?? undefined}
      actions={<Button variant="ghost" size="icon-sm" aria-label="Open in side panel" onClick={() => actions.openCanvas(card.card_id)}><Maximize2 /></Button>}
      disclaimer={card.disclaimer ?? undefined}
    >
      {results.length === 0 ? (
        <p className="py-2 text-sm text-ink-muted">Nothing in the library matched closely{card.filter?.before_date ? ' among judgments decided before the filing date' : ''}.</p>
      ) : (
        <>
          <ul className="-my-1 divide-y divide-border">{shown.map((h) => <PrecedentRow key={h.ref} hit={h} onOpen={() => actions.openCanvas(card.card_id, h.ref)} />)}</ul>
          {results.length > 3 && (
            <button type="button" onClick={() => setAll(!all)} className="mt-1 inline-flex items-center gap-1 text-sm text-ink-muted hover:text-ink" aria-expanded={all}>
              {all ? 'Show fewer' : `Show all ${results.length}`}<ChevronDown className={cn('size-3.5 transition-transform', all && 'rotate-180')} />
            </button>
          )}
          {(card.filter?.undated_excluded ?? 0) > 0 && <p className="mt-2 text-xs text-ink-subtle">{card.filter?.undated_excluded} undated judgment{(card.filter?.undated_excluded ?? 0) > 1 ? 's were' : ' was'} excluded — without a decision date it can’t be shown to predate the filing.</p>}
        </>
      )}
    </CardShell>
  )
}
