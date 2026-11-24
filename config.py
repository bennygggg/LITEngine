from pydantic_settings import BaseSettings
from typing import List
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Hugging Face Configuration
    HUGGINGFACE_API_KEY: str = ""

    # Where embeddings come from: "local" runs all-MiniLM-L6-v2 inside this
    # process (pre-cached in the Docker image), "hf_api" calls the HF
    # Inference Providers router and needs a funded HUGGINGFACE_API_KEY. Both
    # give the same 384-dim vectors, so the FAISS index works with either.
    # Local is the default so a missing, unfunded or rate-limited key can't
    # take precedent search and case chat down with it.
    EMBEDDING_BACKEND: str = "local"

    # Kanoon API Configuration
    KANOON_BASE_URL: str = "https://api.kanoon.example.com/v1"

    # CORS Configuration
    ALLOWED_ORIGINS: str = "*"

    # Server Configuration
    PORT: int = 8000

    # Logging
    LOG_LEVEL: str = "INFO"

    # Cache
    CACHE_TTL: int = 3600

    # App Metadata
    APP_NAME: str = "Legal Intelligence Terminal"
    APP_VERSION: str = "1.0.1"
    DEBUG: bool = False

    # Environment
    ENV: str = "development"

    # Use fixtures (offline dev mode)
    USE_FIXTURES: bool = False

    # Precedent library artifact (vectors.npy + meta.jsonl + manifest.json). Resolution order:
    #   1. PRECEDENT_ARTIFACT_DIR  — a local directory (dev, or pre-baked)
    #   2. PRECEDENT_ARTIFACT_REPO — a private HF dataset repo, downloaded at startup into data/precedent_artifacts
    #   3. the 3-case fixture index (graceful fallback — the app still starts, /health/ready says so)
    # HF_DATASET_TOKEN falls back to HUGGINGFACE_API_KEY; the key needs read access to the dataset repo.
    PRECEDENT_ARTIFACT_DIR: str = ""
    PRECEDENT_ARTIFACT_REPO: str = ""
    PRECEDENT_ARTIFACT_REVISION: str = "main"
    PRECEDENT_ARTIFACT_SUBDIR: str = "v1"
    HF_DATASET_TOKEN: str = ""

    # Chat agent (POST /api/v1/agent/chat). LLM_PROVIDER: "hf_router" | "fake" | "none".
    # "none" runs the whole product with deterministic routing and templated narration (no text leaves the Space).
    AGENT_ENABLED: bool = True
    LLM_PROVIDER: str = "hf_router"
    # Pin the provider with the router's "model:provider" form (see docs/PHASE0.md for why Cerebras).
    PLANNER_MODEL: str = "openai/gpt-oss-120b:cerebras"
    NARRATION_MODEL: str = "openai/gpt-oss-120b:cerebras"
    FALLBACK_MODEL: str = "Qwen/Qwen2.5-72B-Instruct"
    LLM_REASONING_EFFORT: str = "low"
    AGENT_MAX_ITERATIONS: int = 4
    AGENT_MAX_TOKENS: int = 1500
    AGENT_RUN_TIMEOUT_S: int = 90
    AGENT_PING_S: float = 10.0  # keep-alive cadence; the HF proxy and browsers need bytes during CPU work
    AGENT_MAX_CONCURRENT: int = 4  # protects the 2-vCPU Space (stability, not access control)
    AGENT_ORPHAN_CANCEL_S: int = 15  # cancel a run this long after its last reader disconnects
    AGENT_TOOL_TIMEOUT_S: int = 20
    LLM_DAILY_TOKEN_CAP: int = 0  # 0 = unlimited; when exceeded the agent degrades to deterministic mode

    # Throwaway streaming test endpoint (/api/v1/spike/stream) used to prove SSE survives the HF proxy.
    # Off everywhere except the staging Space.
    SPIKE_ENABLED: bool = False

    # Outcome model — which prediction populates the top-level
    # SimulationResponse.result: "juris" (trained binary classifier)
    # or "heuristic" (hand-picked weights). Automatically forced to
    # "heuristic" if the trained model fails to load, regardless of
    # this setting. Flip via env var for a fast, code-free revert.
    JURIS_PRIMARY: str = "juris"
    JURIS_MODEL_PATH: str = ""  # Optional gated, versioned artifact path
    PRECEDENT_INDEX_PATH: str = ""  # Optional dated precedent index used by live search
    # Juris ships through the same private HF dataset repo as the precedent library (HF Spaces reject binary files in git):
    # <PRECEDENT_ARTIFACT_REPO>/<JURIS_ARTIFACT_SUBDIR>/juris.joblib, verified against the sha256 in the committed model_card.json.
    JURIS_ARTIFACT_SUBDIR: str = "juris/v1"
    JURIS_ARTIFACT_REVISION: str = "main"

    # Case chat — instruction-tuned generation model, called through HF's
    # OpenAI-compatible chat-completions router (multi-provider, generally
    # better free-tier availability for conversational models than the
    # older single-provider api-inference.huggingface.co/models/<id> path
    # that embedder.py/extractor.py use for embeddings/NER). Override via
    # env var if this model becomes unavailable — no code change needed.
    # Verified live against the real account 2026-09-25 — Qwen2.5-7B-Instruct
    # and several other candidates (Mistral-7B-Instruct-v0.3, zephyr-7b-beta,
    # Phi-3.5-mini-instruct, gemma-2-9b-it) came back "not supported by any
    # provider you have enabled" for this account; Llama-3.1-8B-Instruct and
    # Qwen2.5-72B-Instruct both worked. Picked the 8B model for lower demo
    # latency over the 72B one.
    CHAT_MODEL: str = "meta-llama/Llama-3.1-8B-Instruct"
    CHAT_TOP_K: int = 5

    @property
    def IS_PRODUCTION(self) -> bool:
        """True when running in production environment."""
        return self.ENV == "production"

    @property
    def cors_origins(self) -> List[str]:
        """Parse CORS origins from comma-separated string.

        In development (default): if ALLOWED_ORIGINS is "*", allow all origins.
        In production: only explicit origins from ALLOWED_ORIGINS.
          If set to "*" in production, defaults to empty list (no CORS access).
        """
        if not self.IS_PRODUCTION and self.ALLOWED_ORIGINS == "*":
            return ["*"]
        if self.ALLOWED_ORIGINS == "*":
            # In production, never allow wildcard — safest default
            return []
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",") if origin.strip()]

    @property
    def allowed_origins_list(self) -> List[str]:
        """Always return the parsed list (no wildcard fallback)."""
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",") if origin.strip()]

    @property
    def hf_key_set(self) -> bool:
        """Whether the HF API key is configured (safe to log)."""
        return bool(self.HUGGINGFACE_API_KEY and not self.HUGGINGFACE_API_KEY.startswith("hf_your_"))

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    """Cached settings instance to avoid reloading .env on every request."""
    return Settings()
