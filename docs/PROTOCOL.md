# Chat protocol (schema v1)

The wire contract between the web client and `POST /api/v1/agent/chat`. The source of truth is
`lit-backend/models/agent_schemas.py`; `lit-backend/openapi.json` is generated from it and
`lit-frontend/src/api/schema.d.ts` is generated from that (`npm run gen:api`). A pytest fails if the committed
OpenAPI file drifts from the models, so the three cannot disagree silently.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `PUT` | `/api/v1/cases/{sha256}` | Register a matter's text in the server cache (RAM only, LRU 20, 2 h). Returns what was detected and the extraction quality. The path hash must equal the sha256 of the body text. |
| `HEAD` | `/api/v1/cases/{sha256}` | 200 if the server still holds the case, else 404. |
| `POST` | `/api/v1/agent/chat` | Run one assistant turn; the response is a `text/event-stream`. |
| `DELETE` | `/api/v1/agent/runs/{run_id}` | Stop a run (companion to aborting the fetch). |
| `GET` | `/api/v1/agent/status` | LLM on/off, library and model state. |
| `POST` | `/api/v1/simulation/scenario` | The scenario engine without the chat (same engine the `run_scenario` tool uses). |
| `GET` | `/api/v1/health/ready` | Real readiness: index, embedder, Juris, LLM configured (boolean only). |

## Request

```jsonc
{
  "client": { "version": "1.0.0", "schema_version": 1 },
  "conversation_id": "…", "run_id": "…",      // run_id is the idempotency key (see Resume)
  "messages": [ { "role": "user|assistant", "text": "…" } ],   // at most 12 recent text-only turns
  "user_message": {
    "text": "…",
    "forced_tool": { "name": "build_argument_map", "args": {} } | null,   // set by the + menu
    "input_response": { "card_id": "…", "values": { "appellant_type": "accused", "filing_date": "2024-06-14" } } | null
  },
  "case": { "ref": "<sha256>", "title": "…", "inputs": { "appellant_type": null, "filing_date": null } } | null,
  "options": { "mode": "auto|deterministic", "narrate": "llm|template|none" }
}
```

Tools: `extract_case_facts`, `search_precedents`, `build_argument_map`, `assess_outcome`, `run_scenario`, `ask_case`,
plus the macro `full_review` (facts → precedents → map → outcome).

## Events

Every event carries `{ v: 1, seq, t }` — `seq` is strictly increasing within a run, `t` is milliseconds since the
request arrived. The SSE event name equals the JSON `event` field, so a recorded stream is self-describing. Unknown
events are ignored by the client reducer, which is what lets the server add event types without breaking old clients.

| Event | Meaning |
|---|---|
| `message_start` | First event. Run/message ids, `mode` (`llm`, `forced` or `deterministic`), model, prompt version, whether the server knows the case. |
| `text_delta` | A chunk of assistant text. A new `part_id` starts a new text part. |
| `step` | A unit of work: `start` → optional `progress` → `end` (`ok`, `cached`, `skipped`, `error`, with `duration_ms` and a one-line `summary`). `origin` is `llm`, `forced` or `dependency`; `produces_card` on `start` lets the UI draw a skeleton in the card's final shape. |
| `card` | A typed result: `case_profile`, `precedents`, `argument_map`, `outcome`, `scenario`, `sources`, `document`, `error`. |
| `needs_input` | A form the user must complete (appellant type, filing date). The run then ends with `done{status:"awaiting_input"}`. |
| `artifact_update` | A cached artifact was produced or reused; `implicit: true` for dependency-only work that shows no card. |
| `meta` | Conversation title, follow-up suggestions, and the effective `case_inputs` the client should persist. |
| `ping` | Keep-alive, every 10 s. Pings keep flowing while a worker thread is busy. |
| `error` | `scope` is `run`, `step` or `llm`; `retryable` says whether a retry makes sense. |
| `done` | Last event: `complete`, `awaiting_input`, `cancelled` or `error`, with token usage, timings (`ttft_ms`, `first_card_ms`, `total_ms`) and warnings (for example, a citation the model used that no tool issued). |

### Invariants (enforced by `assert_stream_invariants` in the tests)

`message_start` is first and `done` is last; `seq` is monotonic; every `step` start has an end; a card follows its
step's start; nothing follows `done`.

## Before the stream: plain JSON errors

| Status | Code | Meaning / client behaviour |
|---|---|---|
| 409 | `case_unknown` | The server restarted or evicted the case. The client re-`PUT`s it and retries, silently. |
| 426 | `client_outdated` | The client's `schema_version` is below the server's minimum. Ask the user to refresh. |
| 429 | `busy` | `AGENT_MAX_CONCURRENT` runs are active (stability for the 2-vCPU Space, not access control). `Retry-After: 5`. |
| 503 | `agent_disabled` | `AGENT_ENABLED=false`. |

## Streaming behaviour

- Headers: `Cache-Control: no-store, no-transform`, `X-Accel-Buffering: no`, `X-Run-Id`. The first bytes are padded
  (~2 KB) so buffering proxies flush immediately. Verified end to end through the Hugging Face proxy on the staging
  Space (150 s stream, 80 s of silence between events).
- **Keep-alive and stall detection.** The server pings every `AGENT_PING_S` (10 s); the client treats 25 s without
  any bytes as a dead connection and resumes.
- **Cold start.** A sleeping Space answers with HTML, not `text/event-stream`. The client shows "Waking the research
  engine", polls `/health` every 3 s (up to 150 s), then re-sends the same `run_id`.
- **Stop.** The client aborts the fetch and calls `DELETE /agent/runs/{id}`. Server-side, a run with no reader is
  cancelled after `AGENT_ORPHAN_CANCEL_S` (15 s); a quick reconnect cancels the timer instead.
- **Resume.** Each run keeps a bounded event log (`RunLog`). Re-POSTing an existing `run_id` with `Last-Event-ID: n`
  replays events after `n` and then tails the live run. An unknown `run_id` simply starts a new run; tools are
  idempotent and cached, so a restart is harmless.

## The never-infer rule

`appellant_type` and `filing_date` are taken only from (a) the needs-input form, (b) an explicit statement in the
user's own words (`parse_explicit_appellant`), or (c) a UI-forced call that carries them. Anything the model puts in
tool arguments is dropped unless one of those holds, and the run instead emits a `needs_input` card. This is enforced
in code (`Tools.accept_inputs`), not by prompting, because appeal type is the strongest factor in Juris.

## Versioning

`schema_version` is bumped only for breaking changes. Additive changes (new optional fields, new event or card
types) do not bump it: the client ignores what it does not know. `client.schema_version` below the server's
`MIN_CLIENT_SCHEMA` gets a 426.
