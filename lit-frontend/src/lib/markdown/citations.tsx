import { createContext, useContext, type ReactNode } from 'react'
import { Tooltip } from '@/design/ui/Tooltip'
import { cn } from '@/lib/cn'

export interface CitationInfo {
  /** Short heading, e.g. the judgment title. */
  title: string
  /** One line of context, e.g. "Supreme Court · 1997 · cosine 0.59". */
  detail?: string
}

export interface CitationApi {
  resolve: (handle: string) => CitationInfo | null
  open: (handle: string) => void
}

const CitationContext = createContext<CitationApi | null>(null)

export function CitationProvider({ value, children }: { value: CitationApi; children: ReactNode }) {
  return <CitationContext.Provider value={value}>{children}</CitationContext.Provider>
}

/** [P1] / [S2] as a small chip: hover shows what it points at, click opens it in the canvas. */
export function CitationChip({ handle }: { handle: string }) {
  const api = useContext(CitationContext)
  const info = api?.resolve(handle) ?? null
  if (!info) return <span className="text-ink-subtle">{handle}</span> // unresolvable: plain muted text, never a dead link
  return (
    <Tooltip label={<span><strong className="font-medium">{info.title}</strong>{info.detail ? <><br />{info.detail}</> : null}</span>}>
      <button
        type="button"
        onClick={() => api?.open(handle)}
        className={cn(
          'mx-0.5 inline-flex h-[1.15rem] -translate-y-px items-center rounded border border-transparent bg-accent-soft px-1.5',
          'align-baseline text-2xs font-semibold tabular-nums text-accent transition-colors hover:border-accent/40',
        )}
        aria-label={`Open source ${handle}: ${info.title}`}
      >
        {handle}
      </button>
    </Tooltip>
  )
}
