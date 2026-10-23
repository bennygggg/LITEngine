import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ChatActionsProvider } from './actions'
import { AssistantMessage } from './AssistantMessage'
import type { Message } from './model'
import type { Card } from '@/types/agent'

const sources = {
  type: 'sources', card_id: 'c1', title: 'Sources in the document', subtitle: 'What happened?', method: 'generated', schema_ver: 1,
  excerpts: [{ ref: 'S1', text: 'The appellant struck the deceased.', cosine: 0.4, char_start: 0, char_end: 30 }, { ref: 'S2', text: 'The weapon was recovered.', cosine: 0.3, char_start: 40, char_end: 70 }],
} as unknown as Card

const base: Message = { id: 'm1', role: 'assistant', createdAt: 0, status: 'complete', parts: [], notices: [], suggestions: [], lastSeq: 0 }
const actions = { busy: false, sendInput() {}, sendTool() {}, sendText() {}, openCanvas() {}, retry() {} }
const show = (m: Message) => render(<ChatActionsProvider value={actions}><AssistantMessage msg={m} isLast={false} /></ChatActionsProvider>)
const order = (container: HTMLElement, ...needles: string[]): [number, number] => {
  const at = needles.map((n) => (container.textContent ?? '').indexOf(n))
  return [at[0] ?? -1, at[1] ?? -1]
}

describe('AssistantMessage ordering', () => {
  const answer: Message = {
    ...base,
    parts: [
      { kind: 'step', id: 's1', stepId: 's1', tool: 'ask_case', label: 'Search the document', origin: 'forced', status: 'ok', durationMs: 16 } as never,
      { kind: 'card', id: 'p1', cardId: 'c1', type: 'sources', payload: sources },
      { kind: 'text', id: 't1', text: 'The appellant is said to have struck the deceased [S1].' },
    ],
  }

  it('puts the answer above the passages, which are collapsed behind a Sources row', async () => {
    const { container } = show(answer)
    await screen.findByText(/The appellant is said/)
    const [answerAt, sourcesAt] = order(container, 'The appellant is said', 'Sources')
    expect(answerAt).toBeGreaterThanOrEqual(0)
    expect(answerAt).toBeLessThan(sourcesAt)
    expect(screen.queryByText('The weapon was recovered.')).toBeNull()                       // collapsed by default
    await userEvent.click(screen.getByRole('button', { name: /Sources · 2 passages/ }))
    expect(await screen.findByText('The weapon was recovered.')).toBeInTheDocument()
  })

  it('opens the passages straight away when there is no answer text to lead with', async () => {
    show({ ...answer, parts: answer.parts.filter((p) => p.kind !== 'text') })
    expect(await screen.findByText('The weapon was recovered.')).toBeInTheDocument()
  })

  it('keeps cards first for everything else, because the text interprets them', async () => {
    const profile = { type: 'error', card_id: 'c2', title: 'Card title', message: 'A card body.', retryable: false, schema_ver: 1 } as unknown as Card
    const { container } = show({ ...base, parts: [{ kind: 'card', id: 'p2', cardId: 'c2', type: 'error', payload: profile }, { kind: 'text', id: 't2', text: 'Interpretation follows the card.' }] })
    await screen.findByText(/Interpretation follows/)
    const [cardAt, textAt] = order(container, 'Card title', 'Interpretation follows')
    expect(cardAt).toBeLessThan(textAt)
  })

  it('honours answerFirst for other card types when the user asked for a one-liner', async () => {
    const profile = { type: 'error', card_id: 'c2', title: 'Card title', message: 'A card body.', retryable: false, schema_ver: 1 } as unknown as Card
    const { container } = show({ ...base, answerFirst: true, parts: [{ kind: 'card', id: 'p2', cardId: 'c2', type: 'error', payload: profile }, { kind: 'text', id: 't2', text: 'One line answer.' }] })
    await screen.findByText(/One line answer/)
    const [cardAt, textAt] = order(container, 'Card title', 'One line answer.')
    expect(textAt).toBeLessThan(cardAt)
  })
})
