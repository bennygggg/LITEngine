import { ChevronDown } from 'lucide-react'
import { useState } from 'react'
import { Badge } from '@/design/ui/Badge'
import { CardShell } from '@/design/ui/CardShell'
import { cn } from '@/lib/cn'
import { cleanActs, uniqueSections } from '@/lib/format'
import type { CaseProfileCard as Card } from '@/types/agent'

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="mb-1.5 text-xs font-medium text-ink-subtle">{label}</h4>
      {children}
    </div>
  )
}

export function CaseProfileCardView({ card }: { card: Card }) {
  const [more, setMore] = useState(false)
  const p = card.profile
  const issues = p.legal_issues ?? []
  const facts = p.key_facts ?? []
  const sections = uniqueSections(p.ipc_sections ?? [])
  const acts = cleanActs(p.acts_referenced ?? [])
  const shownIssues = more ? issues : issues.slice(0, 3)
  const shownFacts = more ? facts : facts.slice(0, 3)
  const extra = Math.max(0, issues.length - 3) + Math.max(0, facts.length - 3)
  const q = card.extraction

  return (
    <CardShell
      eyebrow="Case profile" title={card.title} subtitle={card.subtitle ?? undefined} disclaimer={card.disclaimer ?? undefined}
      footer={
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span>Extraction: <strong className="font-medium text-ink">{q.quality}</strong> · <span className="tnum">{Math.round(q.completeness * 100)}%</span> of expected fields found</span>
          {(q.missing ?? []).length > 0 && <span className="text-ink-subtle">Missing: {(q.missing ?? []).join(', ')}</span>}
        </span>
      }
    >
      <div className="space-y-4">
        {issues.length > 0 && (
          <Section label="Issues">
            <ol className="space-y-1.5">
              {shownIssues.map((i, n) => (
                <li key={i} className="flex gap-2.5 text-sm leading-relaxed"><span className="tnum mt-px w-4 shrink-0 text-ink-subtle">{n + 1}.</span><span>{i}</span></li>
              ))}
            </ol>
          </Section>
        )}
        {(sections.length > 0 || acts.length > 0) && (
          <Section label="Statutes">
            <div className="flex flex-wrap gap-1.5">
              {sections.map((s) => <Badge key={s} tone="outline">{s}</Badge>)}
              {acts.map((a) => <span key={a} className="text-xs text-ink-muted">{a}</span>)}
            </div>
          </Section>
        )}
        {facts.length > 0 && (
          <Section label="Key facts">
            <ul className="space-y-1.5">
              {shownFacts.map((f) => <li key={f} className="flex gap-2.5 text-sm leading-relaxed"><span aria-hidden className="mt-2 size-1 shrink-0 rounded-full bg-ink-subtle" /><span>{f}</span></li>)}
            </ul>
          </Section>
        )}
        {p.relief_sought && (
          <Section label="Relief sought"><p className="text-sm leading-relaxed text-ink">{p.relief_sought}</p></Section>
        )}
        {extra > 0 && (
          <button type="button" onClick={() => setMore(!more)} className="inline-flex items-center gap-1 text-sm text-ink-muted hover:text-ink" aria-expanded={more}>
            {more ? 'Show less' : `Show ${extra} more`}<ChevronDown className={cn('size-3.5 transition-transform', more && 'rotate-180')} />
          </button>
        )}
      </div>
    </CardShell>
  )
}
