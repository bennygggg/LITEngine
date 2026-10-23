"""
Run events: the per-run emitter (seq/t stamping), the replayable RunLog, and the registry of recent runs.

The producer (the orchestrator task) appends events to a RunLog; the SSE response tails it. Decoupling the two is what
makes keep-alive pings flow during CPU work, lets a dropped client re-attach with Last-Event-ID, and lets a Stop
cancel the producer even if the socket is already gone.
"""

import asyncio
import json
import time
from collections import OrderedDict
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from pydantic import BaseModel

from models.agent_schemas import PingEvent

MAX_RUNS = 20
RUN_TTL_S = 300
MAX_RUN_BYTES = 3 * 1024 * 1024


class EventEmitter:
    """Stamps events with a strictly increasing seq and ms-since-start."""

    def __init__(self) -> None:
        self.seq = 0
        self.t0 = time.monotonic()

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.t0) * 1000)

    def make(self, cls: type, **fields: Any) -> BaseModel:
        self.seq += 1
        return cls(seq=self.seq, t=self.elapsed_ms(), **fields)


def encode_sse(seq: int, name: str, data_json: str) -> bytes:
    return f"id: {seq}\nevent: {name}\ndata: {data_json}\n\n".encode("utf-8")


class RunLog:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.emitter = EventEmitter()
        self._events: List[Tuple[int, str, str]] = []  # (seq, name, json)
        self._bytes = 0
        self._changed = asyncio.Event()
        self.finished = False
        self.task: Optional[asyncio.Task] = None
        self.finished_at: Optional[float] = None
        self.cancel_timer: Optional[asyncio.TimerHandle] = None
        self.readers = 0

    # -- producer side -----------------------------------------------------
    def append(self, event: BaseModel) -> None:
        data = event.model_dump_json()
        name = getattr(event, "event")
        self._events.append((event.seq, name, data))  # type: ignore[attr-defined]
        self._bytes += len(data)
        self._changed.set()

    def emit(self, cls: type, **fields: Any) -> BaseModel:
        ev = self.emitter.make(cls, **fields)
        self.append(ev)
        return ev

    def finish(self) -> None:
        self.finished = True
        self.finished_at = time.monotonic()
        self._changed.set()

    # -- consumer side -----------------------------------------------------
    def events_after(self, seq: int) -> List[Tuple[int, str, str]]:
        return [e for e in self._events if e[0] > seq]

    def all_events(self) -> List[Dict[str, Any]]:
        return [json.loads(e[2]) for e in self._events]

    async def wait_for_change(self, timeout: float) -> bool:
        """True if something new arrived (or the run finished) within `timeout`."""
        self._changed.clear()
        try:
            await asyncio.wait_for(self._changed.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def ping(self, warm: bool = True) -> None:
        self.emit(PingEvent, warm=warm)

    async def tail(self, after_seq: int = 0, ping_every: float = 10.0, poll: float = 1.0,
                   is_disconnected: Optional[Any] = None) -> AsyncIterator[Tuple[int, str, str]]:
        """Yield events after `after_seq` as they arrive; emit a ping after `ping_every` s of silence.

        Ends when the run is finished and drained, or when the reader disconnects."""
        cursor = after_seq
        last_sent = time.monotonic()
        while True:
            batch = self.events_after(cursor)
            for item in batch:
                cursor = item[0]
                last_sent = time.monotonic()
                yield item
            if self.finished and not self.events_after(cursor):
                return
            if is_disconnected is not None and await is_disconnected():
                return
            if not batch:
                changed = await self.wait_for_change(poll)
                if not changed and time.monotonic() - last_sent >= ping_every and not self.finished:
                    self.ping()


class RunRegistry:
    def __init__(self) -> None:
        self._runs: "OrderedDict[str, RunLog]" = OrderedDict()

    def _gc(self) -> None:
        now = time.monotonic()
        for rid in [r for r, log in self._runs.items() if log.finished_at and now - log.finished_at > RUN_TTL_S]:
            self._runs.pop(rid, None)
        while len(self._runs) > MAX_RUNS:
            rid, log = self._runs.popitem(last=False)
            if log.task and not log.task.done():
                log.task.cancel()

    def get(self, run_id: str) -> Optional[RunLog]:
        self._gc()
        return self._runs.get(run_id)

    def create(self, run_id: str) -> RunLog:
        log = RunLog(run_id)
        self._runs[run_id] = log
        self._gc()
        return log

    def active_count(self) -> int:
        return sum(1 for log in self._runs.values() if not log.finished)

    def clear(self) -> None:
        for log in self._runs.values():
            if log.task and not log.task.done():
                log.task.cancel()
        self._runs.clear()


registry = RunRegistry()
