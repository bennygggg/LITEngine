import type { AgentEvent } from '@/types/agent'
import { reduceAll, reduceEvent, newAssistantMessage } from '@/features/chat/reducer'
import { buildSchedule, dueEvents, totalMs } from './replay'
import recording from './recordings/lit-demo-v1.json'

const turns = (recording as unknown as { turns: Array<{ events: AgentEvent[] }> }).turns

describe('recorded sample session', () => {
  it('has the shape the demo relies on', () => {
    expect(turns).toHaveLength(9)
    const cards = turns.flatMap((t) => t.events.filter((e) => e.event === 'card').map((e) => (e as { payload: { type: string } }).payload.type))
    for (const needed of ['case_profile', 'argument_map', 'outcome', 'precedents', 'scenario', 'sources']) expect(cards).toContain(needed)
    expect(turns.flatMap((t) => t.events).filter((e) => e.event === 'needs_input')).toHaveLength(1)
  })

  it('every recorded turn reduces to a settled message with no skeletons or running steps', () => {
    for (const t of turns) {
      const m = reduceAll(t.events)
      expect(['complete', 'awaiting_input']).toContain(m.status)
      expect(m.parts.some((p) => p.kind === 'card' && p.payload === null)).toBe(false)
      expect(m.parts.some((p) => p.kind === 'step' && p.status === 'running')).toBe(false)
    }
  })
})

describe('buildSchedule', () => {
  const t0 = turns[0]!.events
  it('preserves order and never goes backwards', () => {
    const s = buildSchedule(t0)
    expect(s.map((x) => x.event)).toEqual(t0)
    for (let i = 1; i < s.length; i++) expect(s[i]!.at).toBeGreaterThanOrEqual(s[i - 1]!.at)
  })

  it('squeezes recorded latency: no single gap exceeds the cap and a turn plays in seconds, not minutes', () => {
    for (const t of turns) {
      const s = buildSchedule(t.events, { gapCapMs: 650 })
      for (let i = 1; i < s.length; i++) expect(s[i]!.at - s[i - 1]!.at).toBeLessThanOrEqual(650)
      expect(totalMs(s)).toBeLessThan(20_000)
    }
  })

  it('replaying on the clock produces exactly the message a live stream would', () => {
    for (const t of turns) {
      const s = buildSchedule(t.events)
      let msg = newAssistantMessage('m', 0)
      let cursor = 0
      for (let ms = 0; cursor < s.length; ms += 40) {
        const due = dueEvents(s, cursor, ms, 1)
        cursor = due.cursor
        msg = due.events.reduce(reduceEvent, msg)
      }
      expect(msg).toEqual(reduceAll(t.events))
    }
  })

  it('a higher speed reaches the end sooner; skipping is just "everything is due"', () => {
    const s = buildSchedule(t0)
    const end = totalMs(s)
    expect(dueEvents(s, 0, end / 4, 4).cursor).toBe(s.length)
    expect(dueEvents(s, 0, end / 4, 1).cursor).toBeLessThan(s.length)
    expect(dueEvents(s, 3, 1, 1e9).cursor).toBe(s.length) // skip = everything is due
  })
})
