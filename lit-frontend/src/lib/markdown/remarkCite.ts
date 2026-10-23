import type { Root, Text, PhrasingContent } from 'mdast'

const HANDLE = /\[([PS]\d{1,2})\]/g

/** Turn [P1] / [S2] in text nodes into `cite` nodes (rendered as citation chips). Never touches code spans or links. */
export function remarkCite() {
  return (tree: Root) => {
    const visit = (node: { children?: unknown[]; type: string }) => {
      if (!node.children || node.type === 'code' || node.type === 'inlineCode' || node.type === 'link') return
      const out: unknown[] = []
      for (const child of node.children as Array<{ type: string; value?: string; children?: unknown[] }>) {
        if (child.type !== 'text' || typeof child.value !== 'string') {
          visit(child)
          out.push(child)
          continue
        }
        let last = 0
        for (const m of child.value.matchAll(HANDLE)) {
          if (m.index! > last) out.push({ type: 'text', value: child.value.slice(last, m.index) } satisfies Text)
          out.push({ type: 'cite', data: { hName: 'cite-chip', hProperties: { handle: m[1] } }, children: [] } as unknown as PhrasingContent)
          last = m.index! + m[0].length
        }
        if (last === 0) out.push(child)
        else if (last < child.value.length) out.push({ type: 'text', value: child.value.slice(last) } satisfies Text)
      }
      node.children = out
    }
    visit(tree as never)
  }
}
