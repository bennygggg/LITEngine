import { lazy, Suspense } from 'react'
import { Outlet } from 'react-router-dom'
import { Dialog, DialogContent } from '@/design/ui/Dialog'
import { CanvasHost } from '@/features/canvas/CanvasHost'
import { useCanvasFull } from '@/features/canvas/useCanvasFull'
import { Sidebar } from '@/features/sidebar/Sidebar'
import type { CaseRecord } from '@/lib/persistence/storage'
import { useUi } from '@/lib/store/ui'

const AddMatterDialog = lazy(() => import('@/features/matters/AddMatterDialog').then((m) => ({ default: m.AddMatterDialog })))
const SettingsDialog = lazy(() => import('@/features/settings/SettingsDialog').then((m) => ({ default: m.SettingsDialog })))

export default function AppShell() {
  const ui = useUi()
  // While the map is full screen it covers the app, so what is behind it must not be reachable by keyboard or screen reader.
  const covered = useCanvasFull()
  const inert = covered ? ({ inert: '' } as Record<string, string>) : {}
  return (
    // `relative` makes this the containing block for every absolutely positioned descendant (including screen-reader-only
    // text deep inside long conversations), so none of them can stretch the document and make the whole page scroll.
    <div className="relative flex h-dvh overflow-hidden bg-bg text-ink">
      <div className="contents" {...inert}>
      {!ui.sidebarCollapsed && <aside className="hidden w-[264px] shrink-0 border-r border-border md:block" aria-label="Sidebar"><Sidebar /></aside>}
      <Dialog open={ui.mobileSidebarOpen} onOpenChange={ui.setMobileSidebarOpen}>
        <DialogContent title="Menu" className="left-0 top-0 h-dvh max-h-dvh w-72 max-w-[85vw] translate-x-0 translate-y-0 rounded-none border-y-0 border-l-0 md:hidden [&>header]:hidden">
          <Sidebar onNavigate={() => ui.setMobileSidebarOpen(false)} />
        </DialogContent>
      </Dialog>
      <main className="flex min-w-0 flex-1"><Outlet /></main>
      </div>
      <CanvasHost />
      <Suspense fallback={null}>
        {ui.matterDialog !== null && (
          <AddMatterDialog
            open onOpenChange={(o) => !o && ui.closeMatterDialog()} defaultTab={ui.matterDialog}
            onSelect={(rec: CaseRecord) => window.dispatchEvent(new CustomEvent('lit:matter-selected', { detail: rec }))}
          />
        )}
        {ui.settingsOpen && <SettingsDialog />}
      </Suspense>
    </div>
  )
}
