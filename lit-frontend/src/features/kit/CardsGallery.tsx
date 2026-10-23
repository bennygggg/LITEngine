import { useMemo } from 'react'
import { AssistantMessage } from '@/features/chat/AssistantMessage'
import { reduceAll } from '@/features/chat/reducer'
import { ChatActionsProvider } from '@/features/chat/actions'
import type { AgentEvent } from '@/types/agent'
import paused from '@/test/fixtures/full_review_paused.json'
import resumed from '@/test/fixtures/full_review_resumed.json'
import scenario from '@/test/fixtures/scenario.json'
import ask from '@/test/fixtures/ask.json'
import outOfScope from '@/test/fixtures/out_of_scope.json'

const streams: Array<[string, unknown]> = [
  ['Review paused for input', paused],
  ['Review resumed: precedents, map, outcome', resumed],
  ['Scenarios', scenario],
  ['Ask the document', ask],
  ['Outcome declined (civil matter)', outOfScope],
]

/** Dev-only: every card, rendered from real server streams through the real components. */
export default function CardsGallery() {
  const msgs = useMemo(() => streams.map(([name, ev]) => [name, reduceAll(ev as AgentEvent[], name)] as const), [])
  return (
    <ChatActionsProvider value={{ busy: false, sendInput() {}, sendTool() {}, sendText() {}, openCanvas() {}, retry() {} }}>
      <div className="mx-auto max-w-column space-y-12 px-4 py-10">
        {msgs.map(([name, m]) => (
          <section key={name}>
            <h2 className="mb-4 border-b border-border pb-2 text-2xs font-medium uppercase tracking-[0.1em] text-ink-subtle">{name}</h2>
            <AssistantMessage msg={m} isLast />
          </section>
        ))}
      </div>
    </ChatActionsProvider>
  )
}
