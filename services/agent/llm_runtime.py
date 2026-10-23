"""
Model fallback chain, circuit breaker and daily token cap around any LLMClient.

`stream_with_fallback` tries the primary model, then the fallback model; once the output has started streaming it never
switches mid-answer. Three consecutive total failures open the circuit for 60 s so a provider outage costs one slow
request, not every request. All of this degrades to LLMUnavailable, which the orchestrator turns into deterministic mode.
"""

import time
from datetime import date
from typing import Any, AsyncIterator, List, Optional

from config import get_settings
from services.agent.llm.base import Finish, LLMError, LLMUnavailable, Message, ToolDef, UsageTotals
from utils.logger import get_logger

logger = get_logger(__name__)

FAILURES_TO_OPEN = 3
OPEN_SECONDS = 60


class _Breaker:
    def __init__(self) -> None:
        self.failures = 0
        self.open_until = 0.0
        self.spent_day = date.today()
        self.spent_tokens = 0

    def allow(self) -> bool:
        if time.monotonic() < self.open_until:
            return False
        cap = get_settings().LLM_DAILY_TOKEN_CAP
        if date.today() != self.spent_day:
            self.spent_day, self.spent_tokens = date.today(), 0
        return not (cap and self.spent_tokens >= cap)

    def success(self, tokens: int) -> None:
        self.failures = 0
        self.spent_tokens += tokens

    def failure(self) -> None:
        self.failures += 1
        if self.failures >= FAILURES_TO_OPEN:
            self.open_until = time.monotonic() + OPEN_SECONDS
            self.failures = 0
            logger.warning(f"LLM circuit opened for {OPEN_SECONDS}s")

    def reset(self) -> None:
        self.failures, self.open_until, self.spent_tokens = 0, 0.0, 0


breaker = _Breaker()


async def stream_with_fallback(client: Any, models: List[str], messages: List[Message], usage: UsageTotals,
                               tools: Optional[List[ToolDef]] = None, max_tokens: int = 1500,
                               temperature: float = 0.2) -> AsyncIterator[Any]:
    if not breaker.allow():
        raise LLMUnavailable("circuit open or daily token cap reached")
    last: Optional[Exception] = None
    for model in [m for i, m in enumerate(models) if m and m not in models[:i]]:
        started_output = False
        try:
            async for ev in client.stream(model, messages, tools, max_tokens, temperature):
                if isinstance(ev, Finish):
                    usage.add(ev)
                    breaker.success(ev.input_tokens + ev.output_tokens)
                else:
                    started_output = True
                yield ev
            return
        except LLMError as exc:
            last = exc
            logger.warning(f"LLM {model} failed ({exc.status}): {str(exc)[:120]}")
            if started_output:
                breaker.failure()
                raise LLMUnavailable("the model stopped mid-answer") from exc
            if not exc.retryable:
                break
    breaker.failure()
    raise LLMUnavailable(str(last) if last else "no model configured")
