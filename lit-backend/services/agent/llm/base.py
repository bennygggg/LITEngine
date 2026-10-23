"""
Provider-neutral LLM interface.

The orchestrator only ever sees these events, so swapping the HF router for another provider (or the scripted fake used
in tests) never touches orchestration code.
"""

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional, Protocol


class LLMError(Exception):
    """A provider failure. `retryable` means a different model or a later retry might succeed."""

    def __init__(self, message: str, status: Optional[int] = None, retryable: bool = True) -> None:
        super().__init__(message)
        self.status, self.retryable = status, retryable


class LLMUnavailable(Exception):
    """Every configured model failed (or the circuit is open / the daily cap is spent): fall back to deterministic mode."""


@dataclass
class TextDelta:
    text: str


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class Finish:
    reason: str = "stop"
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""


LLMEvent = Any  # TextDelta | ToolCall | Finish


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: Dict[str, Any]

    def as_openai(self) -> Dict[str, Any]:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


@dataclass
class Message:
    role: str  # system | user | assistant
    content: str


class LLMClient(Protocol):
    async def stream(self, model: str, messages: List[Message], tools: Optional[List[ToolDef]] = None,
                     max_tokens: int = 1500, temperature: float = 0.2) -> AsyncIterator[LLMEvent]: ...


@dataclass
class UsageTotals:
    input_tokens: int = 0
    output_tokens: int = 0
    llm_calls: int = 0

    def add(self, f: Finish) -> None:
        self.input_tokens += f.input_tokens
        self.output_tokens += f.output_tokens
        self.llm_calls += 1
