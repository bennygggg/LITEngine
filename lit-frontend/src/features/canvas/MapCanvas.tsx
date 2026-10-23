import cytoscape, { type Core, type ElementDefinition } from 'cytoscape'
import { Download, Focus, Maximize, Search, TriangleAlert } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import * as Tabs from '@radix-ui/react-tabs'
import { Button } from '@/design/ui/Button'
import { cn } from '@/lib/cn'
import { LANES, layoutGraph, TYPE_LABEL, TYPE_TOKEN, type NodeType } from '@/features/cards/layout'
import type { ArgumentMapCard } from '@/types/agent'

const SHAPE: Record<NodeType, string> = { EVIDENCE: 'ellipse', STATUTE: 'cut-rectangle', PRECEDENT: 'round-tag', CLAIM: 'round-rectangle', ISSUE: 'rectangle' }

/** Theme colours are CSS variables; Cytoscape needs concrete colours, so read them at (re)style time. */
function token(name: string, alpha = 1): string {
  // Cytoscape only parses the comma form, not the CSS-4 space-separated `rgb(r g b / a)` the tokens use elsewhere.
  const [r, g, b] = getComputedStyle(document.documentElement).getPropertyValue(`--c-${name}`).trim().split(/\s+/)
  return alpha === 1 ? `rgb(${r}, ${g}, ${b})` : `rgba(${r}, ${g}, ${b}, ${alpha})`
}

function styleSheet(): cytoscape.StylesheetJson {
  const ink = token('ink')
  return [
    { selector: 'node', style: { shape: 'data(shape)' as never, width: 'data(w)', height: 'data(h)', label: 'data(short)', 'font-family': 'Inter Variable, system-ui, sans-serif', 'font-size': 12, color: ink, 'text-valign': 'center', 'text-halign': 'center', 'text-wrap': 'ellipsis', 'text-max-width': '116px', 'background-color': 'data(color)' as never, 'background-opacity': 0.16, 'border-width': 1.5, 'border-color': 'data(color)' as never } },
    { selector: 'node[?weak]', style: { 'border-color': token('unfav'), 'border-width': 3 } },
    { selector: 'node:selected', style: { 'border-color': ink, 'border-width': 3 } },
    { selector: 'edge', style: { width: 1.2, 'line-color': token('border-strong'), 'target-arrow-color': token('border-strong'), 'target-arrow-shape': 'triangle', 'arrow-scale': 0.7, 'curve-style': 'bezier', opacity: 0.8 } },
    { selector: 'edge[?hot]', style: { width: 2.4, 'line-color': token('accent'), 'target-arrow-color': token('accent'), opacity: 1 } },
    { selector: '.dim', style: { opacity: 0.12 } },
    { selector: '.hide', style: { display: 'none' } },
  ] as cytoscape.StylesheetJson
}

const short = (s: string) => (s.length > 26 ? `${s.slice(0, 25)}…` : s)

export default function MapCanvas({ card, focus }: { card: ArgumentMapCard; focus?: string }) {
  // A tighter grid than the inline preview, so labels stay readable once the whole map is fitted into the side panel.
  const layout = useMemo(() => layoutGraph(card.graph, { colWidth: 150, nodeW: 128, nodeH: 30, rowHeight: 40, pad: 14 }), [card.graph])
  const host = useRef<HTMLDivElement>(null)
  const cy = useRef<Core | null>(null)
  const [selected, setSelected] = useState<string | null>(focus ?? null)
  const [active, setActive] = useState<Set<NodeType>>(() => new Set(LANES))
  const [q, setQ] = useState('')
  const [focusMode, setFocusMode] = useState(false)
  const nodesById = useMemo(() => new Map(card.graph.nodes.map((n) => [n.id, n])), [card.graph])
  const weakIds = useMemo(() => new Set(card.graph.weak_nodes ?? []), [card.graph])

  useEffect(() => {
    if (!host.current) return
    const elements: ElementDefinition[] = [
      ...layout.nodes.map((n) => ({
        data: { id: n.id, label: n.label, short: short(n.label), type: n.type, weak: n.weak, shape: SHAPE[n.type], w: n.w, h: n.type === 'ISSUE' || n.type === 'CLAIM' ? 40 : n.h, color: token(TYPE_TOKEN[n.type]), tint: token(TYPE_TOKEN[n.type], 0.14) },
        position: { x: n.x, y: n.y },
      })),
      ...layout.edges.map((e) => ({ data: { id: e.id, source: e.source, target: e.target } })),
    ]
    const instance = cytoscape({ container: host.current, elements, style: styleSheet(), layout: { name: 'preset' }, minZoom: 0.2, maxZoom: 2.5, wheelSensitivity: 0.25, boxSelectionEnabled: false })
    instance.fit(undefined, 16)
    instance.on('tap', 'node', (e) => setSelected(e.target.id()))
    instance.on('tap', (e) => { if (e.target === instance) setSelected(null) })
    cy.current = instance
    const ro = new ResizeObserver(() => { instance.resize(); instance.fit(undefined, 16) })
    ro.observe(host.current)
    const mo = new MutationObserver(() => { instance.style(styleSheet()); instance.nodes().forEach((n) => { const t = n.data('type') as NodeType; n.data('color', token(TYPE_TOKEN[t])); n.data('tint', token(TYPE_TOKEN[t], 0.14)) }) })
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
    return () => { ro.disconnect(); mo.disconnect(); instance.destroy(); cy.current = null }
  }, [layout])

  // filters, search, selection and focus mode are all expressed as classes on the same instance
  useEffect(() => {
    const c = cy.current
    if (!c) return
    c.batch(() => {
      const needle = q.trim().toLowerCase()
      c.elements().removeClass('dim hide').removeData('hot')
      c.nodes().forEach((n) => { if (!active.has(n.data('type'))) n.addClass('hide') })
      c.edges().forEach((e) => { if (e.source().hasClass('hide') || e.target().hasClass('hide')) e.addClass('hide') })
      if (needle) c.nodes().forEach((n) => { if (!String(n.data('label')).toLowerCase().includes(needle)) n.addClass('dim') })
      c.nodes().unselect()
      if (selected && c.getElementById(selected).nonempty()) {
        const sel = c.getElementById(selected)
        sel.select()
        sel.connectedEdges().forEach((e) => { e.data('hot', true) })
        if (focusMode) c.elements().not(sel.closedNeighborhood()).addClass('dim')
      }
    })
  }, [active, q, selected, focusMode, layout])

  const sel = selected ? nodesById.get(selected) : undefined
  const connections = useMemo(() => {
    if (!selected) return []
    return card.graph.edges.filter((e) => e.source === selected || e.target === selected).map((e) => {
      const other = nodesById.get(e.source === selected ? e.target : e.source)
      return { edge: e, other, outgoing: e.source === selected }
    })
  }, [card.graph.edges, selected, nodesById])

  const toggle = (t: NodeType) => setActive((cur) => { const next = new Set(cur); if (next.has(t)) next.delete(t); else next.add(t); return next })
  const exportPng = () => { const c = cy.current; if (!c) return; const a = document.createElement('a'); a.href = c.png({ full: true, scale: 2, bg: token('surface') }); a.download = 'lit-argument-map.png'; a.click() }
  const present = LANES.filter((l) => layout.nodes.some((n) => n.type === l))

  return (
    <Tabs.Root defaultValue="map" className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between border-b border-border px-4">
        <Tabs.List className="flex gap-5" aria-label="Map views">
          {['map', 'list'].map((t) => <Tabs.Trigger key={t} value={t} className="relative py-2.5 text-sm capitalize text-ink-muted outline-none data-[state=active]:text-ink data-[state=active]:after:absolute data-[state=active]:after:inset-x-0 data-[state=active]:after:-bottom-px data-[state=active]:after:h-0.5 data-[state=active]:after:bg-ink">{t === 'map' ? 'Map' : 'List'}</Tabs.Trigger>)}
        </Tabs.List>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="icon-sm" aria-label="Focus on the selected element" aria-pressed={focusMode} onClick={() => setFocusMode(!focusMode)} className={cn(focusMode && 'bg-border/70')}><Focus /></Button>
          <Button variant="ghost" size="icon-sm" aria-label="Fit to panel" onClick={() => cy.current?.fit(undefined, 16)}><Maximize /></Button>
          <Button variant="ghost" size="icon-sm" aria-label="Download as PNG" onClick={exportPng}><Download /></Button>
        </div>
      </div>

      <Tabs.Content value="map" className="flex min-h-0 flex-1 flex-col outline-none">
        <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2.5">
          {present.map((t) => (
            <button key={t} type="button" aria-pressed={active.has(t)} onClick={() => toggle(t)} className={cn('flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors', active.has(t) ? 'border-border-strong bg-surface text-ink' : 'border-border text-ink-subtle line-through')}>
              <span aria-hidden className="size-2 rounded-full" style={{ background: token(TYPE_TOKEN[t]) }} />{TYPE_LABEL[t]}
            </button>
          ))}
          <label className="relative ml-auto"><Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-ink-subtle" /><input value={q} onChange={(e) => setQ(e.target.value)} aria-label="Find an element" placeholder="Find" className="h-7 w-28 rounded-md border border-border bg-surface pl-7 pr-2 text-xs outline-none focus:border-ink" /></label>
        </div>
        <div ref={host} className="min-h-0 flex-1 bg-sunken/50" role="img" aria-label="Interactive argument map. A list view with the same content is on the List tab." />
        <div className="max-h-[42%] shrink-0 overflow-y-auto border-t border-border px-4 py-3 text-sm">
          {sel ? (
            <div>
              <p className="text-2xs font-medium uppercase tracking-[0.08em]" style={{ color: token(TYPE_TOKEN[sel.type as NodeType]) }}>{TYPE_LABEL[sel.type as NodeType]}{weakIds.has(sel.id) && ' · no evidence link'}</p>
              <h3 className="mt-0.5 font-display text-base font-medium leading-snug">{sel.label}</h3>
              {sel.description && <p className="mt-1 text-ink-muted">{sel.description}</p>}
              {connections.length > 0 && (
                <ul className="mt-2 space-y-1">
                  {connections.map(({ edge, other, outgoing }) => (
                    <li key={edge.id}><button type="button" onClick={() => other && setSelected(other.id)} className="flex w-full items-baseline gap-2 rounded px-1 py-0.5 text-left hover:bg-sunken">
                      <span className="w-14 shrink-0 text-2xs uppercase tracking-wide text-ink-subtle">{outgoing ? edge.label || edge.type : `← ${edge.label || edge.type}`}</span>
                      <span className="min-w-0 flex-1 truncate">{other?.label}</span>
                    </button></li>
                  ))}
                </ul>
              )}
            </div>
          ) : (
            <p className="text-ink-muted">{weakIds.size > 0 ? <span className="flex items-start gap-2"><TriangleAlert className="mt-0.5 size-4 shrink-0 text-tier-unfavorable" />{weakIds.size} claim{weakIds.size > 1 ? 's have' : ' has'} no evidence link. Select a node to inspect it.</span> : 'Select a node to see what connects to it. Drag to pan, scroll to zoom.'}</p>
          )}
        </div>
      </Tabs.Content>

      <Tabs.Content value="list" className="min-h-0 flex-1 overflow-y-auto px-4 py-3 outline-none">
        {present.map((t) => (
          <section key={t} className="mb-5">
            <h3 className="mb-1.5 text-2xs font-medium uppercase tracking-[0.08em] text-ink-subtle">{TYPE_LABEL[t]}</h3>
            <ul className="divide-y divide-border rounded-lg border border-border">
              {card.graph.nodes.filter((n) => n.type === t).map((n) => {
                const links = card.graph.edges.filter((e) => e.source === n.id || e.target === n.id)
                return <li key={n.id} className="px-3 py-2 text-sm"><p>{n.label}{weakIds.has(n.id) && <span className="ml-2 text-xs text-tier-unfavorable">no evidence link</span>}</p><p className="text-xs text-ink-subtle">{links.length} link{links.length === 1 ? '' : 's'}</p></li>
              })}
            </ul>
          </section>
        ))}
      </Tabs.Content>
    </Tabs.Root>
  )
}
