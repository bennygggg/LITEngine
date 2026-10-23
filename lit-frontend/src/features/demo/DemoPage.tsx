import { ChevronsRight, Menu as MenuIcon, PanelLeftOpen, Play, RotateCcw, SkipForward } from 'lucide-react'
import { useEffect, useLayoutEffect, useMemo, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Badge } from '@/design/ui/Badge'
import { Button } from '@/design/ui/Button'
import { AssistantMessage } from '@/features/chat/AssistantMessage'
import { ChatActionsProvider, type ChatActions } from '@/features/chat/actions'
import { UserMessage } from '@/features/chat/UserMessage'
import { DEMO_MATTER_ID, SAMPLE_MATTERS } from '@/features/matters/samples'
import { cn } from '@/lib/cn'
import { useCases } from '@/lib/store/cases'
import { useChat } from '@/lib/store/chat'
import { useUi } from '@/lib/store/ui'
import { sendMessage } from '@/features/chat/runController'
import { DEMO_CONV } from './constants'
import { recording, useDemoPlayer } from './useDemoPlayer'

export default function DemoPage() {
  const player = useDemoPlayer()
  const ui = useUi()
  const navigate = useNavigate()
  const messages = useChat((s) => s.messages[DEMO_CONV]) ?? []
  const scroller = useRef<HTMLDivElement>(null)
  const pinned = useRef(true)
  useLayoutEffect(() => { const el = scroller.current; if (el && pinned.current) el.scrollTop = el.scrollHeight })
  useEffect(() => { document.title = 'Sample session — LIT'; return () => { document.title = 'LIT — Legal research assistant' } }, [])

  const actions: ChatActions = useMemo(() => ({
    busy: player.phase === 'playing',
    inputPrefill: player.formAnswer,
    sendInput: () => player.answerInput(),
    sendText() {}, sendTool() {}, retry() {},
    openCanvas: (cardId, focus) => ui.openCanvas({ cardId, focus }),
  }), [player, ui])

  const runLive = async () => {
    const sample = SAMPLE_MATTERS.find((m) => m.id === DEMO_MATTER_ID)!
    const rec = await useCases.getState().addSample(sample)
    const conv = await useChat.getState().create(rec.id, sample.title)
    navigate(`/c/${conv.id}`)
    void sendMessage({ conversationId: conv.id, text: '', forcedTool: { name: 'full_review', args: {} } as never })
  }
  const recorded = new Date(recording.meta.recorded_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
  const playing = player.phase === 'playing'

  return (
    <div className="flex h-full min-w-0 flex-1 flex-col">
      <header className="flex h-14 shrink-0 items-center gap-2 px-3">
        <Button variant="ghost" size="icon-sm" className="md:hidden" aria-label="Open menu" onClick={() => ui.setMobileSidebarOpen(true)}><MenuIcon /></Button>
        {ui.sidebarCollapsed && <Button variant="ghost" size="icon-sm" className="hidden md:inline-flex" aria-label="Show sidebar" onClick={() => ui.setSidebarCollapsed(false)}><PanelLeftOpen /></Button>}
        <h1 className="px-1 text-sm font-medium text-ink-muted">Sample session</h1>
        <Badge tone="outline">Recorded</Badge>
      </header>

      <div className="mx-auto mb-2 w-full max-w-column px-4">
      <div className="rounded-xl border border-border bg-surface px-4 py-2.5 text-sm" role="note">
        <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
          <p className="min-w-[16rem] flex-1 text-ink-muted">
            A replay of a real LIT run on a <strong className="font-medium text-ink">fictional matter</strong>, recorded {recorded} with {recording.meta.llm.narration_model ?? 'the research model'}. Nothing here is sent to a server.
          </p>
          <div className="flex items-center gap-1.5">
            <div role="group" aria-label="Playback speed" className="flex rounded-md border border-border bg-sunken p-0.5">
              {([1, 2, 4] as const).map((s) => <button key={s} type="button" aria-pressed={player.speed === s} onClick={() => player.setSpeed(s)} className={cn('tnum rounded px-2 py-0.5 text-xs transition-colors', player.speed === s ? 'bg-surface shadow-raised' : 'text-ink-muted hover:text-ink')}>{s}×</button>)}
            </div>
            <label className="flex cursor-pointer items-center gap-1.5 px-1.5 text-xs text-ink-muted"><input type="checkbox" checked={player.autoplay} onChange={(e) => player.setAutoplay(e.target.checked)} className="accent-ink" />Autoplay</label>
            <Button size="sm" variant="ghost" disabled={!playing} onClick={player.skip}><SkipForward /> Skip</Button>
            <Button size="sm" variant="ghost" onClick={player.restart} aria-label="Restart the session"><RotateCcw /></Button>
          </div>
        </div>
      </div>
      </div>

      <div ref={scroller} onScroll={() => { const el = scroller.current; if (el) pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 96 }} className="min-h-0 flex-1 overflow-y-auto">
        <ChatActionsProvider value={actions}>
          <div className="mx-auto w-full max-w-column space-y-8 px-4 pb-8 pt-4">
            {messages.length === 0 && (
              <div className="py-16 text-center">
                <Play className="mx-auto mb-3 size-6 text-ink-muted" />
                <h2 className="font-display text-3xl font-normal tracking-tight">See LIT work a real appeal</h2>
                <p className="mx-auto mt-3 max-w-md text-ink-muted">A criminal appeal on a fictional matter: read the case, map the argument, estimate the outcome, find precedents, test scenarios, and ask the document — {player.total - 1} steps, about two minutes.</p>
              </div>
            )}
            {messages.map((m, i) => (m.role === 'user' ? <UserMessage key={m.id} msg={m} /> : <AssistantMessage key={m.id} msg={m} isLast={i === messages.length - 1} />))}
          </div>
        </ChatActionsProvider>
      </div>

      <div className="shrink-0 px-4 pb-4">
        <div className="mx-auto flex w-full max-w-column flex-wrap items-center justify-between gap-3 rounded-composer border border-border-strong bg-surface p-2.5 pl-4 shadow-raised">
          {player.phase === 'finished' ? (
            <p className="text-sm text-ink-muted">That’s the walkthrough. Try it on a matter of your own.</p>
          ) : player.phase === 'awaiting_input' ? (
            <p className="text-sm text-ink-muted">Answer the form above (the recorded answer is pre-selected), then press Continue.</p>
          ) : player.upcomingText ? (
            <p className="min-w-0 flex-1 truncate text-sm text-ink-muted"><span className="text-ink-subtle">Next:</span> {player.upcomingText}</p>
          ) : <span />}
          <div className="flex items-center gap-2">
            {player.phase === 'finished' || player.turn === 0 ? null : null}
            {(player.phase === 'idle') && <Button onClick={player.start}>{player.turn === 0 ? 'Start the session' : 'Send'} <ChevronsRight /></Button>}
            <Button variant={player.phase === 'finished' ? 'primary' : 'outline'} onClick={() => void runLive()}>Run this live on the same matter</Button>
          </div>
        </div>
      </div>
    </div>
  )
}
