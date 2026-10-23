import { createParser } from 'eventsource-parser'
import type { AgentEvent } from '@/types/agent'
import { AgentHttpError, ColdStartError, StallError } from './errors'

export interface StreamOptions {
  url: string
  body: unknown
  signal: AbortSignal
  /** Resume a run: the server replays events with seq greater than this. */
  lastEventId?: number
  /** Presume the connection dead after this long with no bytes (server pings every 10 s). */
  stallMs?: number
  headers?: Record<string, string>
  fetchImpl?: typeof fetch
}

/**
 * POST a chat request and yield the server's events as they arrive.
 *
 * Pre-stream failures are normal JSON responses (AgentHttpError); a response that is not an event stream at all is
 * what a sleeping Hugging Face Space returns (ColdStartError); silence beyond `stallMs` is a StallError.
 */
export async function* streamAgentEvents(opts: StreamOptions): AsyncGenerator<AgentEvent> {
  const { url, body, signal, lastEventId, stallMs = 25_000, headers = {}, fetchImpl = fetch } = opts
  if (signal.aborted) throw new DOMException('Aborted', 'AbortError') // an already-aborted signal never fires its listener
  const watchdog = new AbortController()
  let stalled = false
  let timer: ReturnType<typeof setTimeout> | undefined
  const arm = () => {
    clearTimeout(timer)
    timer = setTimeout(() => {
      stalled = true
      watchdog.abort()
    }, stallMs)
  }
  const onAbort = () => watchdog.abort()
  signal.addEventListener('abort', onAbort, { once: true })

  try {
    arm()
    let resp: Response
    try {
      resp = await fetchImpl(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'text/event-stream',
          ...(lastEventId != null ? { 'Last-Event-ID': String(lastEventId) } : {}),
          ...headers,
        },
        body: JSON.stringify(body),
        signal: watchdog.signal,
      })
    } catch (err) {
      if (stalled) throw new StallError()
      if ((err as Error).name === 'AbortError') throw err
      throw new ColdStartError() // network failure while the Space is booting looks like this
    }

    if (!resp.ok) {
      let payload: { code?: string; message?: string } = {}
      try {
        payload = await resp.json()
      } catch {
        /* HTML or empty body: an HF proxy page */
        if (resp.status >= 500 || resp.status === 404) throw new ColdStartError()
      }
      throw new AgentHttpError(resp.status, payload.code ?? 'http_error', payload.message ?? resp.statusText,
        Number(resp.headers.get('Retry-After')) || undefined)
    }
    if (!(resp.headers.get('content-type') ?? '').includes('text/event-stream') || !resp.body) throw new ColdStartError()

    const queue: AgentEvent[] = []
    const parser = createParser({
      onEvent(ev) {
        try {
          queue.push(JSON.parse(ev.data) as AgentEvent)
        } catch {
          /* a malformed frame is skipped, never fatal */
        }
      },
    })
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    try {
      for (;;) {
        let chunk: ReadableStreamReadResult<Uint8Array>
        try {
          chunk = await reader.read()
        } catch (err) {
          if (stalled) throw new StallError()
          throw err
        }
        if (chunk.done) break
        arm()
        parser.feed(decoder.decode(chunk.value, { stream: true }))
        while (queue.length) yield queue.shift()!
      }
      while (queue.length) yield queue.shift()!
    } finally {
      reader.cancel().catch(() => undefined)
    }
  } finally {
    clearTimeout(timer)
    signal.removeEventListener('abort', onAbort)
  }
}
