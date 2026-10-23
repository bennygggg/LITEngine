import { ChevronDown } from 'lucide-react'
import { useState } from 'react'
import { Badge } from '@/design/ui/Badge'
import { CardShell } from '@/design/ui/CardShell'
import { cn } from '@/lib/cn'
import { signed } from '@/lib/format'
import type { ScenarioCard as Card } from '@/types/agent'

const EFFECT = { large: { label: 'Large effect', tone: 'accent' }, small: { label: 'Small effect', tone: 'neutral' }, negligible: { label: 'No real effect', tone: 'outline' } } as const

export function ScenarioCardView({ card }: { card: Card }) {
  const [open, setOpen] = useState(false)
  const base = Math.round(card.base.p_succeeds * 100)
  const scale = Math.max(20, ...(card.scenarios ?? []).map((s) => Math.abs(s.delta_pp)))
  const sens = card.sensitivity ?? []
  const maxSwing = Math.max(5, ...sens.map((r) => r.swing_pp))

  return (
    <CardShell eyebrow="Scenarios" title={card.title} subtitle={card.subtitle ?? undefined} disclaimer={card.disclaimer ?? undefined}
      actions={<Badge tone="outline">Base ≈ <span className="tnum">{base}%</span></Badge>}>
      <ul className="space-y-4">
        {(card.scenarios ?? []).map((s) => {
          const w = Math.max(s.delta_pp === 0 ? 0 : 2, (Math.abs(s.delta_pp) / scale) * 50)
          const up = s.delta_pp >= 0
          const effect = EFFECT[s.effect_class]
          return (
            <li key={s.id}>
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <p className="font-medium">{s.label}</p>
                <p className="flex items-center gap-2 text-sm"><span className="tnum font-medium">{signed(s.delta_pp)} points</span><Badge tone={effect.tone}>{effect.label}</Badge></p>
              </div>
              <div className="relative mt-2 h-2.5" role="img" aria-label={`${signed(s.delta_pp)} percentage points versus the base estimate`}>
                <span className="absolute inset-y-0 left-0 right-0 rounded-full bg-border/60" />
                <span className="absolute -inset-y-0.5 left-1/2 w-px bg-border-strong" />
                {s.delta_pp !== 0 && <span className={cn('absolute inset-y-0 rounded-full', up ? 'bg-tier-favorable' : 'bg-tier-unfavorable')} style={up ? { left: '50%', width: `${w}%` } : { right: '50%', width: `${w}%` }} />}
              </div>
              <p className="tnum mt-1 text-xs text-ink-subtle">{base}% → {Math.round(s.p_succeeds * 100)}%</p>
              {(s.warnings ?? []).map((w) => <p key={w} className="mt-1 text-xs text-ink-muted">{w}</p>)}
              {(s.applied ?? []).filter((a) => a.status === 'rejected' || a.status === 'clamped').map((a) => <p key={`${a.lever}${a.value}`} className="mt-1 text-xs text-ink-muted"><span className="capitalize">{a.status}</span>: {String(a.value)} — {a.note}</p>)}
            </li>
          )
        })}
      </ul>
      {sens.length > 0 && (
        <>
          <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="mt-5 inline-flex items-center gap-1 text-sm text-ink-muted hover:text-ink">
            How much does each input matter?<ChevronDown className={cn('size-3.5 transition-transform', open && 'rotate-180')} />
          </button>
          {open && (
            <ul className="mt-3 space-y-2 rounded-lg border border-border bg-sunken p-4" aria-label="Sensitivity">
              {sens.map((r) => (
                <li key={r.feature} className="grid grid-cols-[9rem_1fr_3.5rem] items-center gap-3 text-sm">
                  <span className="truncate">{r.display_name}</span>
                  <span className="h-2 rounded-full bg-border"><span className="block h-full rounded-full bg-ink-muted" style={{ width: `${(r.swing_pp / maxSwing) * 100}%` }} /></span>
                  <span className="tnum text-right text-xs text-ink-muted">{r.swing_pp.toFixed(1)} pts</span>
                  {r.note && <span className="col-span-3 -mt-1 text-xs text-ink-subtle">{r.note}</span>}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </CardShell>
  )
}
