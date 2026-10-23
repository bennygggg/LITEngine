"""OpenAI-compatible chat-completions client for the Hugging Face router (streaming, tool calls, usage)."""

import json
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from services.agent.llm.base import Finish, LLMError, Message, TextDelta, ToolCall, ToolDef
from utils.logger import get_logger

logger = get_logger(__name__)

ROUTER_URL = "https://router.huggingface.co/v1/chat/completions"


def _is_reasoning_model(model: str) -> bool:
    return "gpt-oss" in model.lower()


class OpenAICompatClient:
    def __init__(self, api_key: str, url: str = ROUTER_URL, reasoning_effort: str = "low", timeout: float = 60.0) -> None:
        self.api_key, self.url, self.reasoning_effort = api_key, url, reasoning_effort
        self._client: Optional[httpx.AsyncClient] = None
        self._timeout = timeout

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self._timeout, connect=10.0))
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _payload(self, model: str, messages: List[Message], tools: Optional[List[ToolDef]], max_tokens: int, temperature: float) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": model, "stream": True, "stream_options": {"include_usage": True}, "max_tokens": max_tokens,
            "temperature": temperature, "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        if tools:
            payload["tools"] = [t.as_openai() for t in tools]
            payload["tool_choice"] = "auto"
        if _is_reasoning_model(model):
            payload["reasoning_effort"] = self.reasoning_effort  # keeps answers fast; the model's hidden reasoning is never shown
        return payload

    async def stream(self, model: str, messages: List[Message], tools: Optional[List[ToolDef]] = None,
                     max_tokens: int = 1500, temperature: float = 0.2) -> AsyncIterator[Any]:
        client = await self._http()
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        pending: Dict[int, Dict[str, Any]] = {}  # tool-call assembly by stream index
        finish_reason, usage, served_model = "stop", {}, model
        try:
            async with client.stream("POST", self.url, json=self._payload(model, messages, tools, max_tokens, temperature), headers=headers) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", "ignore")[:300]
                    raise LLMError(f"HTTP {resp.status_code}: {body}", status=resp.status_code,
                                   retryable=resp.status_code in (408, 409, 425, 429) or resp.status_code >= 500 or resp.status_code in (400, 404))
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    served_model = obj.get("model", served_model)
                    if obj.get("usage"):
                        usage = obj["usage"]
                    for choice in obj.get("choices") or []:
                        delta = choice.get("delta") or {}
                        if delta.get("content"):          # `reasoning` / `reasoning_content` deltas are deliberately ignored
                            yield TextDelta(delta["content"])
                        for tc in delta.get("tool_calls") or []:
                            slot = pending.setdefault(tc.get("index", 0), {"id": "", "name": "", "args": ""})
                            slot["id"] = tc.get("id") or slot["id"]
                            fn = tc.get("function") or {}
                            slot["name"] = fn.get("name") or slot["name"]
                            slot["args"] += fn.get("arguments") or ""
                        if choice.get("finish_reason"):
                            finish_reason = choice["finish_reason"]
        except httpx.TimeoutException as exc:
            raise LLMError(f"timeout: {type(exc).__name__}", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"network: {type(exc).__name__}", retryable=True) from exc
        for idx in sorted(pending):
            slot = pending[idx]
            try:
                args = json.loads(slot["args"]) if slot["args"].strip() else {}
            except json.JSONDecodeError:
                logger.warning("LLM produced unparseable tool arguments; ignoring that call")
                continue
            if slot["name"]:
                yield ToolCall(id=slot["id"] or f"call_{idx}", name=slot["name"], arguments=args if isinstance(args, dict) else {})
        yield Finish(reason=finish_reason, input_tokens=int(usage.get("prompt_tokens", 0)),
                     output_tokens=int(usage.get("completion_tokens", 0)), model=served_model)
