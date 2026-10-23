import { openDB, type DBSchema, type IDBPDatabase } from 'idb'
import type { ExtractionQuality, CaseInputs } from '@/types/agent'
import type { Message } from '@/features/chat/model'

export interface ConversationRecord {
  id: string
  title: string
  caseId: string | null
  createdAt: number
  updatedAt: number
}

export interface CaseRecord {
  id: string // sha256 of the text
  title: string
  filename?: string
  wordCount: number
  source: 'sample' | 'upload' | 'paste'
  sampleId?: string
  createdAt: number
  lastUsedAt: number
  inputs: CaseInputs
  extraction?: ExtractionQuality | null
  preview: string
  court?: string
  year?: number
  sections?: string[]
  kind?: string
}

export type StoredMessage = Message & { convId: string; seq: number }

/** Everything the app persists. IndexedDB in the browser; a plain in-memory twin when storage is blocked (private mode, tests). */
export interface Storage {
  readonly kind: 'indexeddb' | 'memory'
  listConversations(): Promise<ConversationRecord[]>
  putConversation(c: ConversationRecord): Promise<void>
  deleteConversation(id: string): Promise<void>
  getMessages(convId: string): Promise<StoredMessage[]>
  putMessage(m: StoredMessage): Promise<void>
  deleteMessage(id: string): Promise<void>
  listCases(): Promise<CaseRecord[]>
  getCase(id: string): Promise<CaseRecord | undefined>
  putCase(c: CaseRecord): Promise<void>
  deleteCase(id: string): Promise<void>
  getCaseText(id: string): Promise<string | undefined>
  putCaseText(id: string, text: string): Promise<void>
  exportAll(): Promise<{ conversations: ConversationRecord[]; messages: StoredMessage[]; cases: CaseRecord[] }>
  clearAll(): Promise<void>
}

interface LitDB extends DBSchema {
  conversations: { key: string; value: ConversationRecord; indexes: { byUpdated: number } }
  messages: { key: string; value: StoredMessage; indexes: { byConv: [string, number] } }
  cases: { key: string; value: CaseRecord; indexes: { byUsed: number } }
  case_texts: { key: string; value: { id: string; text: string } }
  kv: { key: string; value: unknown }
}

async function open(name: string): Promise<IDBPDatabase<LitDB>> {
  return openDB<LitDB>(name, 1, {
    upgrade(db) {
      db.createObjectStore('conversations', { keyPath: 'id' }).createIndex('byUpdated', 'updatedAt')
      db.createObjectStore('messages', { keyPath: 'id' }).createIndex('byConv', ['convId', 'seq'])
      db.createObjectStore('cases', { keyPath: 'id' }).createIndex('byUsed', 'lastUsedAt')
      db.createObjectStore('case_texts', { keyPath: 'id' })
      db.createObjectStore('kv')
    },
  })
}

export async function createIndexedDbStorage(name = 'lit'): Promise<Storage> {
  const db = await open(name)
  return {
    kind: 'indexeddb',
    listConversations: async () => (await db.getAll('conversations')).sort((a, b) => b.updatedAt - a.updatedAt),
    putConversation: async (c) => void (await db.put('conversations', c)),
    deleteConversation: async (id) => {
      const tx = db.transaction(['conversations', 'messages'], 'readwrite')
      await tx.objectStore('conversations').delete(id)
      const range = IDBKeyRange.bound([id, 0], [id, Number.MAX_SAFE_INTEGER])
      let cursor = await tx.objectStore('messages').index('byConv').openCursor(range)
      while (cursor) {
        await cursor.delete()
        cursor = await cursor.continue()
      }
      await tx.done
    },
    getMessages: async (convId) => db.getAllFromIndex('messages', 'byConv', IDBKeyRange.bound([convId, 0], [convId, Number.MAX_SAFE_INTEGER])),
    putMessage: async (m) => void (await db.put('messages', m)),
    deleteMessage: async (id) => void (await db.delete('messages', id)),
    listCases: async () => (await db.getAll('cases')).sort((a, b) => b.lastUsedAt - a.lastUsedAt),
    getCase: (id) => db.get('cases', id),
    putCase: async (c) => void (await db.put('cases', c)),
    deleteCase: async (id) => {
      const tx = db.transaction(['cases', 'case_texts'], 'readwrite')
      await tx.objectStore('cases').delete(id)
      await tx.objectStore('case_texts').delete(id)
      await tx.done
    },
    getCaseText: async (id) => (await db.get('case_texts', id))?.text,
    putCaseText: async (id, text) => void (await db.put('case_texts', { id, text })),
    exportAll: async () => ({ conversations: await db.getAll('conversations'), messages: await db.getAll('messages'), cases: await db.getAll('cases') }),
    clearAll: async () => {
      for (const s of ['conversations', 'messages', 'cases', 'case_texts', 'kv'] as const) await db.clear(s)
    },
  }
}

export function createMemoryStorage(): Storage {
  const conversations = new Map<string, ConversationRecord>()
  const messages = new Map<string, StoredMessage>()
  const cases = new Map<string, CaseRecord>()
  const texts = new Map<string, string>()
  return {
    kind: 'memory',
    listConversations: async () => [...conversations.values()].sort((a, b) => b.updatedAt - a.updatedAt),
    putConversation: async (c) => void conversations.set(c.id, c),
    deleteConversation: async (id) => {
      conversations.delete(id)
      for (const [k, m] of messages) if (m.convId === id) messages.delete(k)
    },
    getMessages: async (convId) => [...messages.values()].filter((m) => m.convId === convId).sort((a, b) => a.seq - b.seq),
    putMessage: async (m) => void messages.set(m.id, m),
    deleteMessage: async (id) => void messages.delete(id),
    listCases: async () => [...cases.values()].sort((a, b) => b.lastUsedAt - a.lastUsedAt),
    getCase: async (id) => cases.get(id),
    putCase: async (c) => void cases.set(c.id, c),
    deleteCase: async (id) => {
      cases.delete(id)
      texts.delete(id)
    },
    getCaseText: async (id) => texts.get(id),
    putCaseText: async (id, text) => void texts.set(id, text),
    exportAll: async () => ({ conversations: [...conversations.values()], messages: [...messages.values()], cases: [...cases.values()] }),
    clearAll: async () => {
      conversations.clear()
      messages.clear()
      cases.clear()
      texts.clear()
    },
  }
}

let current: Promise<Storage> | null = null

/** The app's storage: IndexedDB if it works, otherwise memory (the UI renders either way). */
export function getStorage(): Promise<Storage> {
  current ??= (async () => {
    try {
      if (typeof indexedDB === 'undefined') throw new Error('no indexedDB')
      const s = await createIndexedDbStorage()
      void navigator.storage?.persist?.().catch(() => undefined) // ask the browser not to evict our data
      return s
    } catch {
      return createMemoryStorage()
    }
  })()
  return current
}

/** Tests inject their own storage. */
export function setStorageForTests(s: Storage | null): void {
  current = s ? Promise.resolve(s) : null
}
