from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException

from config import get_settings
from models.agent_schemas import ScenarioRequest, ScenarioResponse
from services.agent.cards import model_facts
from services.juris import is_juris_loaded
from services.scenario import run_scenarios
from models.schemas import (
    SearchResult,
    JurisComparison,
    SimulationRequest,
    SimulationResponse,
    SimulationResult,
    StatusResponse,
)
from services.juris import juris_to_simulation_result
from services.outcome_pipeline import score_case
from services.precedent_filter import decision_before
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/simulation", tags=["Simulation"])

_VALID_PRIMARY = {"juris", "heuristic"}


@router.get("/", response_model=StatusResponse)
async def simulation_status():
    """Check simulation module status."""
    return {"status": "ok", "module": "simulation"}


@router.post("/predict", response_model=SimulationResponse)
async def predict(request: SimulationRequest):
    """
    Predict a judicial outcome for the petitioner based on a
    StructuredCaseProfile, optional precedents, and optional graph stats.

    Returns an explainable score breakdown — every component is transparent.
    """
    logger.info(
        f"Predicting outcome: {len(request.case_profile.legal_issues)} issues, "
        f"{len(request.case_profile.ipc_sections)} sections, "
        f"{len(request.precedents)} precedents, "
        f"graph_stats={'yes' if request.graph_stats else 'no'}, "
        f"appellant_type={request.appellant_type}"
    )

    if request.filing_date and any(
        not decision_before(item.date, request.filing_date) for item in request.precedents
    ):
        raise HTTPException(status_code=422, detail="Precedents must have a known decision date before the appeal filing date")

    try:
        # Juris reads the case text (or, if none is sent, a thin summary of the profile); the heuristic is computed beside it.
        scored = score_case(
            request.case_profile, request.precedents, request.graph_stats,
            request.appellant_type, request.case_text,
        )
    except Exception as exc:
        logger.error(f"Simulation prediction failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
    heuristic_result: SimulationResult = scored.heuristic
    juris_result = scored.juris

    settings = get_settings()
    primary = settings.JURIS_PRIMARY if settings.JURIS_PRIMARY in _VALID_PRIMARY else "juris"
    if not juris_result.model_loaded:
        # Juris unavailable for any reason — always fall back to
        # the heuristic as primary, regardless of the configured setting.
        primary = "heuristic"

    top_level_result = heuristic_result if primary == "heuristic" else juris_to_simulation_result(juris_result)

    comparison = JurisComparison(
        primary=primary,
        heuristic=heuristic_result,
        juris=juris_result,
    )

    return SimulationResponse(
        result=top_level_result,
        processing_time_ms=0,  # heuristic/model — near-instant
        timestamp=datetime.now(timezone.utc),
        comparison=comparison,
    )


@router.post("/scenario", response_model=ScenarioResponse)
async def scenario(request: ScenarioRequest):
    """
    Re-score a case under hypothetical changes with Juris.

    Each scenario perturbs a real model input (appeal type, supporting facts, statutes, precedent support, court level)
    and is scored by the same code path as the base estimate. Most levers move the estimate by only a point or two —
    the response says so via `effect_class` and `warnings`.
    """
    if not is_juris_loaded():
        raise HTTPException(status_code=503, detail="Juris is not loaded, so scenarios are unavailable.")
    if request.case_profile.case_type != "criminal":
        raise HTTPException(status_code=422, detail="Scenarios are only available for criminal appeals — Juris was trained on those.")
    try:
        precedents = [SearchResult(**p) for p in request.precedents]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Invalid precedents: {exc}")
    base, outcomes, sensitivity, _ = run_scenarios(
        request.case_profile, precedents, request.graph_stats, request.appellant_type,
        request.scenarios, request.include_sensitivity, request.case_text,
    )
    return ScenarioResponse(model=model_facts(), base=base, scenarios=outcomes, sensitivity=sensitivity)
