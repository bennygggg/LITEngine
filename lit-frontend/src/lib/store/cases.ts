import { create } from 'zustand'
import { putCase as registerCase, sha256Hex } from '@/api/agent'
import { getStorage, type CaseRecord } from '@/lib/persistence/storage'
import type { CaseInputs, CasePreview } from '@/types/agent'
import type { SampleMatter } from '@/features/matters/samples'

export interface NewCase {
  text: string
  title?: string
  filename?: string
  source: CaseRecord['source']
  sampleId?: string
  meta?: Partial<Pick<CaseRecord, 'court' | 'year' | 'sections' | 'kind'>>
}

interface CasesState {
  cases: CaseRecord[]
  loaded: boolean
  load: () => Promise<void>
  addCase: (input: NewCase) => Promise<CaseRecord>
  addSample: (sample: SampleMatter) => Promise<CaseRecord>
  updateInputs: (id: string, inputs: Partial<CaseInputs>) => Promise<void>
  setExtraction: (id: string, preview: CasePreview) => Promise<void>
  rename: (id: string, title: string) => Promise<void>
  touch: (id: string) => Promise<void>
  remove: (id: string) => Promise<void>
  text: (id: string) => Promise<string | undefined>
  /** Make sure the server's short-lived cache has this matter (cheap if already registered this session). */
  ensureRegistered: (id: string, force?: boolean) => Promise<CasePreview | null>
}

const registered = new Set<string>()

export function guessTitle(text: string, filename?: string): string {
  if (filename) return filename.replace(/\.[a-z0-9]+$/i, '').replace(/[_-]+/g, ' ').trim() || 'Uploaded matter'
  const line = text.split('\n').map((l) => l.trim()).find((l) => l.length > 8) ?? 'Untitled matter'
  return line.length > 80 ? `${line.slice(0, 77)}…` : line
}

export const useCases = create<CasesState>((set, get) => ({
  cases: [],
  loaded: false,

  async load() {
    const storage = await getStorage()
    set({ cases: await storage.listCases(), loaded: true })
  },

  async addCase(input) {
    const storage = await getStorage()
    const id = await sha256Hex(input.text)
    const existing = await storage.getCase(id)
    if (existing) {
      await get().touch(id)
      return { ...existing, lastUsedAt: Date.now() }
    }
    const now = Date.now()
    const record: CaseRecord = {
      id, title: input.title || guessTitle(input.text, input.filename), filename: input.filename,
      wordCount: input.text.split(/\s+/).filter(Boolean).length, source: input.source, sampleId: input.sampleId,
      createdAt: now, lastUsedAt: now, inputs: {}, preview: input.text.replace(/\s+/g, ' ').slice(0, 240), ...input.meta,
    }
    await storage.putCase(record)
    await storage.putCaseText(id, input.text)
    set({ cases: [record, ...get().cases] })
    return record
  },

  addSample: (sample) =>
    get().addCase({
      text: sample.text, title: sample.title, source: 'sample', sampleId: sample.id,
      meta: { court: sample.court, year: sample.year, sections: sample.sections, kind: sample.kind },
    }),

  async updateInputs(id, inputs) {
    const storage = await getStorage()
    const rec = await storage.getCase(id)
    if (!rec) return
    const next = { ...rec, inputs: { ...rec.inputs, ...inputs } }
    await storage.putCase(next)
    set({ cases: get().cases.map((c) => (c.id === id ? next : c)) })
  },

  async setExtraction(id, preview) {
    const storage = await getStorage()
    const rec = await storage.getCase(id)
    if (!rec) return
    const next = { ...rec, extraction: preview.extraction }
    await storage.putCase(next)
    set({ cases: get().cases.map((c) => (c.id === id ? next : c)) })
  },

  async rename(id, title) {
    const storage = await getStorage()
    const rec = await storage.getCase(id)
    if (!rec) return
    const next = { ...rec, title }
    await storage.putCase(next)
    set({ cases: get().cases.map((c) => (c.id === id ? next : c)) })
  },

  async touch(id) {
    const storage = await getStorage()
    const rec = await storage.getCase(id)
    if (!rec) return
    const next = { ...rec, lastUsedAt: Date.now() }
    await storage.putCase(next)
    set({ cases: [next, ...get().cases.filter((c) => c.id !== id)] })
  },

  async remove(id) {
    const storage = await getStorage()
    await storage.deleteCase(id)
    registered.delete(id)
    set({ cases: get().cases.filter((c) => c.id !== id) })
  },

  async text(id) {
    return (await getStorage()).getCaseText(id)
  },

  async ensureRegistered(id, force = false) {
    if (!force && registered.has(id)) return null
    const [rec, text] = await Promise.all([(await getStorage()).getCase(id), get().text(id)])
    if (!rec || text === undefined) throw new Error('This matter is no longer stored on this device.')
    const preview = await registerCase(id, { text, title: rec.title, filename: rec.filename })
    registered.add(id)
    void get().setExtraction(id, preview)
    return preview
  },
}))

export function __resetRegisteredForTests(): void {
  registered.clear()
}
