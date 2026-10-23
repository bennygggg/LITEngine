import { useCallback, useEffect, useRef, useState } from 'react'
import type { Message } from '@/features/chat/model'
import { newAssistantMessage, reduceEvent } from '@/features/chat/reducer'
import { SAMPLE_MATTERS, DEMO_MATTER_ID } from '@/features/matters/samples'
import { useChat } from '@/lib/store/chat'
import type { AgentEvent } from '@/types/agent'
import { DEMO_CONV } from './constants'
import recordingJson from './recordings/lit-demo-v1.json'
import { buildSchedule, dueEvents, type Scheduled } from './replay'

interface Turn {
  user: { text: string; request: { text: string; forced_tool?: unknown; input_response?: { card_id: string; values: Record<string, string> } | null }; attach: boolean }
  events: AgentEvent[]
}
export interface Recording {
  meta: { recorded_at: string; server_version: string; llm: { narration_model?: string | null }; matter_id: string }
  turns: Turn[]
}
export const recording = recordingJson as unknown as Recording
export type Phase = 'idle' | 'playing' | 'awaiting_input' | 'finished'
export type Speed = 1 | 2 | 4

const TICK_MS = 30

/**
 * Plays the recorded session through the SAME reducer and components as a live run. The player owns only timing and which
 * turn is next; what appears on screen is whatever the recorded events reduce to.
 */
export function useDemoPlayer() {
  const [turn, setTurn] = useState(0)            // the next turn to start
  const [phase, setPhase] = useState<Phase>('idle')
  const [speed, setSpeed] = useState<Speed>(1)
  const [autoplay, setAutoplay] = useState(false)
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)
  const next = useRef<ReturnType<typeof setTimeout> | null>(null)
  const live = useRef<{ msg: Message; schedule: Scheduled[]; cursor: number; elapsed: number } | null>(null)
  const speedRef = useRef(speed)
  speedRef.current = speed
  const autoRef = useRef(autoplay)
  autoRef.current = autoplay

  const stopTimers = () => {
    if (timer.current) clearInterval(timer.current)
    if (next.current) clearTimeout(next.current)
    timer.current = next.current = null
  }

  const finishTurn = useCallback((index: number, status: Message['status']) => {
    stopTimers()
    live.current = null
    const last = index >= recording.turns.length - 1
    const awaiting = status === 'awaiting_input'
    setTurn(index + 1)
    setPhase(awaiting ? 'awaiting_input' : last ? 'finished' : 'idle')
  }, [])

  const apply = useCallback((index: number, events: AgentEvent[]) => {
    const run = live.current
    if (!run) return
    run.msg = events.reduce(reduceEvent, run.msg)
    useChat.getState().upsertMessage(DEMO_CONV, run.msg)
  }, [])

  const startTurn = useCallback((index: number) => {
    const t = recording.turns[index]
    if (!t || live.current) return
    stopTimers()
    const matter = SAMPLE_MATTERS.find((m) => m.id === DEMO_MATTER_ID)!
    const chat = useChat.getState()
    chat.upsertMessage(DEMO_CONV, {
      id: `demo-u${index}`, role: 'user', createdAt: Date.now(), status: 'complete', notices: [], suggestions: [], lastSeq: 0,
      parts: [
        ...(t.user.attach ? [{ kind: 'attachment' as const, id: 'a', caseId: matter.id, title: matter.title, wordCount: matter.text.split(/\s+/).length, source: 'sample' as const }] : []),
        { kind: 'text', id: 'u', text: t.user.text },
      ],
    })
    const msg: Message = { ...newAssistantMessage(`demo-a${index}`), recorded: true }
    live.current = { msg, schedule: buildSchedule(t.events), cursor: 0, elapsed: 0 }
    chat.upsertMessage(DEMO_CONV, msg)
    setPhase('playing')
    timer.current = setInterval(() => {
      const run = live.current
      if (!run) return
      run.elapsed += TICK_MS
      const due = dueEvents(run.schedule, run.cursor, run.elapsed, speedRef.current)
      run.cursor = due.cursor
      if (due.events.length) apply(index, due.events)
      if (run.cursor >= run.schedule.length) {
        const status = run.msg.status
        finishTurn(index, status)
        if (autoRef.current && status !== 'awaiting_input' && index < recording.turns.length - 1) next.current = setTimeout(() => startTurn(index + 1), 1400 / speedRef.current)
        if (autoRef.current && status === 'awaiting_input') next.current = setTimeout(() => answerInput(index + 1), 1700 / speedRef.current)
      }
    }, TICK_MS)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apply, finishTurn])

  /** The user pressed Continue on the (pre-filled) form: the next recorded turn is its answer. */
  const answerInput = useCallback((index: number) => {
    const t = recording.turns[index]
    const ir = t?.user.request.input_response
    if (!t || !ir) return
    useChat.getState().markInputAnswered(DEMO_CONV, ir.card_id, ir.values)
    startTurn(index)
  }, [startTurn])

  const skip = useCallback(() => {
    const run = live.current
    if (!run) return
    const index = turn
    const rest = run.schedule.slice(run.cursor).map((s) => s.event)
    run.cursor = run.schedule.length
    apply(index, rest)
    finishTurn(index, run.msg.status)
  }, [apply, finishTurn, turn])

  const restart = useCallback(() => {
    stopTimers()
    live.current = null
    useChat.setState({ messages: { ...useChat.getState().messages, [DEMO_CONV]: [] } })
    setTurn(0)
    setPhase('idle')
  }, [])

  useEffect(() => { useChat.setState({ messages: { ...useChat.getState().messages, [DEMO_CONV]: [] } }); return () => { stopTimers(); live.current = null; const { [DEMO_CONV]: _gone, ...rest } = useChat.getState().messages; useChat.setState({ messages: rest }) } }, [])

  const upcoming = recording.turns[turn]
  const formAnswer = recording.turns.find((t) => t.user.request.input_response)?.user.request.input_response?.values
  return {
    turn, phase, speed, setSpeed, autoplay, setAutoplay, skip, restart,
    start: () => startTurn(turn),
    answerInput: () => answerInput(turn),
    upcomingText: upcoming && !upcoming.user.request.input_response ? upcoming.user.text : null,
    formAnswer,
    total: recording.turns.length,
  }
}
