import type { AgentEvent } from '@/types/agent'

export interface Scheduled {
  /** Milliseconds from the start of the turn at 1× speed. */
  at: number
  event: AgentEvent
}

export interface PacingOptions {
  /** Longest pause kept between two ordinary events (the recording's real LLM/network latency is squeezed to this). */
  gapCapMs?: number
  /** Pause between streamed text chunks — small, so the text flows. */
  textGapMs?: number
  /** A step needs to be visible for a moment before its card replaces the spinner. */
  stepMinMs?: number
}

/**
 * Turn a recorded event stream into a paced schedule. Event ORDER is untouched; only the gaps change, so the replay can
 * never show something the live stream would not have.
 */
export function buildSchedule(events: AgentEvent[], opts: PacingOptions = {}): Scheduled[] {
  const { gapCapMs = 650, textGapMs = 22, stepMinMs = 320 } = opts
  const out: Scheduled[] = []
  let clock = 0
  let prev: AgentEvent | null = null
  for (const ev of events) {
    if (prev) {
      const recorded = Math.max(0, (ev.t ?? 0) - (prev.t ?? 0))
      let gap: number
      if (ev.event === 'text_delta' && prev.event === 'text_delta') gap = Math.min(recorded, textGapMs)
      else if (ev.event === 'text_delta') gap = Math.min(Math.max(recorded, 180), gapCapMs) // a beat before the narration starts
      else if (ev.event === 'step' && ev.phase === 'end') gap = Math.max(Math.min(recorded, gapCapMs), stepMinMs)
      else gap = Math.min(recorded, gapCapMs)
      clock += gap
    }
    out.push({ at: clock, event: ev })
    prev = ev
  }
  return out
}

export const totalMs = (schedule: Scheduled[]) => (schedule.length ? schedule[schedule.length - 1]!.at : 0)

/** Events that are due by `elapsedMs` (scaled by speed), starting after `cursor`. */
export function dueEvents(schedule: Scheduled[], cursor: number, elapsedMs: number, speed: number): { events: AgentEvent[]; cursor: number } {
  const limit = elapsedMs * speed
  const events: AgentEvent[] = []
  let i = cursor
  while (i < schedule.length && schedule[i]!.at <= limit) events.push(schedule[i++]!.event)
  return { events, cursor: i }
}
