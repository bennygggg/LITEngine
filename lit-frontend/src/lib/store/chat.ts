import { create } from 'zustand'
import type { Message } from '@/features/chat/model'
import { settleInterrupted } from '@/features/chat/reducer'
import { newId } from '@/lib/id'
import { getStorage, type ConversationRecord, type StoredMessage } from '@/lib/persistence/storage'

interface ChatState {
  conversations: ConversationRecord[]
  messages: Record<string, Message[]>
  activeId: string | null
  loaded: boolean
  /** conversationId -> the run in flight (so the UI can show Stop and the controller can cancel it). */
  running: Record<string, { runId: string; abort: AbortController }>

  load: () => Promise<void>
  select: (id: string | null) => Promise<void>
  create: (caseId: string | null, title?: string) => Promise<ConversationRecord>
  setCase: (id: string, caseId: string | null) => Promise<void>
  rename: (id: string, title: string) => Promise<void>
  remove: (id: string) => Promise<void>
  /** Add or replace a message (by id) in memory; call `persist` when it settles. */
  upsertMessage: (convId: string, msg: Message) => void
  persist: (convId: string, msg: Message) => Promise<void>
  removeMessage: (convId: string, msgId: string) => Promise<void>
  setRunning: (convId: string, run: { runId: string; abort: AbortController } | null) => void
  markInputAnswered: (convId: string, cardId: string, values: Record<string, string>) => void
}

function seqOf(list: Message[], id: string): number {
  const i = list.findIndex((m) => m.id === id)
  return i >= 0 ? i : list.length
}

export const useChat = create<ChatState>((set, get) => ({
  conversations: [],
  messages: {},
  activeId: null,
  loaded: false,
  running: {},

  async load() {
    const storage = await getStorage()
    set({ conversations: await storage.listConversations(), loaded: true })
  },

  async select(id) {
    set({ activeId: id })
    if (!id || get().messages[id]) return
    const stored = await (await getStorage()).getMessages(id)
    set({ messages: { ...get().messages, [id]: stored.map((m) => settleInterrupted(m)) } })
  },

  async create(caseId, title = 'New conversation') {
    const now = Date.now()
    const conv: ConversationRecord = { id: newId('c'), title, caseId, createdAt: now, updatedAt: now }
    await (await getStorage()).putConversation(conv)
    set({ conversations: [conv, ...get().conversations], messages: { ...get().messages, [conv.id]: [] }, activeId: conv.id })
    return conv
  },

  async setCase(id, caseId) {
    const conv = get().conversations.find((c) => c.id === id)
    if (!conv) return
    const next = { ...conv, caseId, updatedAt: Date.now() }
    set({ conversations: get().conversations.map((c) => (c.id === id ? next : c)) }) // state first: concurrent writers must see it
    await (await getStorage()).putConversation(next)
  },

  async rename(id, title) {
    const conv = get().conversations.find((c) => c.id === id)
    if (!conv) return
    const next = { ...conv, title }
    set({ conversations: get().conversations.map((c) => (c.id === id ? next : c)) })
    await (await getStorage()).putConversation(next)
  },

  async remove(id) {
    get().running[id]?.abort.abort()
    await (await getStorage()).deleteConversation(id)
    const { [id]: _gone, ...rest } = get().messages
    set({ conversations: get().conversations.filter((c) => c.id !== id), messages: rest, activeId: get().activeId === id ? null : get().activeId })
  },

  upsertMessage(convId, msg) {
    const list = get().messages[convId] ?? []
    const i = list.findIndex((m) => m.id === msg.id)
    const next = i >= 0 ? [...list.slice(0, i), msg, ...list.slice(i + 1)] : [...list, msg]
    set({ messages: { ...get().messages, [convId]: next } })
  },

  async persist(convId, msg) {
    const list = get().messages[convId] ?? []
    const stored: StoredMessage = { ...msg, convId, seq: seqOf(list, msg.id) }
    const conv = get().conversations.find((c) => c.id === convId)
    const next = conv ? { ...conv, updatedAt: Date.now() } : null
    if (next) set({ conversations: [next, ...get().conversations.filter((c) => c.id !== convId)] }) // bump to the top immediately
    const storage = await getStorage()
    await storage.putMessage(stored)
    // Re-read: a rename may have landed while the message was being written.
    const latest = get().conversations.find((c) => c.id === convId)
    if (latest) await storage.putConversation(latest)
  },

  async removeMessage(convId, msgId) {
    set({ messages: { ...get().messages, [convId]: (get().messages[convId] ?? []).filter((m) => m.id !== msgId) } })
    await (await getStorage()).deleteMessage(msgId)
  },

  setRunning(convId, run) {
    const { [convId]: _old, ...rest } = get().running
    set({ running: run ? { ...rest, [convId]: run } : rest })
  },

  markInputAnswered(convId, cardId, values) {
    const list = get().messages[convId] ?? []
    set({
      messages: {
        ...get().messages,
        [convId]: list.map((m) => ({
          ...m,
          parts: m.parts.map((p) => (p.kind === 'input' && p.cardId === cardId ? { ...p, answered: values } : p)),
        })),
      },
    })
  },
}))
