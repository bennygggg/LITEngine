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

AI-powered legal intelligence system for Indian courts. This FastAPI backend provides semantic precedent search, automated fact extraction from case text, argument graph construction, and judicial outcome simulation. It integrates with Indian Kanoon for live judgment scraping, computes embeddings locally with MiniLM, and uses Hugging Face's Inference Providers for case-chat generation.

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

# 5. (Optional) Use fixtures for offline development
export USE_FIXTURES=true

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
3. Commit backend changes to the monorepo's `main` branch. The monorepo's
   `.github/workflows/deploy-hf.yml` deploys only the `lit-backend/` subtree to
   the Space. Set the GitHub repository **secret** `HF_TOKEN` to a fine-grained
   token with write access to this Space.
4. Set the GitHub repository **variable** `HF_SPACE_URL` to the public direct
   URL, `https://thebenmerlin-lit-backend.hf.space`. The
   monorepo's `.github/workflows/keep-alive.yml` calls `/health` every six hours
   and supports a manual run from the Actions tab. It fails
   visibly if the request or JSON health check fails. Scheduled GitHub Actions
   may be delayed and can be disabled after 60 days without activity in a
   public repository, so this is best effort rather than an uptime guarantee.

**Deploying without GitHub Actions.** The Space is a git repository, so the same
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
# Check outcome_model_loaded and index_loaded before testing model endpoints.
```

Then manually run both GitHub workflows and check their logs. If the frontend
is deployed separately, point its backend URL to the same direct Space URL and
check CORS from that exact frontend origin. `logs/`, `fixtures/`, and `data/`
are writable but Space-local runtime changes are ephemeral; persist any new
data outside the Space before relying on it.

---

## API Endpoints

### Health

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Basic health check — returns app name, version, status |
| GET | `/api/v1/health/ready` | Readiness probe — returns `ready`, `index_loaded`, `hf_key_set` |

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
| `HUGGINGFACE_API_KEY` | *(empty)* | HF Inference Providers token for case-chat generation (and embeddings when `EMBEDDING_BACKEND=hf_api`) |
| `EMBEDDING_BACKEND` | `local` | `local` runs MiniLM in-process; `hf_api` calls the HF Inference API and needs a funded key. Same 384-dim vectors either way |
| `KANOON_BASE_URL` | `https://api.kanoon.example.com/v1` | Base URL for Indian Kanoon scraper |
| `ALLOWED_ORIGINS` | `*` | Comma-separated list of allowed CORS origins |
| `PORT` | `8000` | Server port |
| `ENV` | `development` | `development` or `production` — controls CORS strictness |
| `USE_FIXTURES` | `false` | Use local fixture data instead of live scraping |
| `LOG_LEVEL` | `INFO` | Log level (DEBUG, INFO, WARNING, ERROR) |
| `CACHE_TTL` | `3600` | In-memory cache TTL in seconds |

---

## Sleep and Wake (Hugging Face Space)

Spaces on free hardware are suspended after a period of inactivity (Hugging
Face's docs give two days as an example) and start again on the next visit, so
the first request after a wake waits for the container to boot. The embedding
model is pre-cached in the image and loaded at startup, so requests are not
delayed by it once the container is up. The monorepo's
`keep-alive.yml` workflow calls `/health` every six hours to keep the Space
awake; see the deployment section above for its caveats.
