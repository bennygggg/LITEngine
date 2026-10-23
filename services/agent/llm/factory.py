"""Which LLM (if any) this server uses: decided by config, never by the request."""

from typing import Optional

from config import get_settings
from services.agent.llm.fake import FakeLLMClient
from services.agent.llm.openai_compat import OpenAICompatClient

fake_llm = FakeLLMClient()
_hf: Optional[OpenAICompatClient] = None


def get_llm() -> Optional[object]:
    """None means deterministic mode: routing by rules, narration by templates, nothing sent to any provider."""
    global _hf
    s = get_settings()
    if s.LLM_PROVIDER == "fake":
        return fake_llm
    if s.LLM_PROVIDER == "hf_router" and s.hf_key_set:
        if _hf is None:
            _hf = OpenAICompatClient(api_key=s.HUGGINGFACE_API_KEY, reasoning_effort=s.LLM_REASONING_EFFORT)
        return _hf
    return None


async def close_llm() -> None:
    if _hf is not None:
        await _hf.close()
