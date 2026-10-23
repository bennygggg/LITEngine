import type { AgentEvent, Card, CardType, CaseInputs, DoneEvent, ForcedTool, NeedsInputCard, Suggestion, ToolName } from '@/types/agent'

export type StepStatus = 'running' | 'ok' | 'cached' | 'skipped' | 'error'

export interface TextPart {
  kind: 'text'
  id: string
  text: string
}

export interface StepPart {
  kind: 'step'
  id: string
  stepId: string
  tool: ToolName
  label: string
  origin: 'llm' | 'forced' | 'dependency'
  status: StepStatus
  /** Server-side elapsed ms when the step began (for ordering/duration); durationMs arrives with the end event. */
  startedAt: number
  durationMs?: number
  summary?: string
  progress?: string
}

/** A card slot. `payload === null` is a skeleton: the step announced a card that has not arrived yet. */
export interface CardPart {
  kind: 'card'
  id: string
  cardId: string
  stepId?: string
  type: CardType
  payload: Card | null
}

export interface InputPart {
  kind: 'input'
  id: string
  cardId: string
  payload: NeedsInputCard
  /** Set once the user has answered (the form then renders read-only). */
  answered?: Record<string, string>
}

export interface AttachmentPart {
  kind: 'attachment'
  id: string
  caseId: string
  title: string
  wordCount: number
  source: 'sample' | 'upload' | 'paste'
}

export type Part = TextPart | StepPart | CardPart | InputPart | AttachmentPart

export interface Notice {
  code: string
  message: string
  scope: 'run' | 'step' | 'llm'
  retryable: boolean
}

export type MessageStatus = 'streaming' | 'complete' | 'awaiting_input' | 'cancelled' | 'error' | 'interrupted'

/** What a user message asked for — kept so "regenerate" can replay it exactly. */
export interface UserRequest {
  text: string
  forcedTool?: ForcedTool | null
  inputResponse?: { card_id: string; values: Record<string, string>; pending?: ForcedTool | null } | null
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  createdAt: number
  parts: Part[]
  request?: UserRequest
  status: MessageStatus
  runId?: string
  mode?: 'llm' | 'forced' | 'deterministic'
  model?: string | null
  /** The user asked for a short answer: the text comes before any cards. */
  answerFirst?: boolean
  usage?: DoneEvent['usage']
  timings?: DoneEvent['timings']
  warnings?: string[]
  notices: Notice[]
  suggestions: Suggestion[]
  /** Inputs the server resolved this run (form answer or explicit user statement); the controller persists them on the matter. */
  caseInputs?: CaseInputs | null
  /** Highest event seq applied — makes replay idempotent and gives the resume cursor. */
  lastSeq: number
  /** True when this message is a recorded sample being replayed. */
  recorded?: boolean
}

export type { AgentEvent }
