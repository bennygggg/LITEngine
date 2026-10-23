import { FolderOpen, MoreHorizontal, Moon, PanelLeftClose, Play, Plus, Settings, Sun, Trash2, Pencil } from 'lucide-react'
import { useState } from 'react'
import { Link, NavLink, useNavigate } from 'react-router-dom'
import { Badge } from '@/design/ui/Badge'
import { Button } from '@/design/ui/Button'
import { Menu, MenuContent, MenuItem, MenuTrigger } from '@/design/ui/Menu'
import { cn } from '@/lib/cn'
import type { ConversationRecord } from '@/lib/persistence/storage'
import { useChat } from '@/lib/store/chat'
import { useEngine } from '@/lib/store/engine'
import { useUi } from '@/lib/store/ui'
import { getThemeMode, resolveTheme, setThemeMode } from '@/lib/theme'

const DAY = 86_400_000

export function groupByRecency(list: ConversationRecord[], now = Date.now()): Array<{ label: string; items: ConversationRecord[] }> {
  const start = new Date(now).setHours(0, 0, 0, 0)
  const groups: Record<string, ConversationRecord[]> = { Today: [], Yesterday: [], 'Previous 7 days': [], Earlier: [] }
  for (const c of list) {
    const key = c.updatedAt >= start ? 'Today' : c.updatedAt >= start - DAY ? 'Yesterday' : c.updatedAt >= start - 7 * DAY ? 'Previous 7 days' : 'Earlier'
    groups[key]!.push(c)
  }
  return Object.entries(groups).filter(([, items]) => items.length).map(([label, items]) => ({ label, items }))
}

function Wordmark() {
  return (
    <Link to="/" className="flex items-center gap-2 rounded-md px-1 py-0.5" aria-label="LIT — new chat">
      <span aria-hidden className="flex size-7 items-center justify-center rounded-lg bg-ink font-display text-lg font-semibold leading-none text-bg">L</span>
      <span className="font-display text-lg font-medium tracking-tight">LIT</span>
    </Link>
  )
}

function Item({ conv }: { conv: ConversationRecord }) {
  const chat = useChat()
  const navigate = useNavigate()
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(conv.title)
  const running = Boolean(chat.running[conv.id])
  if (editing) {
    return (
      <input
        autoFocus value={title} aria-label="Conversation title" onChange={(e) => setTitle(e.target.value)}
        onBlur={() => { setEditing(false); if (title.trim() && title !== conv.title) void chat.rename(conv.id, title.trim()) }}
        onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); if (e.key === 'Escape') { setTitle(conv.title); setEditing(false) } }}
        className="mx-1 h-8 w-[calc(100%-0.5rem)] rounded-md border border-ink bg-surface px-2 text-sm outline-none"
      />
    )
  }
  return (
    <div className="group/item relative">
      <NavLink to={`/c/${conv.id}`} className={({ isActive }) => cn('flex h-8 items-center gap-2 rounded-md px-2.5 pr-8 text-sm transition-colors', isActive ? 'bg-border/70 text-ink' : 'text-ink-muted hover:bg-border/40 hover:text-ink')}>
        <span className="truncate">{conv.title}</span>
        {running && <span className="size-1.5 shrink-0 animate-pulse rounded-full bg-accent" aria-label="Running" />}
      </NavLink>
      <Menu>
        <MenuTrigger asChild>
          <button type="button" aria-label={`Options for ${conv.title}`} className="absolute right-1 top-1/2 flex size-6 -translate-y-1/2 items-center justify-center rounded text-ink-subtle opacity-0 hover:bg-border hover:text-ink focus-visible:opacity-100 group-hover/item:opacity-100 data-[state=open]:opacity-100">
            <MoreHorizontal className="size-4" />
          </button>
        </MenuTrigger>
        <MenuContent align="start" className="w-44">
          <MenuItem onSelect={() => setEditing(true)}><Pencil className="size-4 text-ink-muted" />Rename</MenuItem>
          <MenuItem onSelect={() => { void chat.remove(conv.id); if (window.location.pathname.endsWith(conv.id)) navigate('/') }}><Trash2 className="size-4 text-ink-muted" />Delete</MenuItem>
        </MenuContent>
      </Menu>
    </div>
  )
}

function EngineStatus() {
  const { state, status } = useEngine()
  const label = { unknown: 'Connecting…', online: status?.deterministic_only ? 'Online · no AI narration' : 'Research engine online', waking: 'Waking the research engine…', offline: 'Engine unreachable' }[state]
  const dot = { unknown: 'bg-ink-subtle', online: 'bg-tier-favorable', waking: 'bg-tier-uncertain animate-pulse', offline: 'bg-tier-unfavorable' }[state]
  return <p className="flex items-center gap-2 px-2.5 text-xs text-ink-muted" role="status"><span className={cn('size-2 rounded-full', dot)} />{label}</p>
}

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const conversations = useChat((s) => s.conversations)
  const ui = useUi()
  const navigate = useNavigate()
  const [dark, setDark] = useState(() => resolveTheme(getThemeMode()) === 'dark')
  const groups = groupByRecency(conversations)
  const go = (fn: () => void) => () => { fn(); onNavigate?.() }

  return (
    <div className="flex h-full w-full flex-col bg-sunken text-ink">
      <div className="flex items-center justify-between px-3 pb-2 pt-3.5">
        <Wordmark />
        <Button variant="ghost" size="icon-sm" aria-label="Hide sidebar" className="hidden md:inline-flex" onClick={() => ui.setSidebarCollapsed(true)}><PanelLeftClose /></Button>
      </div>
      <div className="space-y-1 px-3 pb-2">
        <Button variant="outline" className="w-full justify-start" onClick={go(() => navigate('/'))}><Plus /> New chat</Button>
        <NavLink to="/demo" onClick={onNavigate} className={({ isActive }) => cn('flex h-9 items-center gap-2 rounded-md px-2.5 text-sm transition-colors', isActive ? 'bg-border/70' : 'hover:bg-border/40')}>
          <Play className="size-4 text-ink-muted" /> Sample session <Badge tone="outline" className="ml-auto">Recorded</Badge>
        </NavLink>
        <button type="button" onClick={go(() => ui.openMatterDialog('matters'))} className="flex h-9 w-full items-center gap-2 rounded-md px-2.5 text-sm text-ink transition-colors hover:bg-border/40">
          <FolderOpen className="size-4 text-ink-muted" /> Matters
        </button>
      </div>
      <nav aria-label="Conversations" className="min-h-0 flex-1 overflow-y-auto px-3 pb-3 pt-2">
        {groups.length === 0 && <p className="px-2.5 pt-3 text-sm text-ink-subtle">Your conversations will appear here.</p>}
        {groups.map((g) => (
          <section key={g.label} className="mb-3">
            <h2 className="px-2.5 pb-1 text-2xs font-medium uppercase tracking-[0.08em] text-ink-subtle">{g.label}</h2>
            <div onClick={onNavigate} className="space-y-px">{g.items.map((c) => <Item key={c.id} conv={c} />)}</div>
          </section>
        ))}
      </nav>
      <div className="space-y-2 border-t border-border px-3 py-3">
        <EngineStatus />
        <div className="flex items-center justify-between">
          <Button variant="ghost" size="sm" onClick={go(() => ui.setSettingsOpen(true))}><Settings /> Settings</Button>
          <Button variant="ghost" size="icon-sm" aria-label={dark ? 'Switch to light theme' : 'Switch to dark theme'} onClick={() => { const next = dark ? 'light' : 'dark'; setThemeMode(next); setDark(!dark) }}>{dark ? <Sun /> : <Moon />}</Button>
        </div>
      </div>
    </div>
  )
}
