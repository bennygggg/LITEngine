import { vi } from 'vitest'
import type { AgentEvent } from '@/types/agent'
import paused from '@/test/fixtures/full_review_paused.json'
import resumed from '@/test/fixtures/full_review_resumed.json'
import type * as AgentApi from '@/api/agent'
import ask from '@/test/fixtures/ask.json'

vi.mock('@/api/agent', async (orig) => {
  const real = await orig<typeof AgentApi>()
  return { ...real, putCase: vi.fn(async (sha: string) => ({ ref: sha, known: true, word_count: 10, detected: { sections: [] }, extraction: { method: 'rules', quality: 'good', completeness: 1, missing: [] } })), stopRun: vi.fn(async () => null) }
})

import * as agentApi from '@/api/agent'
import { createMemoryStorage, setStorageForTests } from '@/lib/persistence/storage'
import { AgentHttpError, ColdStartError, StallError } from '@/lib/sse/errors'
import { __resetRegisteredForTests, useCases } from '@/lib/store/cases'
import { useChat } from '@/lib/store/chat'
import { useEngine } from '@/lib/store/engine'
import type { Message } from './model'
import { type ControllerDeps, historyFor, retryMessage, sendMessage, stopConversation } from './runController'

const ev = (x: unknown) => x as AgentEvent[]
async function* from(events: AgentEvent[], then?: () => never): AsyncGenerator<AgentEvent> {
  for (const e of events) yield e
  if (then) then()
}
const hang = async function* (signal: AbortSignal): AsyncGenerator<AgentEvent> {
  await new Promise((_r, rej) => signal.addEventListener('abort', () => rej(Object.assign(new Error('aborted'), { name: 'AbortError' }))))
  yield undefined as never
}

function deps(over: Partial<ControllerDeps> = {}): ControllerDeps {
  return {
    stream: (() => from([])) as unknown as ControllerDeps['stream'],
    raf: (cb) => cb(), sleep: async () => undefined, waitHealthy: async () => true, stop: vi.fn(async () => null) as unknown as ControllerDeps['stop'], ...over,
  }
}

let convId = ''
let caseId = ''
beforeEach(async () => {
  setStorageForTests(createMemoryStorage())
  __resetRegisteredForTests()
  vi.clearAllMocks()
  useChat.setState({ conversations: [], messages: {}, activeId: null, running: {}, loaded: false })
  useCases.setState({ cases: [], loaded: false })
  const rec = await useCases.getState().addCase({ text: 'IN THE HIGH COURT. Ramesh Kumar v State. The appellant was convicted.', title: 'Ramesh Kumar v. State', source: 'paste' })
  caseId = rec.id
  convId = (await useChat.getState().create(caseId)).id
})

const messages = () => useChat.getState().messages[convId] ?? []
const assistant = () => messages().filter((m) => m.role === 'assistant').at(-1)!

describe('sendMessage', () => {
  it('streams a run into the store, persists it, and records the inputs the server resolved', async () => {
    const stream = vi.fn(() => from(ev(resumed)))
    await sendMessage({ conversationId: convId, text: '', forcedTool: { name: 'full_review', args: {} } }, deps({ stream: stream as never }))
    const a = assistant()
    expect(a.status).toBe('complete')
    expect(a.parts.filter((p) => p.kind === 'card').map((p) => p.kind === 'card' && p.payload?.type)).toEqual(['precedents', 'argument_map', 'outcome'])
    expect(useChat.getState().running[convId]).toBeUndefined()
    expect(messages()[0]).toMatchObject({ role: 'user' })
    const stored = await (await import('@/lib/persistence/storage')).getStorage().then((s) => s.getMessages(convId))
    expect(stored).toHaveLength(2)
    expect((await (await import('@/lib/persistence/storage')).getStorage().then((s) => s.getCase(caseId)))?.inputs.appellant_type).toBe('accused_appeal')
    const body = (stream.mock.calls[0] as unknown as [{ body: { case: { ref: string }; user_message: { forced_tool: { name: string } } } }])[0].body
    expect(body.case.ref).toBe(caseId)
    expect(body.user_message.forced_tool.name).toBe('full_review')
  })

  it('registers the matter with the server before the first run', async () => {
    await sendMessage({ conversationId: convId, text: 'hi' }, deps({ stream: (() => from(ev(ask))) as never }))
    expect(agentApi.putCase).toHaveBeenCalledTimes(1)
    await sendMessage({ conversationId: convId, text: 'again' }, deps({ stream: (() => from(ev(ask))) as never }))
    expect(agentApi.putCase).toHaveBeenCalledTimes(1) // already registered this session
  })

  it('an answered form is marked answered and the run resumes the pending tool', async () => {
    await sendMessage({ conversationId: convId, text: '', forcedTool: { name: 'full_review', args: {} } }, deps({ stream: (() => from(ev(paused))) as never }))
    expect(assistant().status).toBe('awaiting_input')
    const input = assistant().parts.find((p) => p.kind === 'input')!
    if (input.kind !== 'input') throw new Error()
    await sendMessage({ conversationId: convId, text: '', inputResponse: { card_id: input.cardId, values: { appellant_type: 'accused_appeal', filing_date: '2021-04-12' }, pending: input.payload.pending } },
      deps({ stream: (() => from(ev(resumed))) as never }))
    const first = messages().find((m) => m.role === 'assistant')!
    expect(first.parts.find((p) => p.kind === 'input')).toMatchObject({ answered: { appellant_type: 'accused_appeal' } })
    expect(messages().filter((m) => m.role === 'user').at(-1)!.parts[0]).toMatchObject({ text: 'Appeal by the accused · filed 12 Apr 2021' })
  })

  it('rides out a cold start: waits for health, then retries and completes', async () => {
    let calls = 0
    const waitHealthy = vi.fn(async () => true)
    const stream = vi.fn(() => { calls += 1; return calls === 1 ? (async function* () { throw new ColdStartError() })() : from(ev(ask)) })
    await sendMessage({ conversationId: convId, text: 'q' }, deps({ stream: stream as never, waitHealthy }))
    expect(waitHealthy).toHaveBeenCalledTimes(1)
    expect(assistant().status).toBe('complete')
    expect(useEngine.getState().state).toBe('online')
  })

  it('re-registers the matter on 409 case_unknown (a restarted server) and retries silently', async () => {
    let calls = 0
    const stream = vi.fn(() => { calls += 1; return calls === 1 ? (async function* () { throw new AgentHttpError(409, 'case_unknown', 'unknown') })() : from(ev(ask)) })
    await sendMessage({ conversationId: convId, text: 'q' }, deps({ stream: stream as never }))
    expect(agentApi.putCase).toHaveBeenCalledTimes(2)
    expect(assistant().status).toBe('complete')
    expect(assistant().notices).toEqual([])
  })

  it('backs off and retries when the server is busy', async () => {
    let calls = 0
    const sleep = vi.fn(async () => undefined)
    const stream = vi.fn(() => { calls += 1; return calls < 3 ? (async function* () { throw new AgentHttpError(429, 'busy', 'busy', 2) })() : from(ev(ask)) })
    await sendMessage({ conversationId: convId, text: 'q' }, deps({ stream: stream as never, sleep }))
    expect(sleep).toHaveBeenNthCalledWith(1, 2000)
    expect(assistant().status).toBe('complete')
  })

  it('resumes after a stalled connection using the last event id, without duplicating content', async () => {
    const all = ev(resumed)
    const cut = 7
    let calls = 0
    const stream = vi.fn((o: { lastEventId?: number }) => { calls += 1; return calls === 1 ? from(all.slice(0, cut), () => { throw new StallError() }) : from(all.filter((e) => e.seq > (o.lastEventId ?? 0))) })
    await sendMessage({ conversationId: convId, text: '' , forcedTool: { name: 'full_review', args: {} } }, deps({ stream: stream as never }))
    expect(stream).toHaveBeenCalledTimes(2)
    expect((stream.mock.calls[1] as unknown as [{ lastEventId: number }])[0].lastEventId).toBe(all[cut - 1]!.seq)
    expect(assistant().parts.filter((p) => p.kind === 'card')).toHaveLength(3)
    expect(assistant().status).toBe('complete')
  })

  it('a server that restarted mid-run (fresh run on resume) replaces the partial message instead of freezing', async () => {
    const all = ev(resumed)
    let calls = 0
    const stream = vi.fn(() => { calls += 1; return calls === 1 ? from(all.slice(0, 8), () => { throw new StallError() }) : from(all) })
    await sendMessage({ conversationId: convId, text: '', forcedTool: { name: 'full_review', args: {} } }, deps({ stream: stream as never }))
    expect(assistant().status).toBe('complete')
    expect(assistant().parts.filter((p) => p.kind === 'card')).toHaveLength(3)
  })

  it('a stream that closes without finishing is treated as a dropped connection, then reported honestly', async () => {
    const stream = vi.fn(() => from(ev(resumed).slice(0, 5)))
    await sendMessage({ conversationId: convId, text: '', forcedTool: { name: 'full_review', args: {} } }, deps({ stream: stream as never }))
    expect(stream).toHaveBeenCalledTimes(3) // first attempt + two resumes
    expect(assistant().status).toBe('error')
    expect(assistant().notices.at(-1)).toMatchObject({ scope: 'run', retryable: true })
    expect(assistant().parts.some((p) => p.kind === 'step' && p.status === 'running')).toBe(false)
  })

  it('stop cancels the run, tells the server, and leaves a cancelled message', async () => {
    const stop = vi.fn(async () => null)
    const pending = sendMessage({ conversationId: convId, text: 'slow' }, deps({ stream: ((o: { signal: AbortSignal }) => hang(o.signal)) as never, stop: stop as never }))
    await vi.waitFor(() => expect(useChat.getState().running[convId]).toBeDefined())
    stopConversation(convId, deps({ stop: stop as never }))
    await pending
    expect(assistant().status).toBe('cancelled')
    expect(stop).toHaveBeenCalledOnce()
    expect(useChat.getState().running[convId]).toBeUndefined()
  })

  it('shows a plain-language error for a network failure and retry re-runs the same request', async () => {
    const fail = vi.fn(() => (async function* () { throw new Error('boom') })())
    await sendMessage({ conversationId: convId, text: 'tell me about the case' }, deps({ stream: fail as never }))
    expect(assistant().status).toBe('error')
    expect(assistant().notices[0]!.message).toBe('boom')
    const failedId = assistant().id
    const ok = vi.fn(() => from(ev(ask)))
    await retryMessage(convId, failedId, deps({ stream: ok as never }))
    expect(messages().filter((m) => m.role === 'user')).toHaveLength(1) // the user's message is reused, not duplicated
    expect(messages().some((m) => m.id === failedId)).toBe(false)
    expect(assistant().status).toBe('complete')
  })

  it('does not start a second run while one is in flight', async () => {
    const pending = sendMessage({ conversationId: convId, text: 'one' }, deps({ stream: ((o: { signal: AbortSignal }) => hang(o.signal)) as never }))
    await vi.waitFor(() => expect(useChat.getState().running[convId]).toBeDefined())
    const stream2 = vi.fn(() => from([]))
    await sendMessage({ conversationId: convId, text: 'two' }, deps({ stream: stream2 as never }))
    expect(stream2).not.toHaveBeenCalled()
    stopConversation(convId, deps())
    await pending
  })

  it('titles a new conversation from the first message', async () => {
    await sendMessage({ conversationId: convId, text: 'Find precedents on delay in lodging an FIR' }, deps({ stream: (() => from(ev(ask))) as never }))
    await vi.waitFor(() => expect(useChat.getState().conversations.find((c) => c.id === convId)?.title).toBe('Find precedents on delay in lodging an FIR'))
  })
})

describe('historyFor', () => {
  it('sends text only, drops empty turns, and keeps the last twelve', () => {
    const mk = (role: 'user' | 'assistant', text: string) => ({ id: text, role, createdAt: 0, status: 'complete', notices: [], suggestions: [], lastSeq: 0, parts: text ? [{ kind: 'text', id: 'a', text }] : [] }) as unknown as Message
    const list = Array.from({ length: 20 }, (_, i) => mk(i % 2 ? 'assistant' : 'user', `turn ${i}`))
    list.push(mk('assistant', ''))
    const h = historyFor(list)
    expect(h).toHaveLength(12)
    expect(h[h.length - 1]).toEqual({ role: 'assistant', content: 'turn 19' })
    expect(h.every((m) => m.content.length > 0)).toBe(true)
  })
})
