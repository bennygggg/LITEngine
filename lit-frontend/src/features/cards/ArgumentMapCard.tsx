import { Maximize2, TriangleAlert } from 'lucide-react'
import { useMemo } from 'react'
import { Button } from '@/design/ui/Button'
import { CardShell } from '@/design/ui/CardShell'
import { useChatActions } from '@/features/chat/actions'
import type { ArgumentMapCard as Card } from '@/types/agent'
import { LANES, layoutGraph, TYPE_LABEL, TYPE_TOKEN, type NodeType, type PlacedNode } from './layout'

const fill = (t: NodeType) => `rgb(var(--c-${TYPE_TOKEN[t]}))`

function Shape({ n }: { n: PlacedNode }) {
  const c = fill(n.type)
  const r = 9
  switch (n.type) {
    case 'EVIDENCE': return <circle cx={n.x} cy={n.y} r={r} fill={c} />
    case 'STATUTE': return <rect x={n.x - r} y={n.y - r} width={r * 2} height={r * 2} fill={c} transform={`rotate(45 ${n.x} ${n.y})`} rx={1.5} />
    case 'PRECEDENT': return <rect x={n.x - r - 1} y={n.y - r + 1} width={(r + 1) * 2} height={(r - 1) * 2} fill={c} rx={4} />
    default: return <rect x={n.x - r - 3} y={n.y - r + 1} width={(r + 3) * 2} height={(r - 1) * 2} fill={c} rx={2.5} stroke={n.weak ? 'rgb(var(--c-unfav))' : 'none'} strokeWidth={n.weak ? 2.5 : 0} />
  }
}

/** Static preview of the map: no graph library, so a long conversation of maps stays light. The interactive version lives in the side panel. */
export function MapThumb({ card, className }: { card: Card; className?: string }) {
  const layout = useMemo(() => layoutGraph(card.graph), [card.graph])
  const presentLanes = LANES.filter((l) => layout.nodes.some((n) => n.type === l))
  const laneX = (l: NodeType) => layout.nodes.find((n) => n.type === l)!.x
  const s = card.summary
  return (
    <svg viewBox={`0 0 ${layout.width} ${layout.height + 30}`} role="img" className={className} preserveAspectRatio="xMidYMid meet"
      aria-label={`Argument map: ${s?.issues ?? 0} issues, ${s?.claims ?? 0} claims, ${s?.evidence ?? 0} evidence, ${s?.statutes ?? 0} statutes, ${s?.precedents ?? 0} precedents; ${s?.weak_claims ?? 0} claims without evidence links`}>
      {presentLanes.map((l) => <text key={l} x={laneX(l)} y={16} textAnchor="middle" fontSize={16} fill="rgb(var(--c-ink-subtle))" style={{ letterSpacing: '0.06em', textTransform: 'uppercase' }}>{TYPE_LABEL[l]}</text>)}
      <g transform="translate(0 30)">
        {layout.edges.map((e) => <path key={e.id} d={e.d} fill="none" stroke="rgb(var(--c-border-strong))" strokeWidth={1} opacity={0.75} />)}
        {layout.nodes.map((n) => <Shape key={n.id} n={n} />)}
      </g>
    </svg>
  )
}

export function ArgumentMapCardView({ card }: { card: Card }) {
  const actions = useChatActions()
  const s = card.summary
  const weak = (card.graph.nodes ?? []).filter((n) => (card.graph.weak_nodes ?? []).includes(n.id))
  const counts: Array<[NodeType, number]> = [['ISSUE', s?.issues ?? 0], ['CLAIM', s?.claims ?? 0], ['EVIDENCE', s?.evidence ?? 0], ['STATUTE', s?.statutes ?? 0], ['PRECEDENT', s?.precedents ?? 0]]
  return (
    <CardShell
      eyebrow="Argument map" title={card.title} subtitle={card.subtitle ?? undefined} disclaimer={card.disclaimer ?? undefined}
      actions={<Button variant="outline" size="sm" onClick={() => actions.openCanvas(card.card_id)}><Maximize2 /> Open map</Button>}
    >
      <MapThumb card={card} className="h-auto max-h-72 w-full" />
      <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5" aria-label="Legend">
        {counts.filter(([, n]) => n > 0).map(([t, n]) => (
          <li key={t} className="flex items-center gap-1.5 text-xs text-ink-muted"><span aria-hidden className="size-2.5 rounded-sm" style={{ background: fill(t) }} />{TYPE_LABEL[t]} <span className="tnum text-ink-subtle">{n}</span></li>
        ))}
      </ul>
      {weak.length > 0 && (
        <div className="mt-3 flex items-start gap-2 rounded-lg border border-border-strong bg-sunken px-3 py-2 text-sm">
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-tier-unfavorable" />
          <p><strong className="font-medium">{weak.length} claim{weak.length > 1 ? 's' : ''} with no evidence link:</strong> {weak.map((w) => w.label).join('; ')}. This flags a gap in the map, not a weakness in the claim.</p>
        </div>
      )}
    </CardShell>
  )
}
