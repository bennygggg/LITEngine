"""
Streaming spike — a throwaway endpoint that answers one question: does a long Server-Sent Events response
survive the Hugging Face Spaces proxy (and a cross-origin browser) intact and in real time?

Only mounted when SPIKE_ENABLED=true (the staging Space). Never enable it on the production Space.

    GET /api/v1/spike/stream?seconds=150&tick=5&ping=10&silent_from=0&silent_for=0

Events: `hello` (padded ~2 KB to defeat proxy buffering), `tick` every `tick` seconds, `ping` every `ping` seconds,
optional silence (`silent_from`..`silent_from+silent_for` seconds with no bytes at all, to find the proxy's idle
limit), then `done`. Every payload carries the server's elapsed milliseconds so the client can measure lag.
"""

import asyncio
import json
import time
from typing import AsyncIterator

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/spike", tags=["Spike"])


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


@router.get("/stream")
async def stream(
    request: Request,
    seconds: int = Query(150, ge=5, le=600),
    tick: int = Query(5, ge=1, le=60),
    ping: int = Query(10, ge=1, le=60),
    silent_from: int = Query(0, ge=0, le=600),
    silent_for: int = Query(0, ge=0, le=300),
    pad: int = Query(2048, ge=0, le=16384),
):
    started = time.monotonic()

    def elapsed_ms() -> int:
        return int((time.monotonic() - started) * 1000)

    async def gen() -> AsyncIterator[bytes]:
        yield _sse("hello", {"t": 0, "pad": "x" * pad})
        seq = 0
        next_tick, next_ping = tick, ping
        while True:
            now = time.monotonic() - started
            if now >= seconds or await request.is_disconnected():
                break
            in_silence = silent_for > 0 and silent_from <= now < silent_from + silent_for
            if not in_silence:
                if now >= next_tick:
                    seq += 1
                    next_tick += tick
                    yield _sse("tick", {"seq": seq, "t": elapsed_ms()})
                if now >= next_ping:
                    next_ping += ping
                    yield _sse("ping", {"t": elapsed_ms()})
            await asyncio.sleep(0.25)
        yield _sse("done", {"t": elapsed_ms(), "ticks": seq})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no"},
    )
