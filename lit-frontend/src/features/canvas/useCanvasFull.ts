import { useChat } from '@/lib/store/chat'
import { useUi } from '@/lib/store/ui'

/** Whether the details panel currently covers the whole window: the argument map opens that way unless the user steps back. */
export function useCanvasFull(): boolean {
  const canvas = useUi((s) => s.canvas)
  const chosen = useUi((s) => s.canvasExpanded)
  const isMap = useChat((s) => {
    if (!canvas) return false
    return Object.values(s.messages).some((list) => list.some((m) => m.parts.some((p) => p.kind === 'card' && p.cardId === canvas.cardId && p.type === 'argument_map')))
  })
  return canvas !== null && (chosen ?? isMap)
}
