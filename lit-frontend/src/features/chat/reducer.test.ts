import type { AgentEvent } from '@/types/agent'
import { messageText, newAssistantMessage, reduceAll, reduceEvent, settleInterrupted } from './reducer'
import paused from '@/test/fixtures/full_review_paused.json'
import resumed from '@/test/fixtures/full_review_resumed.json'
import scenario from '@/test/fixtures/scenario.json'
import ask from '@/test/fixtures/ask.json'
import outOfScope from '@/test/fixtures/out_of_scope.json'
import help from '@/test/fixtures/help.json'

const evs = (x: unknown) => x as AgentEvent[]
const cards = (m: ReturnType<typeof reduceAll>) => m.parts.filter((p) => p.kind === 'card')

describe('reduceEvent on real server streams', () => {
  it('a paused review ends awaiting input with the profile card filled and a form part', () => {
    const m = reduceAll(evs(paused))
    expect(m.status).toBe('awaiting_input')
    const cardTypes = cards(m).map((c) => c.kind === 'card' && c.payload?.type)
    expect(cardTypes).toEqual(['case_profile'])
    expect(m.parts.some((p) => p.kind === 'input')).toBe(true)
    expect(m.parts.some((p) => p.kind === 'card' && p.payload === null)).toBe(false) // no skeleton left behind
  })

  it('the resumed run shows precedents, map and outcome in order, with dependency steps but no extra cards', () => {
    const m = reduceAll(evs(resumed))
    expect(m.status).toBe('complete')
    expect(cards(m).map((c) => c.kind === 'card' && c.payload?.type)).toEqual(['precedents', 'argument_map', 'outcome'])
    const steps = m.parts.filter((p) => p.kind === 'step')
    expect(steps.length).toBeGreaterThanOrEqual(4)
    expect(steps.every((s) => s.kind === 'step' && s.status !== 'running')).toBe(true)
    expect(m.caseInputs?.appellant_type).toBe('accused_appeal')
    expect(m.suggestions.length).toBeGreaterThan(0)
    expect(m.usage?.llm_calls).toBe(0)
  })

  it('a card replaces its skeleton in place (same position, no duplicate)', () => {
    const all = evs(resumed)
    const mid = all.findIndex((e) => e.event === 'card')
    const before = reduceAll(all.slice(0, mid))
    expect(before.parts.some((p) => p.kind === 'card' && p.payload === null)).toBe(true) // the announced skeleton is visible
    const skeletonIndex = before.parts.findIndex((p) => p.kind === 'card')
    const after = reduceAll(all.slice(0, mid + 1))
    expect(after.parts.findIndex((p) => p.kind === 'card')).toBe(skeletonIndex)
    expect(cards(after)).toHaveLength(1)
  })

  it('scenario, ask and out-of-scope streams settle cleanly', () => {
    expect(cards(reduceAll(evs(scenario))).map((c) => c.kind === 'card' && c.payload?.type)).toContain('scenario')
    expect(cards(reduceAll(evs(ask))).map((c) => c.kind === 'card' && c.payload?.type)).toEqual(['sources'])
    const oos = reduceAll(evs(outOfScope))
    expect(cards(oos).some((c) => c.kind === 'card' && c.payload?.type === 'error')).toBe(true)
    expect(oos.notices.some((n) => n.code === 'outcome_out_of_scope')).toBe(true)
  })

  it('text-only help has text and no cards', () => {
    const m = reduceAll(evs(help))
    expect(cards(m)).toHaveLength(0)
    expect(messageText(m)).toContain('Attach a matter')
  })
})

describe('reducer invariants', () => {
  it('is idempotent: replaying events already applied changes nothing', () => {
    const all = evs(resumed)
    const once = reduceAll(all)
    const twice = all.reduce(reduceEvent, once)
    expect(twice).toEqual(once)
  })

  it('applying a stream in two halves equals applying it at once (resume correctness)', () => {
    const all = evs(resumed)
    const half = Math.floor(all.length / 2)
    const first = reduceAll(all.slice(0, half))
    expect(all.slice(half).reduce(reduceEvent, first)).toEqual(reduceAll(all))
  })

  it('ignores events it does not know about', () => {
    const m = newAssistantMessage('m')
    const out = reduceEvent(m, { event: 'future_thing', v: 9, seq: 1, t: 0 } as unknown as AgentEvent)
    expect(out.parts).toEqual([])
  })

  it('a step that never ends is closed by done, and unfilled skeletons are removed', () => {
    const all = evs(resumed)
    const startOnly = all.filter((e) => !(e.event === 'step' && e.phase === 'end') && e.event !== 'card')
    const m = reduceAll(startOnly)
    expect(m.parts.some((p) => p.kind === 'step' && p.status === 'running')).toBe(false)
    expect(m.parts.some((p) => p.kind === 'card' && p.payload === null)).toBe(false)
  })

  it('text deltas for one part concatenate; a new part id starts a new paragraph', () => {
    let m = newAssistantMessage('m')
    for (const [i, [part, delta]] of ([['a', 'Hello '], ['a', 'world'], ['b', 'Second']] as const).entries()) {
      m = reduceEvent(m, { event: 'text_delta', v: 1, seq: i + 1, t: 0, message_id: 'm', part_id: part, delta } as AgentEvent)
    }
    expect(m.parts).toEqual([{ kind: 'text', id: 'a', text: 'Hello world' }, { kind: 'text', id: 'b', text: 'Second' }])
    expect(messageText(m)).toBe('Hello world\n\nSecond')
  })

  it('a superseding card replaces the earlier one (e.g. sources relabelled extractive)', () => {
    const base = reduceAll(evs(ask).filter((e) => e.event !== 'done'))
    const original = base.parts.find((p) => p.kind === 'card')
    if (original?.kind !== 'card' || !original.payload) throw new Error('fixture lacks a card')
    const fixed = { ...original.payload, card_id: 'new', method: 'extractive' }
    const m = reduceEvent(base, { event: 'card', v: 1, seq: 999, t: 0, card_id: 'new', part_id: 'px', supersedes: original.cardId, payload: fixed } as AgentEvent)
    expect(cards(m)).toHaveLength(1)
    expect(m.parts.find((p) => p.kind === 'card')).toMatchObject({ cardId: 'new' })
  })

  it('settleInterrupted turns a dangling stream into a finished, honest message', () => {
    const all = evs(resumed)
    const dangling = reduceAll(all.slice(0, 6))
    expect(dangling.status).toBe('streaming')
    const settled = settleInterrupted(dangling)
    expect(settled.status).toBe('interrupted')
    expect(settled.parts.some((p) => p.kind === 'step' && p.status === 'running')).toBe(false)
  })
})

describe('answer_first', () => {
  it('is carried from message_start so the view can lead with the text', () => {
    const start = { v: 1, seq: 1, t: 0, event: 'message_start', run_id: 'r', message_id: 'm', conversation_id: 'c', mode: 'llm', server_version: '1.0.1', schema_version: 1, case_known: true, answer_first: true } as never
    expect(reduceEvent(newAssistantMessage('m'), start).answerFirst).toBe(true)
    expect(reduceEvent(newAssistantMessage('m'), { ...(start as object), answer_first: undefined } as never).answerFirst).toBe(false)
  })
})
