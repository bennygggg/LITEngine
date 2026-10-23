import { Check } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/design/ui/Button'
import { cn } from '@/lib/cn'
import type { NeedsInputCard as Card } from '@/types/agent'
import { useChatActions } from '@/features/chat/actions'

/** The assistant needs two facts only the user can supply. Never defaulted, never guessed. */
export function NeedsInputCard({ card, answered }: { card: Card; answered?: Record<string, string> }) {
  const actions = useChatActions()
  const [values, setValues] = useState<Record<string, string>>(actions.inputPrefill ?? {})
  const done = Boolean(answered)
  const shown = answered ?? values
  const complete = card.fields.every((f) => !f.required || Boolean(shown[f.name]))
  const today = new Date().toISOString().slice(0, 10)

  return (
    <section className={cn('rounded-lg border bg-surface shadow-raised', done ? 'border-border' : 'border-accent/40')} aria-label={card.title}>
      <div className="px-5 pb-1 pt-4">
        <p className="mb-1 text-2xs font-medium uppercase tracking-[0.08em] text-ink-subtle">{done ? 'Provided' : 'Needed to continue'}</p>
        <h3 className="font-display text-lg font-medium tracking-tight">{done ? 'Details provided' : card.title}</h3>
        {!done && <p className="mt-1 text-sm text-ink-muted">{card.reason}</p>}
      </div>
      <form
        className="space-y-5 px-5 pb-4 pt-3"
        onSubmit={(e) => {
          e.preventDefault()
          if (!done && complete) actions.sendInput(card.card_id, values, card.pending)
        }}
      >
        {card.fields.map((f) => (
          <fieldset key={f.name} disabled={done} className="space-y-2">
            <legend className="text-sm font-medium">{f.label}</legend>
            {f.kind === 'select' ? (
              <div role="radiogroup" aria-label={f.label} className="grid gap-2">
                {(f.options ?? []).map((o) => {
                  const on = shown[f.name] === o.value
                  return (
                    <button
                      key={o.value} type="button" role="radio" aria-checked={on} disabled={done}
                      onClick={() => setValues({ ...values, [f.name]: o.value })}
                      className={cn(
                        'flex items-center gap-3 rounded-lg border px-3.5 py-2.5 text-left text-sm transition-colors',
                        on ? 'border-ink bg-sunken' : 'border-border hover:border-border-strong hover:bg-sunken/60',
                        done && !on && 'opacity-40',
                      )}
                    >
                      <span className={cn('flex size-4 shrink-0 items-center justify-center rounded-full border', on ? 'border-ink bg-ink text-bg' : 'border-border-strong')}>
                        {on && <Check className="size-2.5" strokeWidth={3} />}
                      </span>
                      {o.label}
                    </button>
                  )
                })}
              </div>
            ) : (
              <input
                type="date" max={today} value={shown[f.name] ?? ''} disabled={done}
                onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}
                aria-label={f.label}
                className="h-10 w-full max-w-56 rounded-lg border border-border-strong bg-surface px-3 text-sm outline-none focus:border-ink disabled:opacity-60"
              />
            )}
          </fieldset>
        ))}
        {!done && (
          <div className="flex items-center justify-between gap-4">
            {card.hint ? <p className="max-w-md text-xs text-ink-muted">{card.hint}</p> : <span />}
            <Button type="submit" disabled={!complete || actions.busy}>Continue</Button>
          </div>
        )}
      </form>
    </section>
  )
}
