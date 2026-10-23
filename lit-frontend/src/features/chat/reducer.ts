import { TOOL_CARD } from '@/types/agent'
import type { AgentEvent, StepEvent } from '@/types/agent'
import type { CardPart, Message, Part, StepPart } from './model'

/** A new, empty assistant message ready to receive events. */
export function newAssistantMessage(id: string, createdAt = Date.now()): Message {
  return { id, role: 'assistant', createdAt, parts: [], status: 'streaming', notices: [], suggestions: [], lastSeq: 0 }
}

const replace = (parts: Part[], index: number, part: Part): Part[] => [...parts.slice(0, index), part, ...parts.slice(index + 1)]

function applyStep(msg: Message, ev: StepEvent): Message {
  const idx = msg.parts.findIndex((p) => p.kind === 'step' && p.stepId === ev.step_id)
  if (ev.phase === 'start') {
    if (idx >= 0) return msg
    const step: StepPart = {
      kind: 'step', id: `step:${ev.step_id}`, stepId: ev.step_id, tool: ev.tool, label: ev.label,
      origin: ev.origin ?? 'forced', status: 'running', startedAt: ev.t,
    }
    const parts: Part[] = [...msg.parts, step]
    const cardType = TOOL_CARD[ev.tool]
    if (ev.produces_card && cardType) {
      parts.push({ kind: 'card', id: `skeleton:${ev.step_id}`, cardId: `skeleton:${ev.step_id}`, stepId: ev.step_id, type: cardType, payload: null })
    }
    return { ...msg, parts }
  }
  if (idx < 0) return msg
  const current = msg.parts[idx] as StepPart
  if (ev.phase === 'progress') return { ...msg, parts: replace(msg.parts, idx, { ...current, progress: ev.message ?? current.progress }) }
  return {
    ...msg,
    parts: replace(msg.parts, idx, { ...current, status: ev.status ?? 'ok', durationMs: ev.duration_ms ?? undefined, summary: ev.summary ?? undefined }),
  }
}

/**
 * Apply one server event to a message. Pure and total: unknown events are ignored (forward compatibility), and an
 * event whose seq has already been applied is a no-op, so a replay after a dropped connection can never duplicate content.
 * The live stream and the recorded sample both run through this exact function.
 */
export function reduceEvent(msg: Message, ev: AgentEvent): Message {
  if (typeof ev.seq === 'number' && ev.seq <= msg.lastSeq && ev.event !== 'ping') return msg
  const next = typeof ev.seq === 'number' ? { ...msg, lastSeq: Math.max(msg.lastSeq, ev.seq) } : msg

  switch (ev.event) {
    case 'message_start':
      return { ...next, runId: ev.run_id, mode: ev.mode, model: ev.model ?? null }

    case 'text_delta': {
      const idx = next.parts.findIndex((p) => p.kind === 'text' && p.id === ev.part_id)
      if (idx >= 0) {
        const part = next.parts[idx]
        if (part?.kind !== 'text') return next
        return { ...next, parts: replace(next.parts, idx, { ...part, text: part.text + ev.delta }) }
      }
      return { ...next, parts: [...next.parts, { kind: 'text', id: ev.part_id, text: ev.delta }] }
    }

    case 'step':
      return applyStep(next, ev)

    case 'card': {
      const payload = ev.payload
      if (ev.supersedes) {
        const idx = next.parts.findIndex((p) => p.kind === 'card' && p.cardId === ev.supersedes)
        if (idx >= 0) {
          const old = next.parts[idx] as CardPart
          return { ...next, parts: replace(next.parts, idx, { ...old, cardId: payload.card_id, payload, type: payload.type }) }
        }
      }
      const skeleton = next.parts.findIndex((p) => p.kind === 'card' && p.payload === null && p.stepId && p.stepId === ev.step_id)
      if (skeleton >= 0) {
        const old = next.parts[skeleton] as CardPart
        return { ...next, parts: replace(next.parts, skeleton, { ...old, cardId: payload.card_id, payload, type: payload.type }) }
      }
      return { ...next, parts: [...next.parts, { kind: 'card', id: ev.part_id, cardId: payload.card_id, stepId: ev.step_id ?? undefined, type: payload.type, payload }] }
    }

    case 'needs_input':
      return { ...next, parts: [...next.parts, { kind: 'input', id: ev.part_id, cardId: ev.card_id, payload: ev.payload }] }

    case 'meta':
      return {
        ...next,
        suggestions: ev.suggestions ?? next.suggestions,
        caseInputs: ev.case_inputs ?? next.caseInputs,
      }

    case 'error': {
      const notices = [...next.notices, { code: ev.code, message: ev.message, scope: ev.scope ?? 'run', retryable: Boolean(ev.retryable) }]
      if (ev.scope === 'step' && ev.step_id) {
        const idx = next.parts.findIndex((p) => p.kind === 'step' && p.stepId === ev.step_id)
        if (idx >= 0) return { ...next, notices, parts: replace(next.parts, idx, { ...(next.parts[idx] as StepPart), status: 'error' }) }
      }
      return { ...next, notices }
    }

    case 'done': {
      // Anything still "running" never got its end event (cancelled/crashed): don't leave spinners or skeletons behind.
      const parts = next.parts
        .filter((p) => !(p.kind === 'card' && p.payload === null))
        .map((p): Part => (p.kind === 'step' && p.status === 'running' ? { ...p, status: ev.status === 'complete' ? 'ok' : 'error' } : p))
      const hasRunError = next.notices.some((n) => n.scope === 'run')
      return {
        ...next, parts, status: ev.status === 'complete' && hasRunError ? 'error' : ev.status,
        usage: ev.usage, timings: ev.timings, warnings: ev.warnings ?? [],
      }
    }

    default:
      return next // ping, artifact_update, and anything from a newer server
  }
}

/** Fold a whole recorded stream into a finished message (tests, the demo's skip-to-end, and reload of persisted runs). */
export function reduceAll(events: AgentEvent[], id = 'm', createdAt = 0): Message {
  return events.reduce(reduceEvent, newAssistantMessage(id, createdAt))
}

/** Plain text of a message — what goes back to the server as conversation history. */
export function messageText(msg: Message): string {
  return msg.parts.filter((p) => p.kind === 'text').map((p) => (p.kind === 'text' ? p.text : '')).join('\n\n').trim()
}

/** After a reload, a message that was mid-stream can never complete: say so instead of spinning forever. */
export function settleInterrupted(msg: Message): Message {
  if (msg.status !== 'streaming') return msg
  const parts = msg.parts
    .filter((p) => !(p.kind === 'card' && p.payload === null))
    .map((p): Part => (p.kind === 'step' && p.status === 'running' ? { ...p, status: 'error' } : p))
  return { ...msg, status: 'interrupted', parts }
}
