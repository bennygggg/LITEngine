import { Copy, RotateCw, TriangleAlert } from 'lucide-react'
import { useMemo, type ReactNode } from 'react'
import { Button } from '@/design/ui/Button'
import { Tooltip } from '@/design/ui/Tooltip'
import { cn } from '@/lib/cn'
import { CitationProvider, type CitationApi } from '@/lib/markdown/citations'
import { StreamingMarkdown } from '@/lib/markdown/StreamingMarkdown'
import { CardRenderer } from '@/features/cards/CardRenderer'
import { NeedsInputCard } from '@/features/cards/NeedsInputCard'
import { useChatActions } from './actions'
import type { Message, Part, StepPart } from './model'
import { messageText } from './reducer'
import { StepTimeline } from './StepTimeline'

export function Avatar() {
  return (
    <span aria-hidden className="mt-0.5 flex size-6 shrink-0 select-none items-center justify-center rounded-full bg-ink font-display text-[13px] font-semibold leading-none text-bg">
      L
    </span>
  )
}

/** Group consecutive steps so the timeline reads as one block. */
function groupParts(parts: Part[]): Array<Part | { kind: 'steps'; id: string; steps: StepPart[] }> {
  const out: Array<Part | { kind: 'steps'; id: string; steps: StepPart[] }> = []
  for (const p of parts) {
    const last = out[out.length - 1]
    if (p.kind === 'step') {
      if (last && 'steps' in last) last.steps.push(p)
      else out.push({ kind: 'steps', id: `steps:${p.id}`, steps: [p] })
    } else out.push(p)
  }
  return out
}

export function useCitations(msg: Message, open: (cardId: string, focus?: string) => void): CitationApi {
  return useMemo(() => {
    const index = new Map<string, { title: string; detail?: string; cardId: string }>()
    for (const p of msg.parts) {
      if (p.kind !== 'card' || !p.payload) continue
      if (p.payload.type === 'precedents') {
        for (const h of p.payload.results) {
          const tier = h.court_tier === 'SC' ? 'Supreme Court' : h.court ?? 'Court'
          index.set(h.ref, { title: h.title, detail: `${tier} · ${(h.date ?? '').slice(0, 4) || 'undated'} · cosine ${h.cosine.toFixed(2)}`, cardId: p.payload.card_id })
        }
      } else if (p.payload.type === 'sources') {
        for (const e of p.payload.excerpts) index.set(e.ref, { title: `Passage ${e.ref}`, detail: e.text.length > 140 ? `${e.text.slice(0, 140)}…` : e.text, cardId: p.payload.card_id })
      }
    }
    return {
      resolve: (h) => index.get(h) ?? null,
      open: (h) => { const t = index.get(h); if (t) open(t.cardId, h) },
    }
  }, [msg.parts, open])
}

export function AssistantMessage({ msg, isLast, children }: { msg: Message; isLast: boolean; children?: ReactNode }) {
  const actions = useChatActions()
  const live = msg.status === 'streaming'
  const citations = useCitations(msg, actions.openCanvas)
  const grouped = groupParts(msg.parts)
  const lastTextId = [...msg.parts].reverse().find((p) => p.kind === 'text')?.id
  const hasContent = msg.parts.length > 0
  const text = messageText(msg)
  const problem = msg.notices.find((n) => n.scope === 'run')
  const aiNotice = msg.notices.find((n) => n.scope === 'llm')

  return (
    <article className="group flex gap-3 animate-rise-in" aria-label="Assistant message" aria-busy={live}>
      <Avatar />
      <div className="min-w-0 flex-1 space-y-3">
        <CitationProvider value={citations}>
          {!hasContent && live && <div className="flex h-6 items-center gap-1.5 text-sm text-ink-muted" role="status"><span className="size-1.5 animate-pulse rounded-full bg-ink-subtle" />Thinking</div>}
          {grouped.map((g) => {
            if ('steps' in g) return <StepTimeline key={g.id} steps={g.steps} live={live} />
            if (g.kind === 'text') return <StreamingMarkdown key={g.id} text={g.text} streaming={live && g.id === lastTextId && !msg.parts.some((p) => p.kind === 'card' && p.payload === null)} />
            if (g.kind === 'card') return <CardRenderer key={g.id} part={g} />
            if (g.kind === 'input') return <NeedsInputCard key={g.id} card={g.payload} answered={g.answered} />
            return null
          })}
        </CitationProvider>

        {aiNotice && !live && (
          <p className="flex items-center gap-1.5 text-xs text-ink-muted"><TriangleAlert className="size-3.5" />AI narration was unavailable, so this summary is templated. The results above are unaffected.</p>
        )}
        {(msg.status === 'error' || msg.status === 'interrupted' || msg.status === 'cancelled') && (
          <div role="status" className={cn('flex flex-wrap items-center gap-3 rounded-lg border px-3.5 py-2.5 text-sm', msg.status === 'cancelled' ? 'border-border text-ink-muted' : 'border-border-strong bg-surface text-ink')}>
            <span className="min-w-0 flex-1">
              {msg.status === 'cancelled' ? 'Stopped.' : msg.status === 'interrupted' ? 'This reply was interrupted before it finished.' : problem?.message ?? 'Something went wrong.'}
            </span>
            {msg.status !== 'cancelled' && <Button size="sm" variant="outline" disabled={actions.busy} onClick={() => actions.retry(msg.id)}><RotateCw /> Try again</Button>}
          </div>
        )}

        {!live && text && (
          <div className="flex items-center gap-0.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
            <Tooltip label="Copy"><Button variant="ghost" size="icon-sm" aria-label="Copy reply" onClick={() => void navigator.clipboard?.writeText(text)}><Copy /></Button></Tooltip>
            {msg.recorded && <span className="ml-1 text-2xs text-ink-subtle">Recorded</span>}
          </div>
        )}
        {isLast && !live && !msg.recorded && msg.suggestions.length > 0 && msg.status === 'complete' && (
          <div className="flex flex-wrap gap-2 pt-1" role="group" aria-label="Suggested next steps">
            {msg.suggestions.map((s) => (
              <button
                key={s.label} type="button" disabled={actions.busy}
                onClick={() => (s.forced_tool ? actions.sendTool(s.forced_tool, s.label) : actions.sendText(s.prompt))}
                className="rounded-full border border-border-strong bg-surface px-3.5 py-1.5 text-sm text-ink transition-colors hover:bg-sunken disabled:opacity-50"
              >
                {s.label}
              </button>
            ))}
          </div>
        )}
        {children}
      </div>
    </article>
  )
}
