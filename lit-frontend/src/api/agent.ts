import type { CasePreview } from '@/types/agent'
import { ApiError, request, serverRoot } from './client'

export interface CaseUpload {
  text: string
  title?: string
  filename?: string
}

export async function sha256Hex(text: string): Promise<string> {
  const bytes = new TextEncoder().encode(text)
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('')
}

/** Register a matter's text in the server's short-lived cache; returns what was detected in it. */
export function putCase(sha: string, body: CaseUpload): Promise<CasePreview> {
  return request<CasePreview>(`/cases/${sha}`, { method: 'PUT', body: JSON.stringify(body), timeoutMs: 60_000 })
}

export function stopRun(runId: string): Promise<unknown> {
  // Best-effort companion to aborting the fetch; `keepalive` lets it survive a page unload.
  return request(`/agent/runs/${encodeURIComponent(runId)}`, { method: 'DELETE', keepalive: true, timeoutMs: 5_000 }).catch(() => null)
}

export interface AgentStatus {
  schema_version: number
  server_version: string
  agent_enabled: boolean
  llm: { provider: string; configured: boolean; planner_model: string | null; narration_model: string | null }
  deterministic_only: boolean
  library: { name: string; source: string; version: string; docs: number; chunks: number }
  outcome_model_loaded: boolean
  active_runs: number
}

export function getStatus(): Promise<AgentStatus> {
  return request<AgentStatus>('/agent/status', { timeoutMs: 8_000 })
}

/** Resolves when the server answers /health (used to ride out a cold start). */
export async function waitForHealthy(signal: AbortSignal, maxMs = 150_000, everyMs = 3_000): Promise<boolean> {
  const started = Date.now()
  while (Date.now() - started < maxMs && !signal.aborted) {
    try {
      const resp = await fetch(`${serverRoot()}/health`, { signal, cache: 'no-store' })
      if (resp.ok && (await resp.json())?.status === 'healthy') return true
    } catch {
      /* still waking */
    }
    await new Promise((r) => setTimeout(r, everyMs))
  }
  return false
}

export { ApiError }
