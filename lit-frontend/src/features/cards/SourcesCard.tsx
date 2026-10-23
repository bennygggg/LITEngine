import { Maximize2 } from 'lucide-react'
import { CardShell } from '@/design/ui/CardShell'
import { useChatActions } from '@/features/chat/actions'
import type { SourcesCard as Card } from '@/types/agent'

export function SourcesCardView({ card }: { card: Card }) {
  const actions = useChatActions()
  const excerpts = card.excerpts ?? []
  return (
    <CardShell
      eyebrow="Sources" title={card.title} subtitle={card.question}
      disclaimer={card.method === 'extractive' ? { level: 'info', text: 'Showing the closest passages only — the AI answer was unavailable.' } : undefined}
    >
      {excerpts.length === 0 ? (
        <p className="text-sm text-ink-muted">{card.coverage ?? 'No passage in this document matched the question.'}</p>
      ) : (
        <ul className="-my-1 divide-y divide-border">
          {excerpts.map((e) => (
            <li key={e.ref}>
              <button type="button" onClick={() => actions.openCanvas(card.card_id, e.ref)} className="group flex w-full gap-3 py-3 text-left">
                <span className="mt-0.5 flex h-5 w-7 shrink-0 items-center justify-center rounded bg-accent-soft text-2xs font-semibold tabular-nums text-accent">{e.ref}</span>
                <span className="min-w-0 flex-1">
                  <span className="line-clamp-3 text-sm leading-relaxed text-ink">{e.text}</span>
                  <span className="mt-1.5 flex items-center justify-between text-xs text-ink-subtle"><span className="tnum">cosine {e.cosine.toFixed(2)}</span><span className="inline-flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"><Maximize2 className="size-3" /> View in document</span></span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </CardShell>
  )
}
