import { createContext, useContext } from 'react'
import type { ForcedTool } from '@/types/agent'

/** What a message (or card inside it) can ask the surrounding conversation to do. */
export interface ChatActions {
  sendInput: (cardId: string, values: Record<string, string>, pending: ForcedTool | null | undefined) => void
  sendTool: (tool: ForcedTool, label?: string) => void
  sendText: (text: string) => void
  openCanvas: (cardId: string, focus?: string) => void
  retry: (assistantId: string) => void
  busy: boolean
  /** Pre-selected form answers (the sample session shows the recorded answer, waiting for Continue). */
  inputPrefill?: Record<string, string>
}

const noop: ChatActions = { sendInput() {}, sendTool() {}, sendText() {}, openCanvas() {}, retry() {}, busy: false }
const Ctx = createContext<ChatActions>(noop)

export const ChatActionsProvider = Ctx.Provider
export const useChatActions = () => useContext(Ctx)
