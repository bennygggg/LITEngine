import { CircleAlert, RotateCw } from 'lucide-react'
import { Button } from '@/design/ui/Button'
import { useChatActions } from '@/features/chat/actions'
import type { ErrorCard } from '@/types/agent'

export function ErrorCardView({ card }: { card: ErrorCard }) {
  const actions = useChatActions()
  return (
    <section role="alert" className="flex items-start gap-3 rounded-lg border border-border bg-surface px-5 py-4 shadow-raised">
      <CircleAlert className="mt-0.5 size-4 shrink-0 text-ink-muted" />
      <div className="min-w-0 flex-1">
        <h3 className="font-display text-base font-medium">{card.title}</h3>
        <p className="mt-1 text-sm text-ink-muted">{card.message}</p>
        {card.technical && <details className="mt-2 text-xs text-ink-subtle"><summary className="cursor-pointer">Technical detail</summary><p className="mt-1 break-words">{card.technical}</p></details>}
      </div>
      {card.retryable && card.retry && (
        <Button size="sm" variant="outline" disabled={actions.busy} onClick={() => actions.sendTool(card.retry!, undefined)}>
          <RotateCw /> Retry
        </Button>
      )}
    </section>
  )
}
