import { FileText } from 'lucide-react'
import type { Message } from './model'

export function UserMessage({ msg }: { msg: Message }) {
  const text = msg.parts.find((p) => p.kind === 'text')
  return (
    <article className="flex justify-end animate-rise-in" aria-label="Your message">
      <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-lg border border-border bg-sunken px-4 py-2.5 text-base text-ink">
        {msg.parts.filter((p) => p.kind === 'attachment').map((a) => a.kind === 'attachment' && (
          <span key={a.id} className="mb-2 flex items-center gap-2 rounded-lg border border-border bg-surface px-2.5 py-1.5 text-sm"><FileText className="size-4 text-ink-muted" />{a.title}</span>
        ))}
        {text?.kind === 'text' ? text.text : null}
      </div>
    </article>
  )
}
