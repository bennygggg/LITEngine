# Phase 0 report — foundations and de-risking

Branch `feat/v1.0.0-chat`. Plan: `~/.claude/plans/okay-now-all-this-nifty-mountain.md`.

## 1. LLM probe (Hugging Face router, your key, synthetic prompts only)

`lit-backend/scripts/probe_llm.py`; raw data in `lit-backend/.cache/probe_report.json` (gitignored).
20 prompts × tool choice, argument validity, "never infer" rule, multi-turn tool round-trip, JSON-schema planning, streaming.

| Model (provider that answered) | Tool choice | Args valid | Never-infer breaches | Round-trip | JSON plan | TTFT (median) | Throughput | Tool-decision latency (median) |
|---|---|---|---|---|---|---|---|---|
| `openai/gpt-oss-120b` (**Cerebras**) | 16/20 | 14/15 | 1 | 14/15 | 7/8 | **385 ms** | **~2,450 tok/s** | **424 ms** |
| `Qwen/Qwen2.5-72B-Instruct` (DeepInfra) | **20/20** | 15/15 | **0** | 15/15 | 8/8 | 790 ms | 14–43 tok/s | 2.4 s (quick run) – 8.5 s (3-way concurrent) |
| `meta-llama/Llama-3.3-70B-Instruct` (Scaleway) *(8-prompt run)* | 8/8 | 5/7 | 0 | **2/7** | 5/8 | 497 ms | 90 tok/s | 0.9 s |
| `meta-llama/Llama-3.1-8B-Instruct` (DeepInfra) *(8-prompt run)* | 4/8 | 7/7 | 1 | 4/7 | no `json_schema` | 558 ms | 28 tok/s | 1.3 s |

**Findings**
- Native tool-calling **works** through the router on the two leading models; multi-turn tool round-trips work (the failure mode reported on the HF forum did not reproduce on them). Llama-3.3 fails the round-trip (repeats the tool call); Llama-3.1-8B (what case chat uses today) is not reliable enough to route.
- `gpt-oss-120b` on Cerebras is ~50–170× faster than Qwen but misses 4/20 routing prompts: "Who are the parties…" (→ ask_case), "What if the State were the appellant…" (→ assess_outcome), "What if we got an independent witness…" (→ ask_case), "Compare outcomes if the State appeals versus…" (→ extract_case_facts), plus one **never-infer breach** ("Estimate the chances of success" invented `appellant_type`/`filing_date`).
- Every one of those misses is a category the deterministic Tier-1 router handles by keyword ("what if", "compare", "who are the parties"), and the never-infer rule is **enforced in code** (the server drops `appellant_type`/`filing_date` unless the user's own words state them and raises the needs-input card instead), so it does not depend on the model behaving.
- The first JSON-plan failures on `gpt-oss-120b` were my schema (strict mode rejects free-form objects); fixed (args travel as a JSON string) and it now passes 7/8.

**Recommendation (for your OK)**
- Planner **and** narrator: `openai/gpt-oss-120b:cerebras` (pin the provider via the router's `model:provider` form; `reasoning_effort: low`). Sub-second routing, answers start streaming in under half a second.
- Automatic fallback chain on error/refusal/timeout: `Qwen/Qwen2.5-72B-Instruct` (most accurate, slower), then deterministic mode.
- Tier-2 mode = native `tools` (json_schema planner kept as a second fallback).

**Data handling (providers' own statements; please skim before real client matters go through)**
- Hugging Face routing: [states](https://huggingface.co/docs/inference-providers/security) it does not use data for training and does not store request bodies/responses when routing (debug logs ≤ 30 days without user data). Each routed provider's own policy governs what they do.
- Cerebras: its [privacy policy](https://www.cerebras.ai/privacy-policy) says inputs/outputs for inference are not retained and logs are deleted when no longer needed. I could not confirm a standalone "no training" clause from a primary source, so treat that as likely-but-unconfirmed; an enterprise agreement would settle it.
- DeepInfra (the fallback) — policy not yet reviewed by me.
- Until you are comfortable with this for real client matters, `LLM_PROVIDER=none` gives the full product with templated narration (no text leaves the Space).

## 2. Precedent library

`lit-backend/scripts/build_precedent_artifacts.py` → `data/precedent_artifacts/v1/` (gitignored):
`vectors.npy` 20.9 MB · `meta.jsonl` 41.5 MB · `manifest.json` (sha256 per file, embedder/chunker identity, score transform).
**Equivalence verified:** vectors byte-identical to the legacy JSON path; top-10 ids and distances identical across 8 MiniLM queries. 13,591 chunks / 505 judgments (501 dated, 198 undated chunks).
Sample query ("§302 + delayed FIR + eyewitness…") now returns real criminal-appeal judgments (Karnataka HC 2022, Gujarat HC 2026, Chhattisgarh HC 2026, Delhi District Court 2018) instead of the three constitutional cases the Space ships today.
macOS note: faiss + torch in one process need `OMP_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false KMP_DUPLICATE_LIB_OK=TRUE` locally (`scripts/verify.sh` sets them); the Linux Space is unaffected.

## 3. Contract and tooling (done)
- `lit-backend/models/agent_schemas.py`: frozen wire contract v1 — requests, 9 card types, 10 SSE events (`ChatTurn.role` validated).
- `lit-backend/openapi.json` + `lit-frontend/src/api/schema.d.ts` generated from it (`npm run gen:api`); drift test in pytest.
- Frontend: TypeScript, Tailwind on RGB-token variables, light/dark, self-hosted Inter + Newsreader, primitives (Button, Badge, Skeleton, Kbd, CardShell), design-kit page at `/`, Vitest + Playwright installed.
- Pinned test environment (Python 3.11.15 + production pins) at `lit-backend/.venv311`; `scripts/verify.sh` + `.githooks/pre-push` (enabled).
- Hygiene: 16 tracked `.pyc` files untracked; `requirements-dev.txt`, `pytest.ini`.
- State: backend 13 tests pass; frontend typecheck, lint (0 errors), 3 tests, production build pass. Initial JS (no Cytoscape yet) 43.6 kB + 159 kB vendor, gzip 13.7 + 51.8 kB.

## 4. Not done yet — each needs your OK because it touches something outside this laptop
1. **Private HF dataset repo** to host the precedent artifact (create + upload 62 MB; the Space downloads it at start).
2. **SSE-through-HF-proxy spike**: a 2-minute test stream with pings from a Vercel origin. Needs a throwaway endpoint on a Space — either a new staging Space (`lit-backend-staging`, free CPU) or briefly on the live one. I recommend the staging Space.
3. Confirm the model choice above (and whether DeepInfra as fallback is acceptable).
