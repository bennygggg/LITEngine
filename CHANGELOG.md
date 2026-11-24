# Changelog

## Unreleased — Juris

### Changed
- **The outcome model is now called Juris, everywhere.** Display name, API types (`JurisResult`, `JurisContribution`, `JurisComparison`), the comparison keys (`juris` / `heuristic`, field `comparison`), `JURIS_PRIMARY` and `JURIS_MODEL_PATH` (were `OUTCOME_MODEL_PRIMARY` / `OUTCOME_MODEL_PATH`), the health key `juris_loaded` (was `outcome_model_loaded`), the module `services/juris.py`, the provenance engine `juris`, and the artifact `data/juris/model/juris.joblib`. Tool names, card types and routes are unchanged. The Docker and git whitelists were updated with the move, and a new test fails if they ever stop matching the artifact path.
- **The black book no longer claims Juris was trained on 1,505 cases.** That figure was wrong: the model served so far is the 187-judgment prototype. Every Juris number in the book now comes from the retrain's reports, and the book was rewritten around the retrained model.

### Added
- **Juris is retrained at scale: 107,847 Indian High Court criminal-appeal judgments (2008-2026), not 187.** It reads the pre-reasoning part of a case (facts, trial-court findings, grounds and submissions) and the appeal type the user states, and never the appellate court's own reasoning or order. On 32,573 later cases (2023-26) it had never seen, read exactly once, it is right **75.3 %** of the time (95 % CI 74.8-75.8; AUC 0.795), against 65.6 % for always guessing the majority outcome and 73.7 % (AUC 0.643) for the appeal type alone. The full results, the leakage ladder (order stripped 82.7 %, full text 90.7 %: not predictions) and the limits are in `docs/MODEL_CARD.md`, generated from the reports.
- **A leakage-controlled pipeline, `lit-backend/scripts/juris/`** (README there): index the open High Court archive from metadata, fetch final orders, gate on quality, procedural endings, interim orders and label disagreement, remove near-duplicates, mask names and proper nouns, cut at the court's reasoning (one function shared by training and serving), split by time, choose settings on 2022, read 2023+ once, calibrate, export. A guard refuses a second look at the test split.
- `case_text` on `POST /simulation/predict` and `/simulation/scenario` (additive); `JurisResult` reports `words_read` and `input_basis`.

### Changed (behaviour)
- **Scenarios now edit what Juris reads.** The real levers are the appeal type and the cited sections; the earlier five-score levers (weak claims, extra supporting facts, excluded precedents, court level) are reported as rejected, with the reason, never silently ignored.
- **The outcome card says what Juris reads and does not read**, prints held-out accuracy against the majority baseline instead of cross-validation on 187 cases, and adds a base-rate caveat for appeals by the State (Juris cannot rank them beyond the base rate: AUC 0.50 on 2,377 test cases). `ModelFacts` gained `eval_accuracy`, `eval_auc`, `n_eval`, `eval_period` and `reads` (`cv_accuracy` is gone). `PROMPT_VERSION` is bumped; the recorded sample session predates it and should be re-recorded (`docs/DEMO.md`).
- `scikit-learn` is still the only new serving dependency; the serving image needs no pandas. The artifact is 4.4 MB and loads in under a second; because Hugging Face Spaces reject binary files in git it is published to the private dataset repo (`juris/v1/`) and downloaded at start, installed only if its sha256 matches the committed `model_card.json` (`scripts/juris/publish_artifact.py`).

## 1.0.1 — polish

### Fixed
- **The whole page no longer scrolls.** Screen-reader-only text deep inside a long conversation stretched the document, so scrolling a conversation to its end slid the entire interface (sidebar included) up the window. The shell is now the containing block for everything inside it and the document itself cannot scroll.
- **The argument map opens full screen**, with a clear way back to the side panel (button and Esc). The toolbar icon that looked like "full screen" was really "fit to view"; it now has its own icon and label. While the map covers the window, the page behind it is inert.
- **Assistant avatar alignment.** The avatar now sits on the same centre line as the first row of the reply (the step row had a 12 px top margin; the first paragraph had its own).
- **One-liners are one line.** "One liner please", "in one sentence", "tl;dr", "briefly" give exactly one sentence, answer first, with no caveat or next step, enforced on the server even if the model rambles. When the question is about the document, the sources are tucked under the answer behind a "Sources" row instead of leading it.
- **Wrong-party attribution.** Document passages were cut mid-sentence, losing their subject, so the model could credit a defence claim (the alibi, false implication) to the prosecution. Passages now start at sentence starts and the grounding rules say to attribute each claim to the party that made it. Measured on the live model: 15 of 15 runs correct, from 0 of 6 before.
- Request filler ("one liner please") is no longer part of the document search, and the no-AI one-liner is an honest "Closest passage" instead of a sentence fragment.

### Changed
- Prompt version 2026-10-24.1. The evaluation script gains three one-liner cases and an attribution check (23 prompts).

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
