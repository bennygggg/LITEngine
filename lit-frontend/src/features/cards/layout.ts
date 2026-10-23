import type { ArgumentMapCard } from '@/types/agent'

type Graph = ArgumentMapCard['graph']
export type NodeType = 'EVIDENCE' | 'STATUTE' | 'PRECEDENT' | 'CLAIM' | 'ISSUE'

/** Left-to-right argument flow: support (evidence, statute, precedent) -> claims -> issues. */
export const LANES: NodeType[] = ['EVIDENCE', 'STATUTE', 'PRECEDENT', 'CLAIM', 'ISSUE']

export interface PlacedNode {
  id: string
  type: NodeType
  label: string
  weak: boolean
  x: number // centre
  y: number
  w: number
  h: number
}
export interface PlacedEdge {
  id: string
  source: string
  target: string
  type: string
  strength: number
  d: string // cubic bezier path
}
export interface Layout {
  nodes: PlacedNode[]
  edges: PlacedEdge[]
  width: number
  height: number
}

export interface LayoutOptions {
  colWidth?: number
  rowHeight?: number
  nodeW?: number
  nodeH?: number
  pad?: number
}

/**
 * Deterministic layered layout (same input -> same output, so it can be snapshot-tested and reproduced in the demo).
 * Rows inside a lane are ordered by the barycentre of their neighbours (two sweeps) to keep edge crossings low.
 */
export function layoutGraph(graph: Graph, opts: LayoutOptions = {}): Layout {
  const { colWidth = 210, rowHeight = 46, nodeW = 168, nodeH = 34, pad = 20 } = opts
  const weakSet = new Set(graph.weak_nodes ?? [])
  const lanes: Record<NodeType, string[]> = { EVIDENCE: [], STATUTE: [], PRECEDENT: [], CLAIM: [], ISSUE: [] }
  const byId = new Map(graph.nodes.map((n) => [n.id, n]))
  for (const n of graph.nodes) (lanes[n.type as NodeType] ?? lanes.EVIDENCE).push(n.id)

  const neighbours = new Map<string, string[]>()
  for (const e of graph.edges) {
    neighbours.set(e.source, [...(neighbours.get(e.source) ?? []), e.target])
    neighbours.set(e.target, [...(neighbours.get(e.target) ?? []), e.source])
  }
  const order = new Map<string, number>()
  const reindex = () => LANES.forEach((lane) => lanes[lane].forEach((id, i) => order.set(id, i)))
  reindex()
  const sortLane = (lane: NodeType) => {
    const bary = (id: string) => {
      const ns = (neighbours.get(id) ?? []).filter((n) => byId.get(n) && byId.get(n)!.type !== lane)
      return ns.length ? ns.reduce((s, n) => s + (order.get(n) ?? 0), 0) / ns.length : order.get(id) ?? 0
    }
    lanes[lane] = [...lanes[lane]].sort((a, b) => bary(a) - bary(b) || (order.get(a) ?? 0) - (order.get(b) ?? 0))
    reindex()
  }
  for (let sweep = 0; sweep < 2; sweep++) {
    for (const lane of [...LANES].reverse()) sortLane(lane)
    for (const lane of LANES) sortLane(lane)
  }

  const used = LANES.filter((l) => lanes[l].length)
  const rows = Math.max(1, ...used.map((l) => lanes[l].length))
  const height = rows * rowHeight + pad * 2
  const width = Math.max(used.length, 1) * colWidth + pad * 2 - (colWidth - nodeW)
  const placed = new Map<string, PlacedNode>()
  used.forEach((lane, col) => {
    const ids = lanes[lane]
    const top = pad + ((rows - ids.length) * rowHeight) / 2 // centre each lane vertically
    ids.forEach((id, i) => {
      const n = byId.get(id)!
      placed.set(id, {
        id, type: lane, label: n.label, weak: weakSet.has(id) || Boolean(n.weak),
        x: pad + col * colWidth + nodeW / 2, y: top + i * rowHeight + rowHeight / 2, w: nodeW, h: nodeH,
      })
    })
  })
  const edges: PlacedEdge[] = []
  for (const e of graph.edges) {
    const a = placed.get(e.source)
    const b = placed.get(e.target)
    if (!a || !b) continue
    const x1 = a.x + a.w / 2
    const x2 = b.x - b.w / 2
    const mid = (x1 + x2) / 2
    edges.push({ id: e.id, source: e.source, target: e.target, type: e.type, strength: e.strength ?? 0.5, d: `M${x1},${a.y} C${mid},${a.y} ${mid},${b.y} ${x2},${b.y}` })
  }
  return { nodes: [...placed.values()], edges, width, height }
}

export const TYPE_LABEL: Record<NodeType, string> = { EVIDENCE: 'Evidence', STATUTE: 'Statute', PRECEDENT: 'Precedent', CLAIM: 'Claim', ISSUE: 'Issue' }
export const TYPE_TOKEN: Record<NodeType, string> = { EVIDENCE: 'node-evidence', STATUTE: 'node-statute', PRECEDENT: 'node-precedent', CLAIM: 'node-claim', ISSUE: 'node-issue' }
