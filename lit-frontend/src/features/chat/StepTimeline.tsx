import { Check, ChevronDown, CircleAlert, Minus } from 'lucide-react'
import { useState } from 'react'
import { Spinner } from '@/design/ui/Spinner'
import { cn } from '@/lib/cn'
import type { StepPart } from './model'

const fmt = (ms?: number) => (ms == null ? '' : ms < 950 ? `${Math.max(ms, 1)} ms` : `${(ms / 1000).toFixed(1)} s`)

function Icon({ status }: { status: StepPart['status'] }) {
  if (status === 'running') return <Spinner className="size-3" />
  if (status === 'error') return <CircleAlert className="size-3.5 text-tier-unfavorable" />
  if (status === 'skipped') return <Minus className="size-3.5 text-ink-subtle" />
  return <Check className="size-3.5 text-ink-subtle" />
}

/** The work behind a reply: what ran, how long it took, and what it found. Open while live, tucked away once settled. */
export function StepTimeline({ steps, live }: { steps: StepPart[]; live: boolean }) {
  const [userOpen, setUserOpen] = useState<boolean | null>(null)
  const open = userOpen ?? live
  const total = steps.reduce((s, x) => s + (x.durationMs ?? 0), 0)
  const running = steps.some((s) => s.status === 'running')
  return (
    <div className="my-3 text-sm">
      <button
        type="button"
        onClick={() => setUserOpen(!open)}
        aria-expanded={open}
        className="flex items-center gap-1.5 rounded-md py-0.5 text-ink-muted transition-colors hover:text-ink"
      >
        {running ? <Spinner className="size-3" /> : <Check className="size-3.5" />}
        <span>{running ? 'Working' : `${steps.length} step${steps.length === 1 ? '' : 's'}${total ? ` · ${fmt(total)}` : ''}`}</span>
        <ChevronDown className={cn('size-3.5 transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <ol className="mt-1.5 space-y-1 border-l border-border pl-3">
          {steps.map((s) => (
            <li key={s.id} className={cn('flex items-baseline gap-2 text-ink-muted animate-fade-in', s.origin === 'dependency' && 'text-ink-subtle')}>
              <span className="mt-0.5 shrink-0 self-start"><Icon status={s.status} /></span>
              <span className="min-w-0 flex-1">
                <span className={cn(s.status === 'running' && 'text-ink')}>{s.label}</span>
                {s.summary && s.status !== 'running' ? <span className="text-ink-subtle"> — {s.summary}</span> : null}
                {s.origin === 'dependency' ? <span className="ml-1.5 text-2xs uppercase tracking-wider text-ink-subtle">needed first</span> : null}
              </span>
              {s.status === 'cached' ? <span className="text-2xs text-ink-subtle">reused</span> : s.durationMs != null ? <span className="tnum text-2xs text-ink-subtle">{fmt(s.durationMs)}</span> : null}
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
