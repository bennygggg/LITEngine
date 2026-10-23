---
title: LITEngine Backend
emoji: ⚖️
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Legal Intelligence Terminal (LIT) — Backend

AI-powered legal research for Indian courts. This FastAPI backend serves the v1.0.0 chat workspace: a streaming agent
(`POST /api/v1/agent/chat`) that reads a case, searches a 505-judgment precedent library, builds an argument map, gives
an indicative outcome estimate for criminal appeals, and compares scenarios — each as a typed card. The per-feature
endpoints (facts, precedents, graph, simulation) remain. Embeddings are computed locally with MiniLM; the agent's
planning and narration use Hugging Face's router (or run fully deterministic with `LLM_PROVIDER=none`).

Start with `../docs/ARCHITECTURE.md`, `../docs/PROTOCOL.md` and `../docs/RUNBOOK.md`.

---

## Local Setup

```bash
# 1. Clone the repo and enter the backend directory
git clone <your-repo-url>
cd lit-backend

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate        # Linux/macOS
# venv\Scripts\activate         # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env — set HUGGINGFACE_API_KEY and other values as needed

# 5. (Optional) Use the real precedent library locally instead of the 3-case fixture index
export PRECEDENT_ARTIFACT_DIR=data/precedent_artifacts/v1      # build with scripts/build_precedent_artifacts.py
# macOS only: faiss and torch in one process need these
export OMP_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false KMP_DUPLICATE_LIB_OK=TRUE

# 6. Start the server
uvicorn main:app --reload
# → http://localhost:8000
# → Swagger docs: http://localhost:8000/docs
```

---

## Deploy to Hugging Face Spaces (Docker)

The Space repository is the contents of this `lit-backend/` directory. This
README (its frontmatter sets `sdk: docker` and `app_port: 7860`) and the
`Dockerfile` must appear at its root. The image runs the FastAPI app, including
`/health`, `/docs`, and `/api/v1/...`, with uvicorn on port 7860. The backend is
CPU-only. The image uses Python 3.11 because the trained outcome model needs
scikit-learn 1.8.0, which requires Python 3.11 or newer. Keep that dependency
and the committed model artifact together when deploying.

1. Use the existing **Docker** Space `thebenmerlin/lit-backend` on **CPU Basic**
   hardware (**Settings → Hardware**). Docker Spaces cannot use ZeroGPU.
2. In the Space's **Settings → Variables and secrets**, set:

   | Name | Type | Value |
   |---|---|---|
   | `ENV` | Variable | `production` |
   | `ALLOWED_ORIGINS` | Variable | Exact frontend origin(s), comma-separated, for example `https://litengine.example.com` |
   | `HUGGINGFACE_API_KEY` | Secret | An Inference Providers token, used for case-chat generation |

   `HUGGINGFACE_API_KEY` is optional: without it, case chat returns the most
   relevant excerpt instead of a generated answer. The GitHub deployment token
   `HF_TOKEN` is separate and must never be put in Space variables or committed
   to Git.
3. Allow the key to **read the private precedent dataset repo** (`PRECEDENT_ARTIFACT_REPO`,
   pinned with `PRECEDENT_ARTIFACT_REVISION`); the Space downloads and verifies the library at start. See
   `../docs/RUNBOOK.md` for the full variable list, staging, smoke test and rollback.
4. Deploy by pushing the `lit-backend/` subtree to the Space (below). The repository's
   `.github/workflows/deploy-hf.yml` and `keep-alive.yml` only apply while a GitHub remote is available.

**Deploying by hand (the current method).** The Space is a git repository, so the
subtree can be pushed to it directly from a checkout. Log in once with a token
that has write access to the Space (`hf auth login --add-to-git-credential`, run
in a real terminal), then from the monorepo root:

```bash
SPLIT=$(git subtree split -q --prefix=lit-backend main)
git push https://huggingface.co/spaces/thebenmerlin/lit-backend "${SPLIT}:refs/heads/main"
```

Use `${SPLIT}` with braces — in zsh, `$SPLIT:refs` is parsed as a modifier.
Add `--dry-run` first to check the credentials without changing the Space.

Verify once the Space reports **Running**:

```bash
HF_SPACE_URL=https://thebenmerlin-lit-backend.hf.space
curl --fail-with-body --show-error --max-time 30 \
  "${HF_SPACE_URL}/health"
# Expect JSON containing "status":"healthy".
curl --fail-with-body --show-error --max-time 30 \
  "${HF_SPACE_URL}/api/v1/health/ready"
# Check outcome_model_loaded and index.source == "artifact" (505 judgments) before testing model endpoints.
python scripts/smoke.py "${HF_SPACE_URL}"   # health, readiness, library, and a streamed precedents run (no LLM needed)
```

If the frontend is deployed separately, point its backend URL to the same direct Space URL and
check CORS from that exact frontend origin. `logs/`, `fixtures/`, and `data/`
are writable but Space-local runtime changes are ephemeral; persist any new
data outside the Space before relying on it.

---

## API Endpoints

### Health

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Basic health check — returns app name, version, status |
| GET | `/api/v1/health/ready` | Readiness — `ready`, library (`index.source`, judgments, version), embedder, outcome model, LLM configured (boolean) |

### Chat agent

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/agent/chat` | Run one assistant turn; streams Server-Sent Events (cards, steps, narration). See `../docs/PROTOCOL.md` |
| DELETE | `/api/v1/agent/runs/{run_id}` | Stop a run |
| GET | `/api/v1/agent/status` | LLM, library and model state |
| PUT | `/api/v1/cases/{sha256}` | Register a matter's text in the RAM-only case cache |
| POST | `/api/v1/simulation/scenario` | Compare scenarios by re-scoring the real outcome model |

### Precedent Search

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/precedent/` | Module status check |
| POST | `/api/v1/precedent/search` | Semantic search over precedents (FAISS + Kanoon fallback) |
| GET | `/api/v1/precedent/{doc_id}` | Fetch full judgment detail from Kanoon |
| POST | `/api/v1/precedent/index` | Index a document into the FAISS index |
| GET | `/api/v1/precedent/index/stats` | FAISS index statistics |

### Fact Extraction

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/facts/` | Module status check |
| POST | `/api/v1/facts/extract` | Extract structured case profile from raw text |
| POST | `/api/v1/facts/extract/batch` | Batch extract up to 5 cases concurrently |
| GET | `/api/v1/facts/status/{task_id}` | Poll async extraction task status |

### Argument Graph

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/graph/` | Module status check |
| POST | `/api/v1/graph/build` | Build argument graph from a StructuredCaseProfile |
| POST | `/api/v1/graph/query` | Query the knowledge graph |

### Judicial Simulation

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/simulation/` | Module status check |
| POST | `/api/v1/simulation/predict` | Predict judicial outcome with explainable scoring |

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `HUGGINGFACE_API_KEY` | *(empty)* | HF token: agent LLM calls, case-chat generation, downloading the precedent library (embeddings too when `EMBEDDING_BACKEND=hf_api`) |
| `EMBEDDING_BACKEND` | `local` | `local` runs MiniLM in-process; `hf_api` calls the HF Inference API and needs a funded key. Same 384-dim vectors either way |
| `KANOON_BASE_URL` | `https://api.kanoon.example.com/v1` | Base URL for Indian Kanoon scraper |
| `ALLOWED_ORIGINS` | `*` | Comma-separated list of allowed CORS origins |
| `PORT` | `8000` | Server port |
| `ENV` | `development` | `development` or `production` — controls CORS strictness |
| `USE_FIXTURES` | `false` | Use local fixture data instead of live scraping |
| `LOG_LEVEL` | `INFO` | Log level (DEBUG, INFO, WARNING, ERROR) |
| `CACHE_TTL` | `3600` | In-memory cache TTL in seconds |
| `PRECEDENT_ARTIFACT_DIR` | *(empty)* | Local directory holding the precedent library (`vectors.npy`, `meta.jsonl`, `manifest.json`) |
| `PRECEDENT_ARTIFACT_REPO` / `_REVISION` / `_SUBDIR` | *(empty)* / `main` / `v1` | Private HF dataset repo the library is downloaded from at start (the key needs Read on it); pin the revision |
| `LLM_PROVIDER` | `hf_router` | `hf_router`, `fake` (tests) or `none` (deterministic routing and templated narration; nothing leaves the server) |
| `PLANNER_MODEL` / `NARRATION_MODEL` | `openai/gpt-oss-120b:cerebras` | Router models; `model:provider` pins the provider |
| `FALLBACK_MODEL` | `Qwen/Qwen2.5-72B-Instruct` | Used when the primary model errors, times out or refuses |
| `LLM_DAILY_TOKEN_CAP` | `0` | `0` = unlimited; above this the agent degrades to deterministic mode |
| `AGENT_ENABLED` | `true` | Kill switch for the chat endpoint |
| `AGENT_MAX_CONCURRENT` | `4` | Concurrent runs the 2-vCPU Space will accept (429 beyond) |
| `AGENT_PING_S` / `AGENT_ORPHAN_CANCEL_S` / `AGENT_RUN_TIMEOUT_S` | `10` / `15` / `90` | Keep-alive cadence, cancel-after-disconnect grace, run wall-clock cap |

---

## Tests

```bash
export OMP_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false KMP_DUPLICATE_LIB_OK=TRUE   # macOS only
.venv311/bin/python -m pytest -q -m "not slow and not live_server"      # 119 tests, no network, no LLM
.venv311/bin/python scripts/export_openapi.py --check                    # contract drift
.venv311/bin/python scripts/eval_agent.py                                # manual: 20 prompts against the live model
```

`.venv311` is Python 3.11 with the production pins (`uv venv --python 3.11 .venv311 && uv pip install --python
.venv311/bin/python -r requirements-dev.txt`), so tests run on what the Space runs. `../scripts/verify.sh` runs the
backend and frontend checks together.

---

## Sleep and Wake (Hugging Face Space)

Spaces on free hardware are suspended after a period of inactivity (Hugging
Face's docs give two days as an example) and start again on the next visit, so
the first request after a wake waits for the container to boot. The embedding
model is pre-cached in the image and loaded at startup, so requests are not
delayed by it once the container is up. The monorepo's
`keep-alive.yml` workflow calls `/health` every six hours to keep the Space
awake; see the deployment section above for its caveats.
