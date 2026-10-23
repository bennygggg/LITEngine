import { lazy, memo, Suspense, useMemo } from 'react'
import { cn } from '@/lib/cn'

const MarkdownImpl = lazy(() => import('./MarkdownImpl'))

/** Split on blank lines that are outside a code fence, so finished paragraphs never re-render while the last one grows. */
export function splitBlocks(text: string): string[] {
  const blocks: string[] = []
  let current: string[] = []
  let fenced = false
  for (const line of text.split('\n')) {
    if (/^\s*```/.test(line)) fenced = !fenced
    if (!fenced && line.trim() === '' && current.length) {
      blocks.push(current.join('\n'))
      current = []
    } else {
      current.push(line)
    }
  }
  if (current.length) blocks.push(current.join('\n'))
  return blocks
}

/** The markdown engine (~50 kB gzipped) loads on the first reply, not with the app shell; plain text covers the gap. */
export const StreamingMarkdown = memo(function StreamingMarkdown({ text, streaming = false, className }: { text: string; streaming?: boolean; className?: string }) {
  const fallback = useMemo(() => <div className={cn('prose-lit whitespace-pre-wrap', className)}>{text}</div>, [text, className])
  return (
    <Suspense fallback={fallback}>
      <MarkdownImpl text={text} streaming={streaming} className={className} />
    </Suspense>
  )
})
