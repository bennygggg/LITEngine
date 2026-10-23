# Changelog

## 1.0.0 — chat workspace

The eight-tab interface is replaced by one full-screen chat. An orchestrator picks the analyses; results render as
cards inline.

### Added
- **Chat workspace.** Ask in plain language, or pick a tool from the `+` menu (Read the case, Find precedents, Map the
  argument, Assess the outcome, Explore scenarios, Ask about the case, Full case review). Add a matter by upload
  (`.pdf`, `.docx`, `.txt`), paste, or from the matters list. Light and dark themes; works on a phone.
- **Nine card types** for case profile, precedents, argument map, outcome estimate, scenario comparison, sourced
  answers, needs-input forms, document and errors; a side panel with the interactive argument map (Cytoscape) and a
  precedent / source reader that highlights the passage in context.
- **Streaming agent** (`POST /api/v1/agent/chat`, SSE): forced tools, a deterministic keyword router, and an LLM planner
  with a fallback chain and circuit breaker; resumable runs, cancel, 10 s keep-alives, cold-start handling.
  See `docs/PROTOCOL.md`.
- **Scenario engine** (`POST /api/v1/simulation/scenario`) that re-scores the real outcome model instead of applying
  hand-picked deltas.
- **Real precedent library**: 505 judgments (13,591 passages) served from a private dataset repo, verified by sha256;
  replaces the 3-case fixture index in production.
- **Case cache** (`PUT /api/v1/cases/{sha256}`): RAM-only, 20 matters, 2 hours.
- **Sample session** (`/demo`): a recorded run of the real system on a fictional matter, replayed through the same
  reducer as live runs; works offline. See `docs/DEMO.md`.
- Model card (`docs/MODEL_CARD.md`) and generated `model_card.json`, real `/api/v1/health/ready`, `scripts/smoke.py`.
- Quality gates: 119 backend tests, 44 frontend unit tests, 18 end-to-end and accessibility checks (WCAG 2.1 AA, both
  themes, 390 px), a bundle budget, OpenAPI drift test, `scripts/verify.sh`, and a pre-push hook.

### Changed
- **Honest presentation of the outcome estimate.** It is a base-rate-by-appeal-type indicator trained on 187
  judgments; it is shown rounded to 5 %, with the main driver named, for criminal appeals only, and the legacy
  heuristic is shown only as an "uncalibrated" comparison. Precedent similarity is shown as cosine with a bar, never
  as a percentage match.
- Appeal type and filing date are **never inferred**; the app asks, or uses the user's explicit words.
- Facts extraction: civil matters are no longer misclassified as criminal (a bare `FIR` pattern matched "first" and
  "firm").
- Logs carry lengths, hashes and counts only; no case text, queries or file names.
- Frontend rewritten in TypeScript on design tokens; initial JavaScript is ~128 kB gzipped.
- `vercel.json` adds a Content-Security-Policy and security headers; fonts are self-hosted.

### Removed
- The eight workspace pages, the browser-side scenario heuristic (`whatIfCalculator.js`), and the dependency that
  served them (`react-cytoscapejs`).

### Known limitations
- The outcome estimate is weak by construction (see the model card); embedder and chunking are frozen for 1.0.
- No accounts, access control or server-side history; conversations live in the browser.
- No OCR for scanned PDFs.
- The recorded sample session reflects the model and prompt at recording time; re-record after changes (`docs/DEMO.md`).

## 0.1.0
The tabbed workspace and per-feature endpoints (extraction, precedent search, argument graph, simulation, case chat).
