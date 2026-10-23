import { ArrowUp, FileText, Square, X } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Button } from '@/design/ui/Button'
import { Kbd } from '@/design/ui/Kbd'
import { cn } from '@/lib/cn'
import type { CaseRecord } from '@/lib/persistence/storage'
import type { ToolName } from '@/types/agent'
import { PlusMenu } from './PlusMenu'
import { toolByName, TOOLS } from './tools'

export interface ComposerProps {
  matter: CaseRecord | null
  busy: boolean
  large?: boolean
  autoFocus?: boolean
  onSubmit: (text: string, tool: ToolName | null) => void
  onStop: () => void
  onAddCase: () => void
  onChooseCase: () => void
  onClearMatter: () => void
  /** Lets the page set a tool chip from outside (empty-state shortcuts, suggestions). */
  presetTool?: ToolName | null
  onPresetConsumed?: () => void
}

export function Composer({ matter, busy, large, autoFocus, onSubmit, onStop, onAddCase, onChooseCase, onClearMatter, presetTool, onPresetConsumed }: ComposerProps) {
  const [text, setText] = useState('')
  const [tool, setTool] = useState<ToolName | null>(null)
  const [plusOpen, setPlusOpen] = useState(false)
  const ref = useRef<HTMLTextAreaElement>(null)
  const spec = tool ? toolByName(tool) : null

  useEffect(() => {
    if (presetTool) {
      setTool(presetTool)
      onPresetConsumed?.()
      ref.current?.focus()
    }
  }, [presetTool, onPresetConsumed])

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = '0px'
    el.style.height = `${Math.min(el.scrollHeight, 8 * 24)}px`
  }, [text, large])
  useEffect(() => { if (autoFocus) ref.current?.focus() }, [autoFocus])

  // "/" at the start of an empty composer opens the same list as "+"
  const onChange = (v: string) => {
    if (v === '/' && !text) { setPlusOpen(true); return }
    setText(v)
  }

  const canSend = !busy && (Boolean(text.trim()) || Boolean(tool && !spec?.needsText && (!spec?.needsCase || matter)))
  const submit = () => {
    if (!canSend) return
    onSubmit(text.trim(), tool)
    setText('')
    setTool(null)
  }

  const placeholder = spec?.hint ?? (matter ? 'Ask about this matter, or press + to pick a tool' : 'Ask a legal research question, or press + to add a matter')

  return (
    <div className={cn('rounded-composer border border-border-strong bg-surface transition-colors focus-within:border-ink/60', large && 'shadow-float')}>
      {(matter || spec) && (
        <div className="flex flex-wrap items-center gap-1.5 px-3.5 pt-3">
          {matter && (
            <span className="group/chip inline-flex max-w-full items-center gap-1.5 rounded-lg border border-border bg-sunken py-1 pl-2 pr-1 text-sm">
              <FileText className="size-3.5 shrink-0 text-ink-muted" />
              <span className="truncate font-medium">{matter.title}</span>
              <span className="tnum shrink-0 text-xs text-ink-subtle">{matter.wordCount.toLocaleString()} words</span>
              <button type="button" aria-label="Detach matter" onClick={onClearMatter} className="rounded p-0.5 text-ink-subtle hover:bg-border hover:text-ink"><X className="size-3.5" /></button>
            </span>
          )}
          {spec && (
            <span className="inline-flex items-center gap-1.5 rounded-lg border border-accent/30 bg-accent-soft py-1 pl-2 pr-1 text-sm text-accent">
              <spec.icon className="size-3.5" />
              <span className="font-medium">{spec.label}</span>
              <button type="button" aria-label="Remove tool" onClick={() => setTool(null)} className="rounded p-0.5 hover:bg-accent/15"><X className="size-3.5" /></button>
            </span>
          )}
        </div>
      )}
      <textarea
        ref={ref} value={text} rows={1} aria-label="Message" placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit() }
          else if (e.key === 'Escape' && busy) onStop()
          else if (e.key === 'Backspace' && !text) { if (tool) setTool(null) }
        }}
        className={cn('block w-full resize-none bg-transparent px-4 text-base leading-6 outline-none placeholder:text-ink-subtle', large ? 'min-h-[3.5rem] py-4' : 'min-h-[2.75rem] py-3')}
      />
      <div className="flex items-center justify-between px-2.5 pb-2.5">
        <PlusMenu
          hasCase={Boolean(matter)} disabled={busy} open={plusOpen} onOpenChange={setPlusOpen}
          onAddCase={onAddCase} onChooseCase={onChooseCase}
          onPickTool={(t) => { setTool(t); window.setTimeout(() => ref.current?.focus(), 0) }}
        />
        <div className="flex items-center gap-2">
          {!busy && <span className="hidden items-center gap-1 text-xs text-ink-subtle sm:inline-flex"><Kbd>↵</Kbd> to send</span>}
          {busy ? (
            <Button size="icon" onClick={onStop} aria-label="Stop generating" className="rounded-sm"><Square className="size-3.5 fill-current" /></Button>
          ) : (
            <Button size="icon" onClick={submit} disabled={!canSend} aria-label="Send message" className="rounded-sm"><ArrowUp /></Button>
          )}
        </div>
      </div>
    </div>
  )
}

export { TOOLS }
