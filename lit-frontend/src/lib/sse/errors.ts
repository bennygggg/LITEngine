/** The stream could not start because the server (or an HF proxy page) is not ready — typically a sleeping Space. */
export class ColdStartError extends Error {
  constructor() {
    super('The research engine is waking up.')
    this.name = 'ColdStartError'
  }
}

/** No bytes for too long: the connection is presumed dead (pings arrive every 10 s on a healthy stream). */
export class StallError extends Error {
  constructor() {
    super('The connection went quiet.')
    this.name = 'StallError'
  }
}

/** A JSON error returned before the stream started (409 case_unknown, 429 busy, 426 client_outdated, …). */
export class AgentHttpError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public retryAfter?: number,
  ) {
    super(message)
    this.name = 'AgentHttpError'
  }
}
