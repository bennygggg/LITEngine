import { create } from 'zustand'
import { getStatus, waitForHealthy, type AgentStatus } from '@/api/agent'

type EngineState = 'unknown' | 'online' | 'waking' | 'offline'

interface EngineStore {
  state: EngineState
  status: AgentStatus | null
  /** Pings the server (which also wakes a sleeping Space) and, if it is not answering, rides out the cold start. */
  check: () => Promise<void>
  setWaking: () => void
  setOnline: () => void
}

let polling: AbortController | null = null

export const useEngine = create<EngineStore>((set, get) => ({
  state: 'unknown',
  status: null,

  async check() {
    try {
      set({ status: await getStatus(), state: 'online' })
    } catch {
      set({ state: 'waking' })
      polling?.abort()
      polling = new AbortController()
      const ok = await waitForHealthy(polling.signal)
      if (ok) {
        try {
          set({ status: await getStatus(), state: 'online' })
        } catch {
          set({ state: 'offline' })
        }
      } else if (!polling.signal.aborted) {
        set({ state: 'offline' })
      }
    }
  },
  setWaking: () => set({ state: 'waking' }),
  setOnline: () => {
    if (get().state !== 'online') set({ state: 'online' })
  },
}))
