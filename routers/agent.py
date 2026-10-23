"""
Agent router — the chat orchestrator's HTTP surface.

Phase 0 ships only the schema carrier below; Phase 1 adds `POST /agent/chat` (SSE), `DELETE /agent/runs/{id}`
and the case cache routes. See models/agent_schemas.py for the wire contract.
"""

from fastapi import APIRouter, HTTPException

from models.agent_schemas import AgentSchemaBundle

router = APIRouter(prefix="/agent", tags=["Agent"])


@router.get("/schema", response_model=AgentSchemaBundle, include_in_schema=True)
async def schema_carrier():
    """Never served: registering this response model puts every card and event variant into the OpenAPI
    components, which `openapi-typescript` turns into the frontend's types."""
    raise HTTPException(status_code=501, detail="Schema carrier only — see /openapi.json")
