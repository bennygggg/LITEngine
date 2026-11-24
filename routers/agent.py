"""
Agent router — the chat orchestrator's HTTP surface.

    POST   /api/v1/agent/chat           SSE stream of AgentEvents (see models/agent_schemas.py)
    DELETE /api/v1/agent/runs/{run_id}  stop a run (best-effort companion to aborting the fetch)
    GET    /api/v1/agent/status         what the agent can do right now (LLM on/off, index, model)
    GET    /api/v1/agent/schema         OpenAPI carrier for the card/event types (never served)
"""

import asyncio
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from config import get_settings
from models.agent_schemas import SCHEMA_VERSION, AgentChatRequest, AgentSchemaBundle
from services.agent.events import RunLog, encode_sse, registry
from services.agent.orchestrator import orchestrator
from services.agent.workspace import workspaces
from services.embedder import embedder_service
from services.juris import is_juris_loaded
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/agent", tags=["Agent"])

MIN_CLIENT_SCHEMA = 1
SSE_HEADERS = {"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"}


def _err(status: int, code: str, message: str, **headers: str) -> JSONResponse:
    return JSONResponse({"code": code, "message": message}, status_code=status, headers=headers)


def llm_status() -> dict:
    s = get_settings()
    configured = s.LLM_PROVIDER == "fake" or (s.LLM_PROVIDER == "hf_router" and s.hf_key_set)
    return {"provider": s.LLM_PROVIDER, "configured": configured, "planner_model": s.PLANNER_MODEL if configured else None,
            "narration_model": s.NARRATION_MODEL if configured else None}


@router.get("/status")
async def status():
    return {
        "schema_version": SCHEMA_VERSION, "server_version": get_settings().APP_VERSION, "agent_enabled": get_settings().AGENT_ENABLED,
        "llm": llm_status(), "deterministic_only": not llm_status()["configured"],
        "library": embedder_service.index_info(), "juris_loaded": is_juris_loaded(),
        "active_runs": registry.active_count(),
    }


@router.post("/chat")
async def chat(request: Request, body: AgentChatRequest, last_event_id: Optional[str] = Header(None)):
    settings = get_settings()
    if not settings.AGENT_ENABLED:
        return _err(503, "agent_disabled", "The assistant is switched off on this server.")
    if body.client.schema_version < MIN_CLIENT_SCHEMA:
        return _err(426, "client_outdated", "Please refresh to get the latest version of the app.")

    log = registry.get(body.run_id)
    after = int(last_event_id) if (last_event_id or "").isdigit() else 0
    if log is None:
        ws = None
        if body.case is not None:
            ws = workspaces.get(body.case.ref)
            if ws is None:
                return _err(409, "case_unknown", "This server doesn't have the case text yet — PUT it to /api/v1/cases/{sha256} and retry.")
        if registry.active_count() >= settings.AGENT_MAX_CONCURRENT:
            return _err(429, "busy", "The assistant is handling several requests. Please try again in a few seconds.", **{"Retry-After": "5"})
        log = registry.create(body.run_id)
        log.task = asyncio.create_task(orchestrator.run(body, ws, log))
        log.task.add_done_callback(lambda t, lg=log: _on_task_done(t, lg))
    return StreamingResponse(_stream(request, log, after), media_type="text/event-stream", headers={**SSE_HEADERS, "X-Run-Id": body.run_id})


def _on_task_done(task: asyncio.Task, log: RunLog) -> None:
    if not log.finished:  # the orchestrator always finishes the log; this covers a cancel before it got to run
        log.finish()
    if not task.cancelled() and task.exception():
        logger.error(f"agent task crashed: {task.exception()}")


def _arm_orphan_timer(log: RunLog) -> None:
    """If nobody is reading this run, stop it after a short grace period (a quick reconnect cancels the timer)."""
    seconds = get_settings().AGENT_ORPHAN_CANCEL_S
    loop = asyncio.get_running_loop()

    def cancel_if_orphaned() -> None:
        if log.readers == 0 and not log.finished and log.task and not log.task.done():
            log.task.cancel()

    log.cancel_timer = loop.call_later(seconds, cancel_if_orphaned)


async def _stream(request: Request, log: RunLog, after_seq: int) -> AsyncIterator[bytes]:
    log.readers += 1
    if log.cancel_timer:
        log.cancel_timer.cancel()
        log.cancel_timer = None
    try:
        yield b": " + b" " * 2048 + b"\n\n"  # pad the first bytes so buffering proxies flush immediately
        async for seq, name, data in log.tail(after_seq, ping_every=get_settings().AGENT_PING_S, poll=min(1.0, get_settings().AGENT_PING_S / 2), is_disconnected=request.is_disconnected):
            yield encode_sse(seq, name, data)
    finally:
        log.readers -= 1
        if log.readers == 0 and not log.finished:
            _arm_orphan_timer(log)


@router.delete("/runs/{run_id}")
async def stop_run(run_id: str):
    log = registry.get(run_id)
    if log is None:
        raise HTTPException(status_code=404, detail="No such run.")
    if log.task and not log.task.done():
        log.task.cancel()
    return {"stopped": True}


@router.get("/schema", response_model=AgentSchemaBundle, include_in_schema=True)
async def schema_carrier():
    """Never served: registering this response model puts every card and event variant into the OpenAPI
    components, which `openapi-typescript` turns into the frontend's types."""
    raise HTTPException(status_code=501, detail="Schema carrier only — see /openapi.json")
