/** Minimal typed REST client. (The chat stream has its own transport in lib/sse.) */

const ENV = import.meta.env as Record<string, string | undefined>
const DEFAULT_BASE = ENV.VITE_PUBLIC_API_BASE_URL || ENV.VITE_API_BASE_URL || '/api/v1'
const SETTINGS_KEY = 'lit-settings'

/** The API base URL, with an advanced override stored by the settings dialog. */
export function apiBase(): string {
  try {
    const stored = JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}') as { apiBaseUrl?: string }
    const configured = stored.apiBaseUrl?.trim()
    return configured ? configured.replace(/\/$/, '') : DEFAULT_BASE
  } catch {
    return DEFAULT_BASE
  }
}

/** The server root (without /api/v1) — where /health lives. */
export function serverRoot(): string {
  return apiBase().replace(/\/api\/v1$/, '')
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code?: string,
    public retryAfter?: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export async function request<T>(path: string, init: RequestInit & { timeoutMs?: number } = {}): Promise<T> {
  const { timeoutMs = 30_000, ...rest } = init
  const url = path.startsWith('http') ? path : `${apiBase()}${path}`
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  const headers = new Headers(rest.headers)
  if (rest.body && !(rest.body instanceof FormData) && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  let resp: Response
  try {
    resp = await fetch(url, { ...rest, headers, signal: rest.signal ?? controller.signal })
  } catch (err) {
    if ((err as Error).name === 'AbortError') throw new ApiError('The request timed out.', 0, 'timeout')
    throw new ApiError((err as Error).message || 'Network error', 0, 'network')
  } finally {
    clearTimeout(timer)
  }
  if (!resp.ok) {
    let body: { code?: string; message?: string; detail?: unknown } = {}
    try {
      body = await resp.json()
    } catch {
      /* not JSON */
    }
    const detail = typeof body.detail === 'string' ? body.detail : undefined
    throw new ApiError(body.message || detail || resp.statusText || `Request failed (${resp.status})`, resp.status, body.code,
      Number(resp.headers.get('Retry-After')) || undefined)
  }
  return resp.status === 204 ? (null as T) : ((await resp.json()) as T)
}
