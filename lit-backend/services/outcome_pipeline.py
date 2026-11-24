"""
One place that turns (profile, case text, appellant type) into both outcome estimates.

The `/simulation/predict` route, the agent's `assess_outcome` tool and the scenario engine all call this, so the base
estimate and every scenario are produced by exactly the same code path and are comparable by construction.

Juris reads the case text. The five-score heuristic (services/simulator.py) is still computed: it is the fallback when Juris
is not loaded and the "earlier rule-based score" comparison on the card.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from models.schemas import JurisResult, SearchResult, SimulationResult, StructuredCaseProfile
from services.juris import predict_juris, profile_to_text
from services.simulator import predict_outcome

# services/simulator.py's ScoreComponent.component strings -> the heuristic's feature keys (display only)
COMPONENT_NAME_TO_FEATURE_KEY: Dict[str, str] = {
    "Precedent Alignment": "precedent_alignment",
    "Statutory Strength": "statutory_strength",
    "Argument Completeness": "argument_completeness",
    "Case Complexity": "case_complexity",
    "Court Level": "court_level",
}


@dataclass
class ScoredCase:
    heuristic: SimulationResult
    juris: JurisResult
    raw_scores: Dict[str, float]


def score_case(
    profile: StructuredCaseProfile,
    precedents: Optional[List[SearchResult]],
    graph_stats: Optional[Dict[str, Any]],
    appellant_type: str,
    case_text: Optional[str] = None,
    pre_cut: bool = False,
) -> ScoredCase:
    """Heuristic first (fallback and comparison row), then Juris on the case text (or a thin profile summary if none is given)."""
    heuristic = predict_outcome(profile=profile, precedents=precedents or [], graph_stats=graph_stats)
    raw_scores = {
        COMPONENT_NAME_TO_FEATURE_KEY[sc.component]: sc.raw_score
        for sc in heuristic.score_breakdown
        if sc.component in COMPONENT_NAME_TO_FEATURE_KEY
    }
    if case_text and case_text.strip():
        juris = predict_juris(case_text, appellant_type, input_basis="case_text", pre_cut=pre_cut)
    else:
        juris = predict_juris(profile_to_text(profile), appellant_type, input_basis="profile_summary")
    return ScoredCase(heuristic=heuristic, juris=juris, raw_scores=raw_scores)
