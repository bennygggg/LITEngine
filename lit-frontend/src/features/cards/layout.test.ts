import type { AgentEvent, ArgumentMapCard } from '@/types/agent'
import map from '@/test/fixtures/argument_map.json'
import { layoutGraph, LANES } from './layout'

const graph = ((map as unknown as AgentEvent[]).find((e) => e.event === 'card' && e.payload.type === 'argument_map') as { payload: ArgumentMapCard }).payload.graph

describe('layoutGraph', () => {
  const layout = layoutGraph(graph)

  it('places every node exactly once, inside the canvas, with no overlaps in a lane', () => {
    expect(layout.nodes).toHaveLength(graph.nodes.length)
    for (const n of layout.nodes) {
      expect(n.x - n.w / 2).toBeGreaterThanOrEqual(0)
      expect(n.x + n.w / 2).toBeLessThanOrEqual(layout.width)
      expect(n.y - n.h / 2).toBeGreaterThanOrEqual(0)
      expect(n.y + n.h / 2).toBeLessThanOrEqual(layout.height)
    }
    for (const lane of LANES) {
      const ys = layout.nodes.filter((n) => n.type === lane).map((n) => n.y).sort((a, b) => a - b)
      for (let i = 1; i < ys.length; i++) expect(ys[i]! - ys[i - 1]!).toBeGreaterThanOrEqual(34)
    }
  })

  it('flows left to right: support, then claims, then issues', () => {
    const x = (t: string) => layout.nodes.find((n) => n.type === t)?.x ?? Infinity
    expect(x('EVIDENCE')).toBeLessThan(x('CLAIM'))
    expect(x('CLAIM')).toBeLessThan(x('ISSUE'))
    for (const e of layout.edges) {
      const a = layout.nodes.find((n) => n.id === e.source)!
      const b = layout.nodes.find((n) => n.id === e.target)!
      expect(a.x).toBeLessThan(b.x)
    }
  })

  it('is deterministic', () => {
    expect(layoutGraph(graph)).toEqual(layout)
    expect(layoutGraph({ ...graph, nodes: [...graph.nodes].reverse() }).nodes.map((n) => n.id).sort()).toEqual(layout.nodes.map((n) => n.id).sort())
  })

  it('draws an edge for every relationship whose endpoints exist', () => {
    expect(layout.edges).toHaveLength(graph.edges.length)
    expect(layout.edges.every((e) => e.d.startsWith('M'))).toBe(true)
  })

  it('copes with an empty graph', () => {
    const empty = layoutGraph({ nodes: [], edges: [], weak_nodes: [], node_count: 0, edge_count: 0 })
    expect(empty.nodes).toEqual([]) 
    expect(empty.width).toBeGreaterThan(0)
  })
})
