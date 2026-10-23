import * as Tabs from '@radix-ui/react-tabs'
import { CircleAlert, FileText, Search, Upload } from 'lucide-react'
import { useMemo, useRef, useState } from 'react'
import { ACCEPTED, uploadDocument } from '@/api/upload'
import { Badge } from '@/design/ui/Badge'
import { Button } from '@/design/ui/Button'
import { Dialog, DialogContent } from '@/design/ui/Dialog'
import { cn } from '@/lib/cn'
import type { CaseRecord } from '@/lib/persistence/storage'
import { useCases } from '@/lib/store/cases'
import { SAMPLE_MATTERS, type SampleMatter } from './samples'

export type MatterTab = 'upload' | 'paste' | 'matters'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  defaultTab?: MatterTab
  onSelect: (record: CaseRecord) => void
}

const tabCls = 'relative px-1 pb-2.5 pt-1 text-sm text-ink-muted outline-none transition-colors hover:text-ink data-[state=active]:text-ink data-[state=active]:after:absolute data-[state=active]:after:inset-x-0 data-[state=active]:after:-bottom-px data-[state=active]:after:h-0.5 data-[state=active]:after:bg-ink'

export function AddMatterDialog({ open, onOpenChange, defaultTab = 'matters', onSelect }: Props) {
  const [tab, setTab] = useState<MatterTab>(defaultTab)
  const [prevOpen, setPrevOpen] = useState(false)
  if (open && !prevOpen) setTab(defaultTab) // reopen on the tab the caller asked for
  if (open !== prevOpen) setPrevOpen(open)

  const choose = (r: CaseRecord) => { onSelect(r); onOpenChange(false) }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent wide title="Add a matter" description="Upload a judgment, paste text, or start from a sample. Everything stays on this device until you ask a question.">
        <Tabs.Root value={tab} onValueChange={(v) => setTab(v as MatterTab)} className="flex min-h-0 flex-1 flex-col">
          <Tabs.List className="flex gap-6 border-b border-border px-6 pt-3" aria-label="How to add a matter">
            <Tabs.Trigger value="matters" className={tabCls}>Matters</Tabs.Trigger>
            <Tabs.Trigger value="upload" className={tabCls}>Upload</Tabs.Trigger>
            <Tabs.Trigger value="paste" className={tabCls}>Paste text</Tabs.Trigger>
          </Tabs.List>
          <Tabs.Content value="matters" className="min-h-0 flex-1 overflow-y-auto outline-none"><Library onChoose={choose} /></Tabs.Content>
          <Tabs.Content value="upload" className="min-h-0 flex-1 overflow-y-auto outline-none"><UploadTab onChoose={choose} /></Tabs.Content>
          <Tabs.Content value="paste" className="min-h-0 flex-1 overflow-y-auto outline-none"><PasteTab onChoose={choose} /></Tabs.Content>
        </Tabs.Root>
      </DialogContent>
    </Dialog>
  )
}

// --- library ----------------------------------------------------------------------------

function Library({ onChoose }: { onChoose: (r: CaseRecord) => void }) {
  const cases = useCases((s) => s.cases)
  const addSample = useCases((s) => s.addSample)
  const [q, setQ] = useState('')
  const needle = q.trim().toLowerCase()
  const mine = useMemo(() => cases.filter((c) => c.source !== 'sample' && (!needle || `${c.title} ${c.filename ?? ''}`.toLowerCase().includes(needle))), [cases, needle])
  const samples = useMemo(() => SAMPLE_MATTERS.filter((s) => !needle || `${s.title} ${s.court} ${s.sections.join(' ')} ${s.kind}`.toLowerCase().includes(needle)), [needle])

  return (
    <div className="px-6 pb-5 pt-4">
      <label className="relative mb-4 block">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-subtle" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by name, court or section" aria-label="Search matters"
          className="h-10 w-full rounded-lg border border-border-strong bg-surface pl-9 pr-3 text-sm outline-none focus:border-ink" />
      </label>
      {mine.length > 0 && (
        <section className="mb-5">
          <h3 className="mb-1.5 text-xs font-medium text-ink-subtle">My matters</h3>
          <ul className="divide-y divide-border rounded-lg border border-border">
            {mine.map((c) => <MatterRow key={c.id} title={c.title} meta={[`${c.wordCount.toLocaleString()} words`, c.source === 'upload' ? 'Uploaded' : 'Pasted']} onChoose={() => onChoose(c)} />)}
          </ul>
        </section>
      )}
      <section>
        <h3 className="mb-1.5 flex items-center gap-2 text-xs font-medium text-ink-subtle">Sample matters <Badge tone="outline">Fictional</Badge></h3>
        <ul className="divide-y divide-border rounded-lg border border-border">
          {samples.map((s: SampleMatter) => (
            <MatterRow key={s.id} title={s.title} meta={[s.court, String(s.year), s.kind]} chips={s.sections} onChoose={async () => onChoose(await addSample(s))} />
          ))}
          {samples.length === 0 && <li className="px-4 py-6 text-center text-sm text-ink-muted">No sample matters match “{q}”.</li>}
        </ul>
      </section>
    </div>
  )
}

function MatterRow({ title, meta, chips, onChoose }: { title: string; meta: string[]; chips?: string[]; onChoose: () => void }) {
  return (
    <li>
      <button type="button" onClick={onChoose} className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-sunken focus-visible:bg-sunken">
        <FileText className="mt-0.5 size-4 shrink-0 text-ink-muted" />
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium">{title}</span>
          <span className="mt-0.5 block text-sm text-ink-muted">{meta.filter(Boolean).join(' · ')}</span>
          {chips && chips.length > 0 && <span className="mt-1.5 flex flex-wrap gap-1">{chips.map((c) => <Badge key={c}>{c}</Badge>)}</span>}
        </span>
        <span className="mt-0.5 shrink-0 text-sm text-accent">Use</span>
      </button>
    </li>
  )
}

// --- upload -----------------------------------------------------------------------------

function UploadTab({ onChoose }: { onChoose: (r: CaseRecord) => void }) {
  const add = useCases((s) => s.addCase)
  const input = useRef<HTMLInputElement>(null)
  const [drag, setDrag] = useState(false)
  const [state, setState] = useState<{ name: string; fraction: number; phase: 'uploading' | 'extracting' } | null>(null)
  const [error, setError] = useState<string | null>(null)

  const run = async (file: File) => {
    setError(null)
    setState({ name: file.name, fraction: 0, phase: 'uploading' })
    try {
      const doc = await uploadDocument(file, (fraction, phase) => setState({ name: file.name, fraction, phase }))
      const rec = await add({ text: doc.text, filename: doc.filename || file.name, source: 'upload' })
      setState(null)
      onChoose(rec)
    } catch (e) {
      setState(null)
      setError((e as Error).message)
    }
  }

  return (
    <div className="px-6 pb-6 pt-5">
      <div
        onDragOver={(e) => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files[0]; if (f) void run(f) }}
        className={cn('flex flex-col items-center justify-center rounded-xl border border-dashed px-6 py-12 text-center transition-colors', drag ? 'border-ink bg-sunken' : 'border-border-strong')}
      >
        <Upload className="mb-3 size-6 text-ink-muted" />
        {state ? (
          <div className="w-full max-w-xs" role="status">
            <p className="mb-2 truncate text-sm font-medium">{state.name}</p>
            <div className="h-1.5 overflow-hidden rounded-full bg-border"><div className={cn('h-full bg-ink transition-all', state.phase === 'extracting' && 'animate-pulse')} style={{ width: `${Math.round(state.fraction * 100)}%` }} /></div>
            <p className="mt-2 text-xs text-ink-muted">{state.phase === 'uploading' ? 'Uploading…' : 'Reading the document…'}</p>
          </div>
        ) : (
          <>
            <p className="font-medium">Drop a judgment here</p>
            <p className="mt-1 text-sm text-ink-muted">PDF, Word or text · up to 20 MB</p>
            <Button className="mt-4" variant="outline" onClick={() => input.current?.click()}>Choose a file</Button>
            <input ref={input} type="file" accept={ACCEPTED} className="sr-only" aria-label="Choose a file to upload" onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) void run(f) }} />
          </>
        )}
      </div>
      {error && (
        <p role="alert" className="mt-3 flex items-start gap-2 rounded-lg border border-border-strong bg-sunken px-3.5 py-2.5 text-sm"><CircleAlert className="mt-0.5 size-4 shrink-0" />{error}</p>
      )}
      <p className="mt-3 text-xs text-ink-muted">Scanned PDFs without a text layer can’t be read yet (no OCR) — paste the text instead.</p>
    </div>
  )
}

// --- paste ------------------------------------------------------------------------------

function PasteTab({ onChoose }: { onChoose: (r: CaseRecord) => void }) {
  const add = useCases((s) => s.addCase)
  const [text, setText] = useState('')
  const [title, setTitle] = useState('')
  const words = text.split(/\s+/).filter(Boolean).length
  return (
    <div className="space-y-3 px-6 pb-6 pt-5">
      <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Title (optional)" aria-label="Title"
        className="h-10 w-full rounded-lg border border-border-strong bg-surface px-3 text-sm outline-none focus:border-ink" />
      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={10} placeholder="Paste the judgment or case text here" aria-label="Case text"
        className="w-full resize-y rounded-lg border border-border-strong bg-surface p-3 text-sm leading-6 outline-none focus:border-ink" />
      <div className="flex items-center justify-between">
        <span className="tnum text-xs text-ink-muted">{words.toLocaleString()} words</span>
        <Button disabled={words < 40} onClick={async () => onChoose(await add({ text: text.trim(), title: title.trim() || undefined, source: 'paste' }))}>Use this text</Button>
      </div>
      {words > 0 && words < 40 && <p className="text-xs text-ink-muted">That is very short — paste at least a few paragraphs so there is something to analyse.</p>}
    </div>
  )
}
