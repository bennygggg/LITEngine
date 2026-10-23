import { Download, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/design/ui/Button'
import { Dialog, DialogContent } from '@/design/ui/Dialog'
import { cn } from '@/lib/cn'
import { getStorage } from '@/lib/persistence/storage'
import { useUi } from '@/lib/store/ui'
import { getThemeMode, setThemeMode, type ThemeMode } from '@/lib/theme'

const SETTINGS_KEY = 'lit-settings'

function Row({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-6 border-b border-border py-4 last:border-0">
      <div className="min-w-0"><p className="text-sm font-medium">{title}</p>{hint && <p className="mt-0.5 text-xs text-ink-muted">{hint}</p>}</div>
      <div className="shrink-0">{children}</div>
    </div>
  )
}

export function SettingsDialog() {
  const ui = useUi()
  const [mode, setMode] = useState<ThemeMode>(getThemeMode())
  const [apiUrl, setApiUrl] = useState(() => { try { return (JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}') as { apiBaseUrl?: string }).apiBaseUrl ?? '' } catch { return '' } })
  const [confirmClear, setConfirmClear] = useState(false)

  const saveUrl = () => {
    try { localStorage.setItem(SETTINGS_KEY, JSON.stringify({ apiBaseUrl: apiUrl.trim() })) } catch { /* blocked */ }
  }
  const exportAll = async () => {
    const data = await (await getStorage()).exportAll()
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
    const a = Object.assign(document.createElement('a'), { href: url, download: `lit-export-${new Date().toISOString().slice(0, 10)}.json` })
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <Dialog open={ui.settingsOpen} onOpenChange={ui.setSettingsOpen}>
      <DialogContent title="Settings" description="Preferences are stored on this device.">
        <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-2">
          <Row title="Theme">
            <div className="flex gap-1 rounded-lg border border-border bg-sunken p-0.5" role="radiogroup" aria-label="Theme">
              {(['light', 'system', 'dark'] as const).map((m) => (
                <button key={m} type="button" role="radio" aria-checked={mode === m} onClick={() => { setMode(m); setThemeMode(m) }}
                  className={cn('rounded-md px-3 py-1 text-sm capitalize transition-colors', mode === m ? 'bg-surface shadow-raised' : 'text-ink-muted hover:text-ink')}>{m}</button>
              ))}
            </div>
          </Row>
          <Row title="AI narration" hint="Let the language model write the short reply after results. Off uses plain templated summaries and sends no text to any model provider.">
            <button type="button" role="switch" aria-checked={ui.aiNarration} aria-label="AI narration" onClick={() => ui.setAiNarration(!ui.aiNarration)}
              className={cn('relative h-6 w-10 rounded-full transition-colors', ui.aiNarration ? 'bg-ink' : 'bg-border-strong')}>
              <span className={cn('absolute top-0.5 size-5 rounded-full bg-bg transition-all', ui.aiNarration ? 'left-[1.15rem]' : 'left-0.5')} />
            </button>
          </Row>
          <Row title="Your data" hint="Matters and conversations live in this browser only. Export them, or remove everything.">
            <div className="flex flex-col items-end gap-2">
              <Button size="sm" variant="outline" onClick={() => void exportAll()}><Download /> Export JSON</Button>
              {confirmClear ? (
                <span className="flex items-center gap-2 text-sm">Delete everything?
                  <Button size="sm" variant="outline" onClick={async () => { await (await getStorage()).clearAll(); localStorage.removeItem('lit-ui'); window.location.assign('/') }}>Yes, delete</Button>
                  <Button size="sm" variant="ghost" onClick={() => setConfirmClear(false)}>Cancel</Button>
                </span>
              ) : <Button size="sm" variant="ghost" onClick={() => setConfirmClear(true)}><Trash2 /> Clear local data</Button>}
            </div>
          </Row>
          <details className="py-4">
            <summary className="cursor-pointer text-sm text-ink-muted">Advanced</summary>
            <label className="mt-3 block text-sm font-medium" htmlFor="api-url">API base URL</label>
            <p className="mt-0.5 text-xs text-ink-muted">Leave blank to use the default server. Changes apply after a reload.</p>
            <div className="mt-2 flex gap-2">
              <input id="api-url" value={apiUrl} onChange={(e) => setApiUrl(e.target.value)} placeholder="https://…/api/v1" className="h-9 min-w-0 flex-1 rounded-lg border border-border-strong bg-surface px-3 text-sm outline-none focus:border-ink" />
              <Button size="sm" variant="outline" onClick={saveUrl}>Save</Button>
            </div>
          </details>
        </div>
        <footer className="border-t border-border px-6 py-3 text-xs text-ink-subtle">LIT {String((import.meta.env as Record<string, string | undefined>).VITE_APP_VERSION ?? '1.0.0-dev')} · An indicative research tool, not legal advice.</footer>
      </DialogContent>
    </Dialog>
  )
}
