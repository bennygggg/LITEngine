import { stopRun, waitForHealthy } from '@/api/agent'
import { apiBase } from '@/api/client'
import { newId } from '@/lib/id'
import { AgentHttpError, ColdStartError, StallError } from '@/lib/sse/errors'
import { streamAgentEvents } from '@/lib/sse/transport'
import { useCases } from '@/lib/store/cases'
import { useChat } from '@/lib/store/chat'
import { useEngine } from '@/lib/store/engine'
import { useUi } from '@/lib/store/ui'
import type { AgentChatRequest, AgentEvent, ForcedTool, ToolName } from '@/types/agent'
import type { Message, UserRequest } from './model'
import { messageText, newAssistantMessage, reduceEvent } from './reducer'

export const TOOL_LABELS: Record<ToolName, string> = {
  extract_case_facts: 'Read the case',
  search_precedents: 'Find precedents',
  build_argument_map: 'Map the argument',
  assess_outcome: 'Assess the outcome',
  run_scenario: 'Explore scenarios',
  ask_case: 'Ask about the case',
  inspect_artifact: 'Inspect',
  full_review: 'Full case review',
}

const APP_VERSION = (import.meta.env as Record<string, string | undefined>).VITE_APP_VERSION ?? '1.0.0-dev'
const HISTORY_TURNS = 12

export interface ControllerDeps {
  stream: typeof streamAgentEvents
  raf: (cb: () => void) => void
  sleep: (ms: number) => Promise<void>
  waitHealthy: typeof waitForHealthy
  stop: typeof stopRun
}

export const defaultDeps: ControllerDeps = {
  stream: streamAgentEvents,
  raf: (cb) => (typeof requestAnimationFrame === 'function' ? requestAnimationFrame(() => cb()) : void setTimeout(cb, 16)),
  sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
  waitHealthy: waitForHealthy,
  stop: stopRun,
}

export interface SendArgs extends UserRequest {
  conversationId: string
  /** Re-run a failed turn: reuse the user message instead of adding a new one. */
  reuseUserMessageId?: string
}

function summariseInputs(values: Record<string, string>): string {
  const who = { accused_appeal: "Appeal by the accused", state_appeal: 'Appeal by the State or complainant', unclear: 'Appeal type not specified' }[values.appellant_type ?? ''] ?? ''
  const when = values.filing_date ? `filed ${new Date(values.filing_date).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })}` : ''
  return [who, when].filter(Boolean).join(' · ') || 'Details provided'
}

export function displayTextFor(req: UserRequest): string {
  if (req.inputResponse) return summariseInputs(req.inputResponse.values)
  if (req.forcedTool) {
    const label = TOOL_LABELS[req.forcedTool.name]
    const q = (req.forcedTool.args as { query?: string }).query || req.text
    return q ? `${label} — ${q}` : label
  }
  return req.text
}

/** Text-only history the server rebuilds its context from (cards are re-described server-side, never replayed). */
export function historyFor(messages: Message[]): NonNullable<AgentChatRequest['messages']> {
  return messages
    .map((m) => ({ role: m.role, content: (m.role === 'user' ? (m.parts.find((p) => p.kind === 'text') as { text: string } | undefined)?.text ?? '' : messageText(m)).slice(0, 8000) }))
    .filter((m) => m.content.trim().length > 0)
    .slice(-HISTORY_TURNS) as NonNullable<AgentChatRequest['messages']>
}

export async function sendMessage(args: SendArgs, deps: ControllerDeps = defaultDeps): Promise<void> {
  const chat = useChat.getState()
  const conv = chat.conversations.find((c) => c.id === args.conversationId)
  if (!conv || chat.running[conv.id]) return

  const caseRecord = conv.caseId ? useCases.getState().cases.find((c) => c.id === conv.caseId) ?? null : null
  const prior = chat.messages[conv.id] ?? []

  // 1. the user's message (or reuse it on a retry)
  let userMsg: Message | undefined = args.reuseUserMessageId ? prior.find((m) => m.id === args.reuseUserMessageId) : undefined
  const historyBase = userMsg ? prior.slice(0, prior.indexOf(userMsg)) : prior
  if (!userMsg) {
    userMsg = {
      id: newId('m'), role: 'user', createdAt: Date.now(), status: 'complete', notices: [], suggestions: [], lastSeq: 0,
      request: { text: args.text, forcedTool: args.forcedTool ?? null, inputResponse: args.inputResponse ?? null },
      parts: [{ kind: 'text', id: 'u1', text: displayTextFor(args) }],
    }
    chat.upsertMessage(conv.id, userMsg)
    void chat.persist(conv.id, userMsg)
    if (prior.length === 0 && conv.title === 'New conversation') {
      void chat.rename(conv.id, (args.text || displayTextFor(args)).slice(0, 56) || caseRecord?.title || 'New conversation')
    }
  }
  if (args.inputResponse) chat.markInputAnswered(conv.id, args.inputResponse.card_id, args.inputResponse.values)

  // 2. the assistant message that will receive the stream
  const runId = newId('r')
  let msg: Message = newAssistantMessage(newId('m'))
  msg.runId = runId
  chat.upsertMessage(conv.id, msg)
  const abort = new AbortController()
  chat.setRunning(conv.id, { runId, abort })
  void useCases.getState().touch(conv.caseId ?? '')

  // 3. the request
  const inputs = caseRecord?.inputs ?? {}
  const body: AgentChatRequest = {
    client: { version: APP_VERSION, schema_version: 1 },
    conversation_id: conv.id,
    run_id: runId,
    retry_of: args.reuseUserMessageId ? runId : null,
    messages: historyFor(historyBase),
    user_message: { text: args.text, forced_tool: args.forcedTool ?? null, input_response: args.inputResponse ? { ...args.inputResponse, pending: args.inputResponse.pending ?? null } : null },
    case: caseRecord ? { ref: caseRecord.id, title: caseRecord.title, inputs, profile_override: null } : null,
    options: { mode: 'auto', narrate: useUi.getState().aiNarration ? 'llm' : 'template' },
  }

  // 4. stream, with batching and recovery
  const queue: AgentEvent[] = []
  let scheduled = false
  let lastPersist = 0
  const flush = () => {
    scheduled = false
    if (!queue.length) return
    for (const ev of queue.splice(0)) {
      // The server restarted mid-run and answered a resume with a fresh run: discard the partial and start over.
      if (ev.event === 'message_start' && msg.lastSeq > 0 && ev.seq <= msg.lastSeq) msg = { ...newAssistantMessage(msg.id, msg.createdAt), runId: msg.runId }
      msg = reduceEvent(msg, ev)
    }
    useChat.getState().upsertMessage(conv.id, msg)
    if (Date.now() - lastPersist > 1000) {
      lastPersist = Date.now()
      void useChat.getState().persist(conv.id, msg)
    }
  }
  const schedule = () => {
    if (!scheduled) {
      scheduled = true
      deps.raf(flush)
    }
  }

  const url = `${apiBase()}/agent/chat`
  let busyRetries = 0
  let wakeRetries = 0
  let stallRetries = 0
  let reregistered = false
  let finished = false
  try {
    if (caseRecord) await useCases.getState().ensureRegistered(caseRecord.id)
    while (!finished) {
      if (abort.signal.aborted) break // Stop pressed while the matter was still being registered
      try {
        let sawDone = false
        for await (const ev of deps.stream({ url, body, signal: abort.signal, lastEventId: msg.lastSeq || undefined })) {
          queue.push(ev)
          if (ev.event === 'done') sawDone = true
          schedule()
        }
        if (!sawDone) throw new StallError() // the connection closed cleanly but the run never finished: resume it
        finished = true
      } catch (err) {
        if (abort.signal.aborted) break
        if (err instanceof AgentHttpError && err.code === 'case_unknown' && caseRecord && !reregistered) {
          reregistered = true
          await useCases.getState().ensureRegistered(caseRecord.id, true)
          continue
        }
        if (err instanceof AgentHttpError && err.status === 429 && busyRetries < 3) {
          busyRetries += 1
          await deps.sleep((err.retryAfter ?? 5) * 1000)
          continue
        }
        if (err instanceof ColdStartError && wakeRetries < 1) {
          wakeRetries += 1
          useEngine.getState().setWaking()
          const ok = await deps.waitHealthy(abort.signal)
          if (!ok) throw err
          useEngine.getState().setOnline()
          continue
        }
        if (err instanceof StallError && stallRetries < 2) {
          stallRetries += 1 // resume: the server replays events after lastSeq
          continue
        }
        throw err
      }
    }
  } catch (err) {
    const aborted = abort.signal.aborted
    const message =
      err instanceof AgentHttpError && err.code === 'client_outdated' ? 'This version of the app is out of date — please refresh the page.'
      : err instanceof AgentHttpError && err.code === 'agent_disabled' ? 'The assistant is switched off on this server.'
      : err instanceof AgentHttpError && err.status === 429 ? 'The assistant is busy right now. Please try again in a moment.'
      : err instanceof ColdStartError ? 'The research engine could not be reached. It may still be waking up — try again in a minute.'
      : err instanceof StallError ? 'The connection dropped before the answer finished.'
      : (err as Error)?.message || 'Something went wrong.'
    if (!aborted) {
      queue.push({ event: 'error', v: 1, seq: msg.lastSeq + 1, t: 0, code: 'client_error', message, scope: 'run', retryable: true } as AgentEvent)
      queue.push({ event: 'done', v: 1, seq: msg.lastSeq + 2, t: 0, status: 'error', message_id: msg.id, usage: { input_tokens: 0, output_tokens: 0, llm_calls: 0 }, timings: { total_ms: 0 }, warnings: [] } as AgentEvent)
    }
  } finally {
    if (abort.signal.aborted && msg.status === 'streaming') {
      queue.push({ event: 'done', v: 1, seq: msg.lastSeq + 1, t: 0, status: 'cancelled', message_id: msg.id, usage: { input_tokens: 0, output_tokens: 0, llm_calls: 0 }, timings: { total_ms: 0 }, warnings: [] } as AgentEvent)
    }
    flush()
    useChat.getState().setRunning(conv.id, null)
    await useChat.getState().persist(conv.id, msg)
    if (msg.caseInputs && conv.caseId) await useCases.getState().updateInputs(conv.caseId, msg.caseInputs)
  }
}

/** Stop the run in a conversation: abort the fetch and tell the server to stop work (best effort). */
export function stopConversation(convId: string, deps: ControllerDeps = defaultDeps): void {
  const run = useChat.getState().running[convId]
  if (!run) return
  run.abort.abort()
  void deps.stop(run.runId)
}

/** Re-run the turn that produced `assistantId` (after an error or an interruption). */
export async function retryMessage(convId: string, assistantId: string, deps: ControllerDeps = defaultDeps): Promise<void> {
  const list = useChat.getState().messages[convId] ?? []
  const idx = list.findIndex((m) => m.id === assistantId)
  const user = idx > 0 ? [...list.slice(0, idx)].reverse().find((m) => m.role === 'user') : undefined
  if (!user?.request) return
  await useChat.getState().removeMessage(convId, assistantId)
  await sendMessage({ conversationId: convId, ...user.request, reuseUserMessageId: user.id }, deps)
}

export type { ForcedTool }
