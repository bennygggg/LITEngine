import { useEffect, useState } from 'react'
import { cn } from '@/lib/cn'
import { useCases } from '@/lib/store/cases'
import type { SourcesCard } from '@/types/agent'

const CONTEXT = 900

/** Shows a retrieved passage in its place in the document (offsets come from the server; the text from this device). */
export default function SourceViewer({ card, focus, caseId, textOverride }: { card: SourcesCard; focus?: string; caseId: string | null; textOverride?: string }) {
  const [text, setText] = useState<string | null | undefined>(undefined)
  const [ref, setRef] = useState(focus ?? card.excerpts?.[0]?.ref)
  useEffect(() => { setRef(focus ?? card.excerpts?.[0]?.ref) }, [focus, card.excerpts])
  useEffect(() => {
    let live = true
    if (textOverride) { setText(textOverride); return }
    if (!caseId) { setText(null); return }
    void useCases.getState().text(caseId).then((t) => live && setText(t ?? null))
    return () => { live = false }
  }, [caseId, textOverride])

  const ex = (card.excerpts ?? []).find((e) => e.ref === ref)
  const start = ex?.char_start ?? 0
  const end = ex?.char_end ?? 0
  const ok = text != null && ex && end > start && text.slice(start, end) === ex.text
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap gap-1.5 border-b border-border px-4 py-2.5" role="tablist" aria-label="Passages">
        {(card.excerpts ?? []).map((e) => (
          <button key={e.ref} role="tab" aria-selected={e.ref === ref} onClick={() => setRef(e.ref)} className={cn('rounded-md border px-2 py-1 text-xs font-semibold tabular-nums transition-colors', e.ref === ref ? 'border-accent/40 bg-accent-soft text-accent' : 'border-border text-ink-muted hover:text-ink')}>{e.ref}</button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4 text-sm leading-7">
        {!ex ? <p className="text-ink-muted">No passage selected.</p> : text === undefined ? <p className="text-ink-muted">Loading the document…</p>
          : ok ? (
            <p className="whitespace-pre-wrap text-ink-muted">
              {start > CONTEXT ? '… ' : ''}{text!.slice(Math.max(0, start - CONTEXT), start)}
              <mark className="rounded bg-accent-soft px-0.5 text-ink [box-decoration-break:clone]">{text!.slice(start, end)}</mark>
              {text!.slice(end, end + CONTEXT)}{end + CONTEXT < text!.length ? ' …' : ''}
            </p>
          ) : (
            <>
              <p className="mb-3 text-xs text-ink-subtle">The full document isn’t stored on this device, so only the passage is shown.</p>
              <p className="whitespace-pre-wrap text-ink"><mark className="rounded bg-accent-soft px-0.5">{ex.text}</mark></p>
            </>
          )}
      </div>
      {ex && <p className="tnum border-t border-border px-4 py-2 text-xs text-ink-subtle">Passage {ex.ref} · cosine {ex.cosine.toFixed(2)}{ok ? ` · characters ${start.toLocaleString()}–${end.toLocaleString()}` : ''}</p>}
    </div>
  )
}
