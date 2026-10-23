import { ArrowDown, Menu as MenuIcon, PanelLeftOpen } from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Button } from '@/design/ui/Button'
import type { CaseRecord } from '@/lib/persistence/storage'
import { DEMO_MATTER_ID } from '@/features/matters/ids'
import { useCases } from '@/lib/store/cases'
import { useChat } from '@/lib/store/chat'
import { useEngine } from '@/lib/store/engine'
import { useUi } from '@/lib/store/ui'
import type { ForcedTool, ToolName } from '@/types/agent'
import { type ChatActions, ChatActionsProvider } from './actions'
import { AssistantMessage } from './AssistantMessage'
import { Composer } from './Composer'
import { EmptyState } from './EmptyState'
import { retryMessage, sendMessage, stopConversation } from './runController'
import { UserMessage } from './UserMessage'

const SAMPLE_START = DEMO_MATTER_ID

export default function ChatPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const chat = useChat()
  const cases = useCases((s) => s.cases)
  const ui = useUi()
  const engine = useEngine((s) => s.state)
  const [draftCaseId, setDraftCaseId] = useState<string | null>(null)
  const [presetTool, setPresetTool] = useState<ToolName | null>(null)

  const conv = chat.conversations.find((c) => c.id === id)
  const messages = (id && chat.messages[id]) || []
  const busy = Boolean(id && chat.running[id])
  const matter = cases.find((c) => c.id === (conv ? conv.caseId : draftCaseId)) ?? null

  useEffect(() => { void chat.select(id ?? null) }, [id]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (id && chat.loaded && !conv) navigate('/', { replace: true }) }, [id, chat.loaded, conv, navigate])

  // --- scrolling: stick to the bottom while streaming unless the reader has scrolled up -----------------------
  const scroller = useRef<HTMLDivElement>(null)
  const [pinned, setPinned] = useState(true)
  const lastLen = messages.length ? JSON.stringify(messages[messages.length - 1]!.parts.length) + (messages[messages.length - 1]!.status) : ''
  useLayoutEffect(() => {
    const el = scroller.current
    if (el && pinned) el.scrollTop = el.scrollHeight
  })
  const onScroll = () => {
    const el = scroller.current
    if (el) setPinned(el.scrollHeight - el.scrollTop - el.clientHeight < 96)
  }
  useEffect(() => { setPinned(true) }, [id])

  const ensureConversation = useCallback(async (caseId: string | null): Promise<string> => {
    if (id && conv) return id
    const c = await useChat.getState().create(caseId)
    navigate(`/c/${c.id}`, { replace: true })
    return c.id
  }, [id, conv, navigate])

  const submit = useCallback(async (text: string, tool: ToolName | null) => {
    const convId = await ensureConversation(matter?.id ?? null)
    let forced: ForcedTool | null = null
    if (tool) {
      const args: Record<string, unknown> = {}
      if (tool === 'search_precedents' && text) args.query = text
      if (tool === 'ask_case') args.question = text
      if (tool === 'run_scenario' && text) args.text = text
      forced = { name: tool, args } as ForcedTool // generated type for the open-ended args object is `Record<string, never>`
    }
    setPinned(true)
    const textInArgs = tool === 'search_precedents' || tool === 'ask_case' || tool === 'run_scenario' // the typed text became tool arguments
    await sendMessage({ conversationId: convId, text: textInArgs ? '' : text, forcedTool: forced })
  }, [ensureConversation, matter?.id])

  const attach = useCallback(async (rec: CaseRecord) => {
    if (conv && conv.caseId === null) await useChat.getState().setCase(conv.id, rec.id)
    else if (conv && conv.caseId !== rec.id) {
      const c = await useChat.getState().create(rec.id, rec.title)
      navigate(`/c/${c.id}`)
    } else setDraftCaseId(rec.id)
  }, [conv, navigate])

  const reviewSample = useCallback(async () => {
    const { SAMPLE_MATTERS } = await import('@/features/matters/samples') // the sample texts load only when one is started
    const sample = SAMPLE_MATTERS.find((s) => s.id === SAMPLE_START)!
    const rec = await useCases.getState().addSample(sample)
    const c = await useChat.getState().create(rec.id, sample.title)
    navigate(`/c/${c.id}`)
    await sendMessage({ conversationId: c.id, text: '', forcedTool: { name: 'full_review', args: {} } })
  }, [navigate])

  const actions: ChatActions = useMemo(() => ({
    busy,
    sendText: (text) => { if (id) void sendMessage({ conversationId: id, text }) },
    sendTool: (tool) => { if (id) void sendMessage({ conversationId: id, text: '', forcedTool: tool }) },
    sendInput: (cardId, values, pending) => {
      if (!id) return
      if (conv?.caseId) void useCases.getState().updateInputs(conv.caseId, { ...(values.appellant_type ? { appellant_type: values.appellant_type as 'accused_appeal' } : {}), ...(values.filing_date ? { filing_date: values.filing_date } : {}) })
      void sendMessage({ conversationId: id, text: '', inputResponse: { card_id: cardId, values, pending: pending ?? null } })
    },
    openCanvas: (cardId, focus) => ui.openCanvas({ cardId, focus }),
    retry: (assistantId) => { if (id) void retryMessage(id, assistantId) },
  }), [busy, id, conv?.caseId, ui])

  const composer = (large: boolean) => (
    <Composer
      key={id ?? 'new'} large={large} autoFocus matter={matter} busy={busy} presetTool={presetTool} onPresetConsumed={() => setPresetTool(null)}
      onSubmit={(t, tool) => void submit(t, tool)} onStop={() => id && stopConversation(id)}
      onAddCase={() => ui.openMatterDialog('upload')} onChooseCase={() => ui.openMatterDialog('matters')}
      onClearMatter={() => (conv ? void useChat.getState().setCase(conv.id, null) : setDraftCaseId(null))}
    />
  )

  const empty = !conv || messages.length === 0
  // Dialog selection is wired once at the shell; it publishes the chosen matter through this event.
  useEffect(() => {
    const h = (e: Event) => void attach((e as CustomEvent<CaseRecord>).detail)
    window.addEventListener('lit:matter-selected', h)
    return () => window.removeEventListener('lit:matter-selected', h)
  }, [attach])

  return (
    <div className="flex h-full min-w-0 flex-1 flex-col">
      <header className="flex h-14 shrink-0 items-center gap-2 px-3">
        <Button variant="ghost" size="icon-sm" className="md:hidden" aria-label="Open menu" onClick={() => ui.setMobileSidebarOpen(true)}><MenuIcon /></Button>
        {ui.sidebarCollapsed && <Button variant="ghost" size="icon-sm" className="hidden md:inline-flex" aria-label="Show sidebar" onClick={() => ui.setSidebarCollapsed(false)}><PanelLeftOpen /></Button>}
        <h1 className="min-w-0 truncate px-1 text-sm font-medium text-ink-muted">{conv?.title && conv.title !== 'New conversation' ? conv.title : ''}</h1>
      </header>

      {empty ? (
        <div className="flex min-h-0 flex-1 overflow-y-auto">
          <EmptyState composer={composer(true)} onReviewSample={() => void reviewSample()} onUpload={() => ui.openMatterDialog('upload')} onFindPrecedents={() => setPresetTool('search_precedents')} />
        </div>
      ) : (
        <>
          <div ref={scroller} onScroll={onScroll} className="relative min-h-0 flex-1 overflow-y-auto" data-testid="message-scroller">
            <ChatActionsProvider value={actions}>
              <div className="mx-auto w-full max-w-column space-y-8 px-4 pb-8 pt-4" data-last={lastLen}>
                {messages.map((m, i) => (m.role === 'user' ? <UserMessage key={m.id} msg={m} /> : <AssistantMessage key={m.id} msg={m} isLast={i === messages.length - 1} />))}
              </div>
            </ChatActionsProvider>
          </div>
          <div className="relative shrink-0 px-4 pb-3">
            {!pinned && (
              <Button variant="outline" size="sm" className="absolute -top-11 left-1/2 -translate-x-1/2 rounded-full bg-surface shadow-float" onClick={() => { const el = scroller.current; if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' }) }}>
                <ArrowDown /> Jump to latest
              </Button>
            )}
            <div className="mx-auto w-full max-w-column">
              {engine === 'waking' && <p role="status" className="mb-2 flex items-center gap-2 rounded-lg border border-border bg-surface px-3.5 py-2 text-sm text-ink-muted"><span className="size-2 animate-pulse rounded-full bg-tier-uncertain" />Waking the research engine — usually under a minute.</p>}
              {composer(false)}
              <p className="mt-2 text-center text-xs text-ink-subtle">LIT can make mistakes. Check important points against the source. An indicative research tool, not legal advice.</p>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
