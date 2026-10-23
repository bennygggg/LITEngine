# LIT — frontend

The web client for the Legal Intelligence Terminal: a full-screen research chat for Indian case law. Ask in plain
language or pick a tool from the `+` menu; results appear inline as cards (case profile, precedents, argument map,
outcome estimate, scenarios, sourced answers) and open in a side panel for detail.

React 18, Vite, TypeScript, Tailwind on CSS-variable design tokens, Radix primitives, zustand, IndexedDB (`idb`),
Cytoscape (lazy). The server contract is in `../docs/PROTOCOL.md`; the system overview is in `../docs/ARCHITECTURE.md`.

## Develop

```bash
npm install
npm run dev          # http://localhost:3000 (expects the backend on :8000)
```

Run the backend from `../lit-backend` (`uvicorn main:app --reload`). With no `HUGGINGFACE_API_KEY` or with
`LLM_PROVIDER=none` everything works with deterministic routing and templated narration. `/demo` (the recorded sample
session) needs no backend at all.

## Checks

```bash
npm run typecheck && npm run lint && npm test     # fast
npm run verify                                    # + production build and the bundle budget (initial JS <= 170 kB gz)
npm run e2e                                       # Playwright: starts the backend (deterministic mode) and Vite itself
```

`npm run e2e` covers the chat flow, the `+` menu, upload and the matters list, the sample session, a 390 px layout, and
an axe accessibility audit (no serious or critical WCAG 2.1 AA violations) in light and dark. The first run needs
`npx playwright install chromium` and the backend's `.venv311` (see `../docs/RUNBOOK.md`).

## Types come from the backend

`src/api/schema.d.ts` is generated from `../lit-backend/openapi.json` and must not be edited by hand:

```bash
(cd ../lit-backend && .venv311/bin/python scripts/export_openapi.py)   # after changing models/agent_schemas.py
npm run gen:api
```

## Structure

```text
src/
  app/            App, AppShell, routes
  api/            client, agent (SSE + case cache), upload, generated schema.d.ts
  design/         tokens.css (colour, type, shadow), base.css, ui/ primitives
  features/
    chat/         reducer (one pure reduceEvent), runController, Composer, PlusMenu, messages
    cards/        one renderer per card type, skeletons, argument-map layout
    canvas/       side panel: map workbench, precedent reader, source viewer
    matters/      add-matter dialog, sample matters (fictional)
    demo/         sample-session player + the recording
    sidebar/ settings/ kit/
  lib/            sse transport, markdown, persistence (IndexedDB), zustand stores, format helpers
  test/fixtures/  real SSE streams used by unit tests
e2e/              Playwright specs
```

Re-skinning: colour, type and shadow decisions live in `src/design/tokens.css`; components use semantic tokens only.

## Configuration and deployment

`VITE_PUBLIC_API_BASE_URL` (tracked in `.env.production`) is the backend's `/api/v1` URL; local development defaults to
`http://localhost:8000/api/v1` and Settings can override it. `vercel.json` provides the SPA rewrite, the
Content-Security-Policy (its `connect-src` must name the backend origin; the inline theme script in `index.html` is
allowed by hash, so re-hash it if that script changes) and security headers. Deploy with `vercel --prod` after
`npm run verify`; see `../docs/RUNBOOK.md`.

Conversations and matters are stored in this browser (IndexedDB). Analysis sends the matter text to the configured
backend; nothing is stored on the server beyond a short-lived in-memory cache.
