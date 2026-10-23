import { lazy, Suspense } from 'react'
import { Outlet } from 'react-router-dom'
import { Dialog, DialogContent } from '@/design/ui/Dialog'
import { CanvasHost } from '@/features/canvas/CanvasHost'
import { Sidebar } from '@/features/sidebar/Sidebar'
import type { CaseRecord } from '@/lib/persistence/storage'
import { useUi } from '@/lib/store/ui'

const AddMatterDialog = lazy(() => import('@/features/matters/AddMatterDialog').then((m) => ({ default: m.AddMatterDialog })))
const SettingsDialog = lazy(() => import('@/features/settings/SettingsDialog').then((m) => ({ default: m.SettingsDialog })))

export default function AppShell() {
  const ui = useUi()
  return (
    <div className="flex h-dvh overflow-hidden bg-bg text-ink">
      {!ui.sidebarCollapsed && <aside className="hidden w-[264px] shrink-0 border-r border-border md:block" aria-label="Sidebar"><Sidebar /></aside>}
      <Dialog open={ui.mobileSidebarOpen} onOpenChange={ui.setMobileSidebarOpen}>
        <DialogContent title="Menu" className="left-0 top-0 h-dvh max-h-dvh w-72 max-w-[85vw] translate-x-0 translate-y-0 rounded-none border-y-0 border-l-0 md:hidden [&>header]:hidden">
          <Sidebar onNavigate={() => ui.setMobileSidebarOpen(false)} />
        </DialogContent>
      </Dialog>
      <main className="flex min-w-0 flex-1"><Outlet /></main>
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
