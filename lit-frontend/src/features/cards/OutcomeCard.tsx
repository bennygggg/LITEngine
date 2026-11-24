import { ArrowDownRight, ArrowUpRight, ChevronDown, Minus } from 'lucide-react'
import { useState } from 'react'
import { Badge } from '@/design/ui/Badge'
import { CardShell } from '@/design/ui/CardShell'
import { cn } from '@/lib/cn'
import { formatDate } from '@/lib/format'
import type { OutcomeCard as Card } from '@/types/agent'

const sentence = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).toLowerCase()
const strength = (c: number) => (Math.abs(c) >= 0.5 ? 'Strong' : Math.abs(c) >= 0.1 ? 'Moderate' : Math.abs(c) >= 0.03 ? 'Slight' : 'Negligible')

const TIER = {
  favorable: { tone: 'favorable', Icon: ArrowUpRight, word: 'Favourable' },
  uncertain: { tone: 'uncertain', Icon: Minus, word: 'Uncertain' },
  unfavorable: { tone: 'unfavorable', Icon: ArrowDownRight, word: 'Unfavourable' },
} as const

function Gauge({ value }: { value: number }) {
  return (
    <div className="mt-3" role="img" aria-label={`Indicative chance of any relief: about ${value} percent`}>
      <div className="relative h-2 rounded-full bg-border">
        <div className="absolute inset-y-0 left-0 rounded-full bg-ink" style={{ width: `${value}%` }} />
        <div className="absolute -inset-y-1 left-1/2 w-px bg-border-strong" />
        <div className="absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-bg bg-ink shadow-raised" style={{ left: `${value}%` }} />
      </div>
      <div className="tnum mt-1.5 flex justify-between text-2xs text-ink-subtle"><span>0%</span><span>even odds</span><span>100%</span></div>
    </div>
  )
}

export function OutcomeCardView({ card }: { card: Card }) {
  const [open, setOpen] = useState(false)
  const tier = TIER[card.estimate.tier]
  const contribs = (card.contributions ?? []).slice(0, 5)
  const scale = Math.max(0.5, ...contribs.map((c) => Math.abs(c.contribution)))
  const m = card.model

  return (
    <CardShell eyebrow="Outcome" title={card.title} subtitle={card.subtitle ?? undefined} disclaimer={card.disclaimer ?? undefined}
      actions={<Badge tone="outline">Indicative</Badge>}>
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <div>
          <p className="font-display text-3xl font-medium leading-tight tracking-tight">{card.estimate.tier_label}</p>
          <p className="mt-1 text-sm text-ink-muted">about <span className="tnum font-medium text-ink">{card.estimate.p_rounded}%</span> chance of any appellate relief, including partial relief</p>
        </div>
        <Badge tone={tier.tone}><tier.Icon className="size-3" />{tier.word}</Badge>
      </div>
      <Gauge value={card.estimate.p_rounded} />

      {contribs.length > 0 && (
        <div className="mt-6">
          <h4 className="mb-2 text-2xs font-medium uppercase tracking-[0.08em] text-ink-subtle">What moves the estimate <span className="normal-case tracking-normal">(compared with a typical case)</span></h4>
          <ul className="space-y-2" aria-label="Drivers">
            {contribs.map((c) => {
              const w = Math.max(2, (Math.abs(c.contribution) / scale) * 50)
              const up = c.contribution >= 0
              return (
                <li key={c.feature} className="grid grid-cols-[8.5rem_1fr_4.5rem] items-center gap-3 text-sm" title={c.explanation}>
                  <span className="truncate text-ink">{sentence(c.display_name)}</span>
                  <span className="relative h-2.5" aria-hidden>
                    <span className="absolute inset-y-0 left-1/2 w-px bg-border-strong" />
                    <span className={cn('absolute inset-y-0 rounded-sm', up ? 'bg-tier-favorable' : 'bg-tier-unfavorable')} style={up ? { left: '50%', width: `${w}%` } : { right: '50%', width: `${w}%` }} />
                  </span>
                  <span className="text-right text-xs text-ink-muted">{strength(c.contribution)}<span className="sr-only"> push toward {up ? 'relief' : 'dismissal'}</span></span>
                </li>
              )
            })}
          </ul>
          <div className="mt-1 grid grid-cols-[8.5rem_1fr_4.5rem] gap-3 text-2xs text-ink-subtle"><span /><span className="flex justify-between"><span>← toward dismissal</span><span>toward relief →</span></span><span /></div>
          {card.drivers_summary && <p className="mt-3 text-sm leading-relaxed text-ink">{card.drivers_summary}</p>}
        </div>
      )}

      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="mt-5 inline-flex items-center gap-1 text-sm text-ink-muted hover:text-ink">
        How this estimate works<ChevronDown className={cn('size-3.5 transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <div className="mt-3 space-y-3 rounded-lg border border-border bg-sunken p-4 text-sm leading-relaxed">
          <p><strong className="font-medium">Model.</strong> {m.name}{m.n_train ? `, trained on ${m.n_train.toLocaleString('en-IN')} Indian High Court criminal appeals` : ''}. {m.reads ? `It reads ${m.reads}.` : 'It reads the facts and grounds in the document plus who is appealing.'} It answers one question: any appellate relief, or none.</p>
          {m.eval_accuracy != null && m.baseline_accuracy != null && (
            <p><strong className="font-medium">How good is it?</strong> On {m.n_eval ? `${m.n_eval.toLocaleString('en-IN')} ` : ''}later cases{m.eval_period ? ` (${m.eval_period})` : ''} that it had not seen, it was right <span className="tnum">{Math.round(m.eval_accuracy * 100)}%</span> of the time; always guessing the more common outcome would be right <span className="tnum">{Math.round(m.baseline_accuracy * 100)}%</span>.{m.eval_auc != null ? <> Its ranking quality (AUC) was <span className="tnum">{m.eval_auc.toFixed(2)}</span>.</> : null} It estimates; it does not decide.</p>
          )}
          <p><strong className="font-medium">Inputs used.</strong> {card.inputs.appellant_type === 'accused_appeal' ? 'Appeal by the accused' : card.inputs.appellant_type === 'state_appeal' ? 'Appeal by the State or complainant' : 'Appeal type not specified'}
            {card.inputs.filing_date ? `, filed ${formatDate(card.inputs.filing_date)}` : ''}. Both were supplied by you; the appeal type is never inferred from the case text.</p>
          <ul className="list-disc space-y-1 pl-5 text-ink-muted">{(card.caveats ?? []).map((c) => <li key={c}>{c}</li>)}</ul>
          {card.legacy && <p className="text-xs text-ink-subtle">Earlier rule-based score: <span className="tnum">{Math.round(card.legacy.p * 100)}%</span>. {card.legacy.note}.</p>}
        </div>
      )}
    </CardShell>
  )
}
