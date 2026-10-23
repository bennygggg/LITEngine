import { create } from 'zustand'

const KEY = 'lit-ui'

interface Persisted {
  sidebarCollapsed: boolean
  canvasWidth: number
  aiNarration: boolean
}

function read(): Persisted {
  try {
    return { sidebarCollapsed: false, canvasWidth: 620, aiNarration: true, ...(JSON.parse(localStorage.getItem(KEY) || '{}') as Partial<Persisted>) }
  } catch {
    return { sidebarCollapsed: false, canvasWidth: 620, aiNarration: true }
  }
}

function write(p: Persisted): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(p))
  } catch {
    /* storage blocked: preferences last for this session only */
  }
}

export interface CanvasTarget {
  cardId: string
  /** Which view of the card to open (e.g. a specific precedent or source), if it has several. */
  focus?: string
}

interface UiState extends Persisted {
  mobileSidebarOpen: boolean
  canvas: CanvasTarget | null
  /** null = the card type's default (the argument map opens full screen); true/false once the user chooses */
  canvasExpanded: boolean | null
  matterDialog: 'upload' | 'paste' | 'matters' | null
  settingsOpen: boolean
  setSidebarCollapsed: (v: boolean) => void
  setMobileSidebarOpen: (v: boolean) => void
  setCanvasWidth: (w: number) => void
  setAiNarration: (v: boolean) => void
  openCanvas: (t: CanvasTarget) => void
  closeCanvas: () => void
  setCanvasExpanded: (v: boolean) => void
  openMatterDialog: (tab: 'upload' | 'paste' | 'matters') => void
  closeMatterDialog: () => void
  setSettingsOpen: (v: boolean) => void
}

export const useUi = create<UiState>((set, get) => {
  const persist = () => {
    const { sidebarCollapsed, canvasWidth, aiNarration } = get()
    write({ sidebarCollapsed, canvasWidth, aiNarration })
  }
  return {
    ...read(),
    mobileSidebarOpen: false,
    canvas: null,
    canvasExpanded: null,
    matterDialog: null,
    settingsOpen: false,
    setSidebarCollapsed: (v) => { set({ sidebarCollapsed: v }); persist() },
    setMobileSidebarOpen: (v) => set({ mobileSidebarOpen: v }),
    setCanvasWidth: (w) => { set({ canvasWidth: Math.min(720, Math.max(420, w)) }); persist() },
    setAiNarration: (v) => { set({ aiNarration: v }); persist() },
    openCanvas: (t) => set((s) => ({ canvas: t, canvasExpanded: s.canvas?.cardId === t.cardId ? s.canvasExpanded : null })),
    closeCanvas: () => set({ canvas: null, canvasExpanded: null }),
    setCanvasExpanded: (v) => set({ canvasExpanded: v }),
    openMatterDialog: (tab) => set({ matterDialog: tab }),
    closeMatterDialog: () => set({ matterDialog: null }),
    setSettingsOpen: (v) => set({ settingsOpen: v }),
  }
})
