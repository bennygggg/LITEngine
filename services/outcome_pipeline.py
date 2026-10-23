"""
One place that turns (profile, precedents, graph stats, appellant type) into both outcome estimates.

The `/simulation/predict` route, the agent's `assess_outcome` tool and the scenario engine all call this, so the
base estimate and every scenario are produced by exactly the same code path and are comparable by construction.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from models.schemas import MLModelResult, SearchResult, SimulationResult, StructuredCaseProfile
from services.outcome_model import COMPONENT_NAME_TO_FEATURE_KEY, predict_ml_outcome
from services.simulator import predict_outcome


@dataclass
class ScoredCase:
    heuristic: SimulationResult
    ml: MLModelResult
    raw_scores: Dict[str, float]


def score_case(
    profile: StructuredCaseProfile,
    precedents: Optional[List[SearchResult]],
    graph_stats: Optional[Dict[str, Any]],
    appellant_type: str,
    filing_date_provided: bool = False,
) -> ScoredCase:
    """Heuristic score first (its five component scores are the model's inputs), then the trained model."""
    heuristic = predict_outcome(profile=profile, precedents=precedents or [], graph_stats=graph_stats)
    raw_scores = {
        COMPONENT_NAME_TO_FEATURE_KEY[sc.component]: sc.raw_score
        for sc in heuristic.score_breakdown
        if sc.component in COMPONENT_NAME_TO_FEATURE_KEY
    }
    extraction_method = profile.metadata.extraction_method if profile.metadata else None
    ml = predict_ml_outcome(raw_scores, appellant_type, extraction_method, filing_date_provided)
    return ScoredCase(heuristic=heuristic, ml=ml, raw_scores=raw_scores)
