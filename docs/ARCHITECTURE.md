# Architecture (v1.0.0)

LIT is a full-screen legal research chat. An orchestrator decides which of five analyses to run (case facts,
precedents, argument map, outcome estimate, scenarios) or answers a question about the uploaded document, and the
results render as typed cards inline in the conversation.

```
 Browser (Vercel, React + Vite + TypeScript)             Hugging Face Docker Space (FastAPI, 1 worker, CPU)
 ┌──────────────────────────────────────────┐            ┌─────────────────────────────────────────────────┐
 │ Composer + "+" menu ─┐                   │  PUT case  │ /cases/{sha}  → workspace cache (RAM, LRU 20)   │
 │ Sidebar / Matters    │ runController     │ ─────────▶ │                                                 │
 │ Cards / Canvas       │  fetch + SSE      │  POST chat │ /agent/chat → Orchestrator                      │
 │ reduceEvent (pure) ◀─┘  stall watchdog   │ ◀───────── │   Tier 0 forced tool (the "+" menu)             │
 │ IndexedDB (conversations, matters)       │  SSE events│   Tier 1 deterministic router (keywords)        │
 │ /demo replay ── same reducer ────────────│            │   Tier 2 LLM planner (HF router, native tools)  │
 └──────────────────────────────────────────┘            │   resolver → tools → cards, narration           │
                                                         │ tools run in-process on the existing services:  │
              HF router ◀── planner + narration only ──  │   extractor · embedder+FAISS · graph_builder ·  │
        (gpt-oss-120b on Cerebras,                       │   Juris · scenario engine · doc index           │
         Qwen2.5-72B fallback)                           └─────────────────────────────────────────────────┘
```

## Backend (`lit-backend`)

| Area | Where | Notes |
|---|---|---|
| Wire contract | `models/agent_schemas.py` | Pydantic v2 discriminated unions: requests, 9 card types, 10 events. OpenAPI carrier route → generated TS types. |
| Run lifecycle | `services/agent/events.py` | `EventEmitter`, `RunLog` (bounded replay buffer), registry. SSE pings, orphan cancel, `Last-Event-ID` resume. |
| Orchestration | `services/agent/orchestrator.py`, `routing.py`, `llm_flow.py` | Tier 0/1/2 as above. A forced tool never calls the LLM to decide. The LLM can fail without failing the run: templated narration takes over. |
| Tools | `services/agent/tools.py` | `Tools` binds a `RunContext`; each tool emits `step` events and, when it has something to show, a card. A dependency resolver expands prerequisites, de-duplicates by artifact key and single-flights concurrent work. |
| Cards | `services/agent/cards.py` | Builders from engine results to card payloads. Rounding (5 %), centred contributions, honesty copy. |
| Workspace | `services/agent/workspace.py`, `doc_index.py` | Content-addressed case cache and artifact cache. The document index chunks ~180 words (inside MiniLM's 256-token window) with character offsets for the source viewer. |
| LLM runtime | `services/agent/llm/`, `llm_runtime.py`, `sanitize.py` | OpenAI-compatible client, fake and null clients, fallback chain, circuit breaker (3 failures → 60 s), daily token cap, a stream sanitiser that drops citation handles no tool issued. |
| Narration | `prompts.py`, `narration.py` | Versioned system prompt (`PROMPT_VERSION`), per-card narration hints (≤ 80 words, three parts), templated fallback in the same voice. |
| Engines | `services/{extractor,embedder,graph_builder,juris,juris_text,juris_features,outcome_pipeline,scenario}.py` | The pre-existing pipeline, now called in-process. Blocking work runs in `asyncio.to_thread`. |
| Library | `services/retrieval/artifact.py` | Verified loader (sha256 per file) for the precedent artifact: from a local directory or a private HF dataset repo; falls back to the 3-case fixture index and says so in `/health/ready`. |

### Design decisions worth knowing

- **Hybrid routing instead of "LLM decides everything".** Explicit picks and obvious intents are fast, free and
  deterministic; the model only plans ambiguous or multi-step asks. In the Phase 0 probe the fast model missed four of
  twenty routing prompts, every one of them a pattern the deterministic router handles.
- **The model cannot forge a card.** Cards only ever come from server tool events. The LLM writes prose around them
  and can cite only the `[P#]` / `[S#]` handles the tools issued; anything else is stripped as it streams.
- **Untrusted text.** Uploaded case text is data. Excerpts passed to the model are wrapped and escaped, tools are
  read-only, tool arguments are validated, and the client renders markdown with no raw HTML and no images.
- **Soft-stateful server.** The cache is recomputable from the client's copy of the text (a restart gives a 409, the
  client re-`PUT`s and retries). Conversations and matters live in the browser's IndexedDB, not on the server.
- **Embedder and chunking are frozen for 1.0.** The precedent library and its search depend on them. Juris itself no longer reads
  precedent similarity: it reads the pre-reasoning case text and who is appealing. See `MODEL_CARD.md`.
- **Privacy in logs.** Logs carry lengths, hashes and counts, never case text, queries or file names (a log-capture
  test enforces it).

## Frontend (`lit-frontend/src`)

| Area | Where |
|---|---|
| Design tokens | `design/tokens.css` (RGB-triplet CSS variables), `tailwind.config.ts`, `design/ui/*`. Re-skinning is a change to the tokens plus a few component variants. |
| Chat engine | `features/chat/`: `reducer.ts` (one pure `reduceEvent`, shared by live runs and the demo), `runController.ts` (cold start, 409 re-PUT, 429 backoff, stall resume, stop), `Composer`, `PlusMenu`. |
| Cards | `features/cards/`: nine renderers plus skeletons; the argument-map thumbnail is a static SVG from a deterministic lane layout (`layout.ts`). |
| Canvas | `features/canvas/`: resizable side panel (a sheet on phones); Cytoscape map workbench and precedent reader, loaded lazily. |
| Matters | `features/matters/`: upload, paste, and the matters list (fictional samples plus the user's own, stored locally). |
| Sample session | `features/demo/`: `replay.ts` (pure scheduler), `useDemoPlayer.ts`, the recording JSON. See `DEMO.md`. |
| State | zustand stores (`lib/store`), IndexedDB persistence with an in-memory fallback (`lib/persistence`). |
| Types | `api/schema.d.ts` generated from the backend OpenAPI; never edited by hand. |

Initial JavaScript is about 128 kB gzipped (budget 170 kB, enforced by `npm run check:bundle`); the markdown engine,
Cytoscape, dialogs, the demo and the sample texts load on demand.

## Quality gates

`scripts/verify.sh` runs backend tests (Python 3.11 venv with production pins), the OpenAPI drift check, and the
frontend typecheck, lint, unit tests, build and bundle budget; `.githooks/pre-push` runs the fast subset. End-to-end
and accessibility checks (`npm run e2e`) run the real app against the real backend in deterministic mode and cover the
chat flow, the `+` menu, uploads, the sample session, 390 px layout and WCAG 2.1 AA in both themes.
