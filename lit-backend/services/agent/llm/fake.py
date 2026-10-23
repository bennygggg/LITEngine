"""
Scriptable LLM for tests and offline demos (LLM_PROVIDER=fake). Each call to `stream` consumes the next script entry:

    fake.script([
        {"tool_calls": [{"name": "search_precedents", "arguments": {"query": "FIR delay"}}]},   # planner turn
        {"text": "The closest match is [P1]."},                                                  # narration turn
    ])

An entry may also set {"error": "msg"} to raise LLMError, or {"delay": 0.2} between text chunks.
"""

import asyncio
from typing import Any, AsyncIterator, Dict, List, Optional

from services.agent.llm.base import Finish, LLMError, Message, TextDelta, ToolCall, ToolDef


class FakeLLMClient:
    def __init__(self) -> None:
        self._script: List[Dict[str, Any]] = []
        self.calls: List[Dict[str, Any]] = []

    def script(self, entries: List[Dict[str, Any]]) -> "FakeLLMClient":
        self._script = list(entries)
        self.calls = []
        return self

    async def stream(self, model: str, messages: List[Message], tools: Optional[List[ToolDef]] = None,
                     max_tokens: int = 1500, temperature: float = 0.2) -> AsyncIterator[Any]:
        self.calls.append({"model": model, "messages": messages, "tools": [t.name for t in tools] if tools else None})
        entry = self._script.pop(0) if self._script else {"text": "Understood."}
        if entry.get("error"):
            raise LLMError(entry["error"], status=entry.get("status", 503), retryable=entry.get("retryable", True))
        text = entry.get("text", "")
        words = text.split(" ")
        for i, w in enumerate(words):
            if entry.get("delay"):
                await asyncio.sleep(entry["delay"])
            yield TextDelta(w + (" " if i < len(words) - 1 else ""))
        for i, tc in enumerate(entry.get("tool_calls", [])):
            yield ToolCall(id=f"call_{i}", name=tc["name"], arguments=tc.get("arguments", {}))
        yield Finish(reason="tool_calls" if entry.get("tool_calls") else "stop",
                     input_tokens=sum(len(m.content) // 4 for m in messages), output_tokens=max(len(text) // 4, 1), model=model)
