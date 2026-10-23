import { X } from 'lucide-react'
import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { Button } from '@/design/ui/Button'
import { Skeleton } from '@/design/ui/Skeleton'
import { CardRenderer } from '@/features/cards/CardRenderer'
import { cn } from '@/lib/cn'
import { useChat } from '@/lib/store/chat'
import { useUi } from '@/lib/store/ui'
import type { CardPart } from '@/features/chat/model'
import { DEMO_CONV } from '@/features/demo/constants'
import { DEMO_MATTER_ID } from '@/features/matters/ids'

const MapCanvas = lazy(() => import('./MapCanvas'))
const PrecedentsCanvas = lazy(() => import('./PrecedentsCanvas'))
const SourceViewer = lazy(() => import('./SourceViewer'))

/** The recorded session's matter is bundled (not stored); fetch its text only when a source from the demo is opened. */
function useDemoText(enabled: boolean): string | undefined {
  const [text, setText] = useState<string>()
  useEffect(() => {
    if (!enabled) return
    void import('@/features/matters/samples').then((m) => setText(m.SAMPLE_MATTERS.find((s) => s.id === DEMO_MATTER_ID)?.text))
  }, [enabled])
  return enabled ? text : undefined
}

const NAMES: Record<string, string> = { argument_map: 'Argument map', precedents: 'Precedents', sources: 'Source document', outcome: 'Outcome', scenario: 'Scenarios', case_profile: 'Case profile' }

/** Right-hand panel for expanded artifacts. A side sheet on desktop, a full-screen sheet on small screens. */
export function CanvasHost() {
  const { canvas, closeCanvas, canvasWidth, setCanvasWidth } = useUi()
  const messages = useChat((s) => s.messages)
  const conversations = useChat((s) => s.conversations)
  const drag = useRef<{ x: number; w: number } | null>(null)
  const cardIdForDemo = canvas?.cardId
  const inDemo = Boolean(cardIdForDemo && (messages[DEMO_CONV] ?? []).some((m) => m.parts.some((p) => p.kind === 'card' && p.cardId === cardIdForDemo)))
  const demoText = useDemoText(inDemo)
  if (!canvas) return null

  let part: CardPart | undefined
  let convId: string | undefined
  for (const [id, list] of Object.entries(messages)) {
    for (const m of list) {
      const hit = m.parts.find((p): p is CardPart => p.kind === 'card' && p.cardId === canvas.cardId)
      if (hit) { part = hit; convId = id }
    }
  }
  const card = part?.payload
  const caseId = conversations.find((c) => c.id === convId)?.caseId ?? null

  return (
    <aside style={{ width: undefined }} aria-label="Details panel"
      className={cn('fixed inset-0 z-40 flex flex-col bg-surface lg:static lg:inset-auto lg:z-auto lg:shrink-0 lg:border-l lg:border-border')}>
      <style>{`@media (min-width:1024px){aside[aria-label="Details panel"]{width:${canvasWidth}px}}`}</style>
      <div role="separator" aria-orientation="vertical" aria-label="Resize panel" aria-valuenow={canvasWidth} aria-valuemin={420} aria-valuemax={720} tabIndex={0}
        className="absolute -left-1 top-0 hidden h-full w-2 cursor-col-resize lg:block hover:bg-border-strong/40"
        onPointerDown={(e) => { drag.current = { x: e.clientX, w: canvasWidth }; (e.target as HTMLElement).setPointerCapture(e.pointerId) }}
        onPointerMove={(e) => { if (drag.current) setCanvasWidth(drag.current.w + (drag.current.x - e.clientX)) }}
        onPointerUp={() => { drag.current = null }}
        onKeyDown={(e) => { if (e.key === 'ArrowLeft') setCanvasWidth(canvasWidth + 24); if (e.key === 'ArrowRight') setCanvasWidth(canvasWidth - 24) }} />
      <header className="flex h-14 shrink-0 items-center justify-between border-b border-border px-4">
        <div className="min-w-0"><p className="text-xs font-medium text-ink-subtle">{card ? NAMES[card.type] : 'Details'}</p><h2 className="truncate font-display text-base font-normal leading-tight">{(card && 'subtitle' in card && card.subtitle) || card?.title || 'Not available'}</h2></div>
        <Button variant="ghost" size="icon-sm" aria-label="Close panel" onClick={closeCanvas}><X /></Button>
      </header>
      <div className="min-h-0 flex-1">
        <Suspense fallback={<div className="space-y-3 p-4"><Skeleton className="h-6 w-1/2" /><Skeleton className="h-64 w-full" /></div>}>
          {!card ? <p className="p-4 text-sm text-ink-muted">This item is no longer in the conversation.</p>
            : card.type === 'argument_map' ? <MapCanvas card={card} focus={canvas.focus} />
            : card.type === 'precedents' ? <PrecedentsCanvas card={card} focus={canvas.focus} />
            : card.type === 'sources' ? <SourceViewer card={card} focus={canvas.focus} caseId={caseId} textOverride={convId === DEMO_CONV ? demoText : undefined} />
            : <div className="h-full overflow-y-auto p-4"><CardRenderer part={part!} /></div>}
        </Suspense>
      </div>
    </aside>
  )
}
