# Runbook

GitHub is suspended, so there is no CI and no automatic deploy. Everything below is run by hand from a checkout.

## Before any release

```bash
scripts/verify.sh                 # backend tests (3.11 pinned venv) + OpenAPI drift + frontend typecheck/lint/tests/build
cd lit-frontend && npm run verify # includes the bundle budget (initial JS <= 170 kB gzipped)
cd lit-frontend && npm run e2e    # real app + real backend in deterministic mode: chat flow, + menu, upload, demo, a11y, 390 px
```

Create the pinned test environment once: `uv python install 3.11 && uv venv --python 3.11 .venv311 && uv pip install --python .venv311/bin/python -r requirements-dev.txt` (in `lit-backend/`).

Also run `lit-backend/scripts/eval_agent.py` against the real model when the prompt, tools or model changed (20 prompts, hard checks).

## Configuration

Space → Settings → Variables and secrets.

| Name | Kind | Value |
|---|---|---|
| `ENV` | variable | `production` |
| `ALLOWED_ORIGINS` | variable | the exact frontend origin(s), comma-separated (the Vercel domain) |
| `HUGGINGFACE_API_KEY` | **secret** | token for the router. **Also needs Read on the private dataset repo** (below). |
| `PRECEDENT_ARTIFACT_REPO` | variable | `thebenmerlin/lit-precedent-index` |
| `PRECEDENT_ARTIFACT_REVISION` | variable | the pinned commit SHA of the dataset repo (recorded in `docs/PHASE0.md` and the artifact manifest) |
| `LLM_PROVIDER` | variable | `hf_router` (default), or `none` to run without any LLM |
| `PLANNER_MODEL` / `NARRATION_MODEL` | variable | default `openai/gpt-oss-120b:cerebras` |
| `FALLBACK_MODEL` | variable | default `Qwen/Qwen2.5-72B-Instruct` |
| `LLM_DAILY_TOKEN_CAP` | variable | `0` = unlimited; set a number to degrade to deterministic mode when exceeded |
| `AGENT_ENABLED`, `AGENT_MAX_CONCURRENT` | variable | defaults `true`, `4` |

**The precedent library** (62 MB: `vectors.npy`, `meta.jsonl`, `manifest.json`) lives in the private dataset repo
`thebenmerlin/lit-precedent-index` under `v1/`; the Space downloads it at start and verifies each file's sha256. The
inference key must be allowed to read that repo: huggingface.co → Settings → Access Tokens → the key → add the
repository under *Repositories → Read*. Until then the Space starts, falls back to the 3-case fixture index, and
`/api/v1/health/ready` reports `index.source: "fixture"`. Treat that as not ready for a demo.

## Deploy the backend

Staging first, always.

```bash
# from the monorepo root, on the release branch
SPLIT=$(git subtree split -q --prefix=lit-backend HEAD)
git push https://huggingface.co/spaces/thebenmerlin/lit-backend-staging "${SPLIT}:refs/heads/main" --force   # staging is disposable
```

Smoke-test staging (works with no LLM; a private Space needs `--token`):

```bash
cd lit-backend && .venv311/bin/python scripts/smoke.py https://thebenmerlin-lit-backend-staging.hf.space --token "$HF_TOKEN"
```

It checks health, readiness, that the library loaded from the artifact (505 judgments), the outcome model, registering a
matter, and a forced precedents run whose stream starts with `message_start`, ends with `done`, and returns real results.
Then production (**requires an explicit go-ahead**), and run the same smoke test against it:

```bash
git tag -f deploy/last-good <current production commit>       # before pushing, so rollback is one command
git push https://huggingface.co/spaces/thebenmerlin/lit-backend "${SPLIT}:refs/heads/main"   # braces matter in zsh
```

Use `--dry-run` first to check credentials. The Space rebuilds the image, which takes a few minutes; it is **Running**
when `/health` answers. Then `scripts/smoke.py https://thebenmerlin-lit-backend.hf.space`.

## Deploy the frontend

```bash
cd lit-frontend
npm run verify && npm run build
vercel --prod            # requires an explicit go-ahead
```

`VITE_PUBLIC_API_BASE_URL` (tracked in `.env.production`) points at the Space. `vercel.json` sets the CSP, the security
headers and the SPA rewrite; if the backend URL changes, change `connect-src` in the CSP too. After deploy: open the
site, play `/demo`, run a sample review live, switch theme.

## Rollback

| Problem | Action |
|---|---|
| Bad backend release | `git push <space> <deploy/last-good sha>:refs/heads/main --force`. The previous image rebuilds. |
| Bad frontend release | `vercel rollback` (or promote the previous deployment in the dashboard). |
| LLM misbehaving or provider down | Set `LLM_PROVIDER=none`. The whole product keeps working with deterministic routing and templated narration; nothing leaves the Space. The built-in circuit breaker and fallback chain already degrade automatically on repeated failures. |
| Chat endpoint must be switched off | `AGENT_ENABLED=false`. The old per-feature endpoints stay up. |
| Wrong library revision | Change `PRECEDENT_ARTIFACT_REVISION` (the dataset repo is versioned); restart the Space. |
| Runaway spend | Set `LLM_DAILY_TOKEN_CAP`. |

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| First chat takes about a minute and says "Waking the research engine" | The free Space slept. Expected; the client waits for `/health`. Open the site a minute before a demo, or play `/demo`, which needs no backend. |
| Matter says "case unknown" then recovers | The Space restarted and lost its RAM cache; the client re-uploads silently. Normal. |
| Precedents look like three constitutional cases | The artifact did not load: token lacks Read on the dataset repo, or `PRECEDENT_ARTIFACT_REPO` is unset. See `/health/ready`. |
| 429 `busy` | More than `AGENT_MAX_CONCURRENT` runs. Wait and retry, or raise it on bigger hardware. |
| Stream stalls through a proxy | Check that responses have `X-Accel-Buffering: no` and `no-transform`, and that nothing gzips `/agent/chat`. |
| Local macOS crash or hang when loading the index | Set `OMP_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false KMP_DUPLICATE_LIB_OK=TRUE` (the Linux image is unaffected). |

## Data handling

- Case text is held in the server's RAM only (LRU 20, 2 h), never written to disk, and never logged: logs carry lengths,
  hashes and counts. A restart clears it.
- With `LLM_PROVIDER=hf_router`, the case excerpts the model needs for narration and planning are sent to
  Hugging Face's router and the provider serving the request (Cerebras by default, Qwen on DeepInfra as fallback).
  `docs/PHASE0.md` records what each says about retention and training. For real client matters, either complete that
  review or use `LLM_PROVIDER=none`.
- Conversations and uploaded matters are stored in the user's browser (IndexedDB), with an export and a "clear local
  data" action in Settings. There are no accounts and no server-side history in 1.0.
