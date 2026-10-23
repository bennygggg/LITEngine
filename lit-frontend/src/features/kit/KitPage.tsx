import { useState } from 'react'
import { ArrowUp, Check, Moon, Monitor, Plus, Sun, TriangleAlert } from 'lucide-react'
import { Badge } from '@/design/ui/Badge'
import { Button } from '@/design/ui/Button'
import { CardShell } from '@/design/ui/CardShell'
import { Kbd } from '@/design/ui/Kbd'
import { Skeleton } from '@/design/ui/Skeleton'
import { getThemeMode, setThemeMode, type ThemeMode } from '@/lib/theme'
import { cn } from '@/lib/cn'

const SURFACES = ['bg', 'surface', 'sunken', 'border', 'border-strong'] as const
const INKS = ['ink', 'ink-muted', 'ink-subtle', 'accent', 'accent-soft'] as const
const TIERS = [
  ['fav', 'Favorable'],
  ['unc', 'Uncertain'],
  ['unfav', 'Unfavorable'],
] as const
const NODES = [
  ['node-issue', 'Issue', 'rounded-md'],
  ['node-claim', 'Claim', 'rounded-md'],
  ['node-evidence', 'Evidence', 'rounded-full'],
  ['node-statute', 'Statute', 'rotate-45 rounded-sm'],
  ['node-precedent', 'Precedent', 'rounded-lg'],
] as const

function Swatch({ token }: { token: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className="size-9 shrink-0 rounded-md border border-border-strong" style={{ background: `rgb(var(--c-${token}))` }} />
      <div>
        <p className="text-sm font-medium text-ink">{token}</p>
        <p className="tnum text-2xs text-ink-subtle">--c-{token}</p>
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-4">
      <h2 className="border-b border-border pb-2 text-xs font-medium text-ink-subtle">{title}</h2>
      {children}
    </section>
  )
}

export default function KitPage() {
  const [mode, setMode] = useState<ThemeMode>(getThemeMode())
  const choose = (next: ThemeMode) => {
    setMode(next)
    setThemeMode(next)
  }

  return (
    <main className="mx-auto max-w-4xl space-y-12 px-6 py-12">
      <header className="flex items-end justify-between gap-6">
        <div>
          <p className="mb-2 text-xs font-medium text-ink-subtle">LIT · Design kit · Phase 0</p>
          <h1 className="font-display text-4xl font-normal tracking-tight">Foundations</h1>
          <p className="mt-2 max-w-xl text-ink-muted">
            Tokens, type and the base primitives every card builds on. Re-tuning the look (the Harvey pass) edits
            <code className="mx-1 rounded bg-sunken px-1 text-sm">tokens.css</code>
            and a few component variants — nothing else.
          </p>
        </div>
        <div className="flex gap-1 rounded-lg border border-border bg-surface p-1" role="group" aria-label="Theme">
          {([['light', Sun], ['system', Monitor], ['dark', Moon]] as const).map(([m, Icon]) => (
            <Button key={m} variant={mode === m ? 'secondary' : 'ghost'} size="icon-sm" aria-pressed={mode === m} aria-label={`${m} theme`} onClick={() => choose(m)}>
              <Icon />
            </Button>
          ))}
        </div>
      </header>

      <Section title="Colour tokens">
        <div className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3">
          {[...SURFACES, ...INKS].map((t) => <Swatch key={t} token={t} />)}
        </div>
      </Section>

      <Section title="Outcome tiers — always colour + icon + words">
        <div className="flex flex-wrap gap-3">
          <Badge tone="favorable"><Check className="size-3" />Favorable</Badge>
          <Badge tone="uncertain"><TriangleAlert className="size-3" />Uncertain</Badge>
          <Badge tone="unfavorable"><ArrowUp className="size-3 rotate-180" />Unfavorable</Badge>
          {TIERS.map(([t, label]) => (
            <span key={t} className="inline-flex items-center gap-2 text-sm text-ink-muted">
              <span className="size-3 rounded-full" style={{ background: `rgb(var(--c-${t}))` }} />{label}
            </span>
          ))}
        </div>
      </Section>

      <Section title="Argument-map nodes — colour + shape">
        <div className="flex flex-wrap items-center gap-8">
          {NODES.map(([t, label, shape]) => (
            <div key={t} className="flex items-center gap-3">
              <span className={cn('size-5', shape)} style={{ background: `rgb(var(--c-${t}))` }} />
              <span className="text-sm text-ink-muted">{label}</span>
            </div>
          ))}
        </div>
      </Section>

      <Section title="Type">
        <div className="space-y-3">
          <p className="font-display text-4xl font-normal tracking-tight">What are you working on?</p>
          <p className="font-display text-2xl font-normal tracking-tight">Mohan Lal v. State of Rajasthan</p>
          <p className="font-display text-lg font-normal">Case profile</p>
          <p className="max-w-prose text-base text-ink">
            Body text sets at 15&nbsp;px with a 1.65 line height so long assistant answers read like a memo, not a chat bubble.
            Figures use tabular numerals: <span className="tnum">1,240 words · 505 judgments · cosine 0.572</span>.
          </p>
          <p className="text-sm text-ink-muted">UI chrome sets at 13&nbsp;px. Secondary information is muted, never faint.</p>
          <p className="text-xs font-medium text-ink-subtle">Eyebrow label</p>
        </div>
      </Section>

      <Section title="Controls">
        <div className="flex flex-wrap items-center gap-3">
          <Button>Primary</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="outline">Outline</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="accent">Accent</Button>
          <Button disabled>Disabled</Button>
          <Button size="icon" variant="outline" aria-label="Add"><Plus /></Button>
          <Badge>Neutral</Badge>
          <Badge tone="outline">Outline</Badge>
          <Badge tone="accent">[P1]</Badge>
          <span className="inline-flex items-center gap-1 text-sm text-ink-muted"><Kbd>⌘</Kbd><Kbd>↵</Kbd> send</span>
        </div>
      </Section>

      <Section title="Card frame">
        <CardShell
          eyebrow="Precedents"
          title="Closest matches in the library"
          subtitle="5 judgments decided before 30 Jun 2025"
          disclaimer={{ level: 'info', text: 'Closest matches among 505 indexed judgments — not an exhaustive search.' }}
        >
          <div className="space-y-3">
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-5/6" />
          </div>
        </CardShell>
        <CardShell
          eyebrow="Outcome"
          title="Indicative research estimate"
          disclaimer={{ level: 'caution', text: 'Trained on 187 appellate judgments. Treat as a base-rate indicator by appeal type, not advice.' }}
        >
          <p className="font-display text-3xl tracking-tight"><span className="tnum">Below even odds</span> <span className="text-ink-muted">· about 35%</span></p>
        </CardShell>
      </Section>
    </main>
  )
}
