"""Case cache routes — the client PUTs a matter's text once, then refers to it by its sha256."""

import asyncio

from fastapi import APIRouter, HTTPException

from models.agent_schemas import CasePreview, CasePutRequest
from services.agent.extraction import detect, profile_key
from services.agent.workspace import sha256_text, workspaces
from services.agent.tools import _profile_value
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/cases", tags=["Cases"])


@router.put("/{sha}", response_model=CasePreview)
async def put_case(sha: str, body: CasePutRequest):
    """Register a case's text in the server's short-lived cache; returns what was detected. Nothing is written to disk."""
    if sha256_text(body.text) != sha:
        raise HTTPException(status_code=422, detail="The sha256 in the path does not match the text.")
    ws = workspaces.put(body.text, body.title, body.filename)
    (profile, quality), _ = await ws.get_or_compute(profile_key(sha), lambda: _profile_for_put(body.text))
    # Warm the document index in the background so the first question about this matter doesn't pay for embedding it.
    asyncio.create_task(_prewarm(ws))
    return CasePreview(ref=sha, known=True, word_count=len(body.text.split()), detected=detect(profile), extraction=quality)


@router.head("/{sha}")
async def head_case(sha: str):
    if workspaces.get(sha) is None:
        raise HTTPException(status_code=404)
    return None


async def _profile_for_put(text: str):
    return await _profile_value(text, None)


async def _prewarm(ws) -> None:
    try:
        await ws.ensure_doc_index()
    except Exception as exc:  # noqa: BLE001 — prewarm is an optimisation only
        logger.warning(f"document index prewarm failed: {type(exc).__name__}")
