"""
Card builders: raw engine output -> the frozen wire cards in models/agent_schemas.py.

Pure functions (no I/O) so every honesty rule lives in one testable place:
  - precedents carry a true cosine and never a percent "match"
  - the outcome figure is rounded to 5, named by tier, shown with signed *centred* contributions, and always carries
    the model's real accuracy against its base rate plus caveats
  - the legacy heuristic is attached only as a collapsed "uncalibrated" row
"""

import json
import uuid
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from models.agent_schemas import (
    AppellantType, ArgumentMapCard, CaseInputs, CaseProfileCard, Disclaimer, DocumentCard, Excerpt, ErrorCard,
    ExtractionQuality, ForcedTool, GraphSummary, IndexInfo, InputField, InputOption, LegacyHeuristic, ModelFacts,
    NeedsInputCard, OutcomeCard, OutcomeContribution, OutcomeEstimate, OutcomeInputs, PrecedentFilter, PrecedentHit,
    PrecedentsCard, Provenance, ScenarioBase, ScenarioCard, ScenarioOutcome, SensitivityRow, SourcesCard,
)
from models.schemas import GraphBuildResponse, StructuredCaseProfile
from services.agent.library import LibrarySearch

ENGINE_VERSION = "1"
MODEL_CARD_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "outcome_dataset" / "model" / "model_card.json"

APPELLANT_LABELS = {
    "accused_appeal": "the accused (appealing a conviction)",
    "state_appeal": "the State or complainant (appealing an acquittal)",
    "unclear": "not specified",
}


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def prov(engine: str, ms: int = 0, cached: bool = False, index_version: Optional[str] = None, **inputs: Any) -> Provenance:
    return Provenance(engine=engine, engine_version=ENGINE_VERSION, index_version=index_version, computed_ms=ms,
                      inputs={k: v for k, v in inputs.items() if v is not None}, cached=cached)


@lru_cache(maxsize=1)
def model_card() -> Optional[Dict[str, Any]]:
    try:
        return json.loads(MODEL_CARD_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — the card enriches the outcome view; absence must never break a run
        return None


def model_facts(loaded: bool = True, version: Optional[str] = None) -> ModelFacts:
    card = model_card()
    if not card:
        return ModelFacts(name="Logistic regression (binary)", version=version, loaded=loaded)
    return ModelFacts(
        name=card["model_name"], version=version or card["artifact_sha256"][:8], loaded=loaded,
        n_train=card["trained_on"]["n"], cv_accuracy=card["cv"]["accuracy"],
        baseline_accuracy=card["cv"]["baseline_accuracy"], scope=card["scope"],
    )


# --- case profile ----------------------------------------------------------

def profile_card(card_id: str, profile: StructuredCaseProfile, quality: ExtractionQuality, inputs: CaseInputs,
                 ms: int = 0, cached: bool = False) -> CaseProfileCard:
    petitioner = profile.parties.petitioner or "Petitioner"
    respondent = profile.parties.respondent or "Respondent"
    disclaimer = None
    if quality.quality != "good":
        disclaimer = Disclaimer(
            level="caution",
            text=f"Extraction found {quality.completeness:.0%} of the expected fields (missing: {', '.join(quality.missing) or 'none'}). "
                 "Review the profile against the source before relying on later steps.",
        )
    return CaseProfileCard(
        card_id=card_id, title=f"{petitioner} v. {respondent}",
        subtitle=" · ".join(x for x in (profile.court_level if profile.court_level != "Unknown" else None, profile.case_type.capitalize()) if x),
        profile=profile, extraction=quality, inputs=inputs, disclaimer=disclaimer,
        provenance=prov("rules-extractor", ms, cached),
    )


# --- precedents ------------------------------------------------------------

def precedents_card(card_id: str, search: LibrarySearch, query_source: str, used_for_graph: List[str],
                    ms: int = 0, cached: bool = False) -> PrecedentsCard:
    idx = search.index
    results = [
        PrecedentHit(
            ref=f"P{i}", doc_id=h.doc_id, title=h.title, court=h.court, court_tier=h.court_tier,  # type: ignore[arg-type]
            date=h.date, url=h.url, snippet=h.snippet, cosine=round(h.cosine, 3), band="unranked",
            matched_statutes=h.matched_statutes, source="faiss",
        )
        for i, h in enumerate(search.hits, start=1)
    ]
    note = f"Closest matches among {idx['docs']} indexed judgments — not an exhaustive search and not a statement that any of them supports the case."
    if idx.get("source") != "artifact":
        note = "Only a 3-judgment fixture index is loaded, so these matches are illustrative. " + note
    return PrecedentsCard(
        card_id=card_id, title="Closest matches in the library",
        subtitle=(f"Decided before {search.before_date:%d %b %Y}" if search.before_date else "No date cutoff applied"),
        query=search.query, query_source=query_source,  # type: ignore[arg-type]
        filter=PrecedentFilter(before_date=search.before_date, undated_excluded=search.undated_excluded),
        index=IndexInfo(name=idx["name"], version=str(idx["version"]), docs=idx["docs"], chunks=idx["chunks"]),
        results=results, used_for_graph=used_for_graph,
        disclaimer=Disclaimer(level="info", text=note), provenance=prov("faiss-minilm", ms, cached, str(idx["version"])),
    )


# --- argument map ----------------------------------------------------------

def argument_map_card(card_id: str, graph: Dict[str, Any], ms: int = 0, cached: bool = False) -> ArgumentMapCard:
    resp = GraphBuildResponse(**graph)
    by_type: Dict[str, int] = {}
    for n in resp.nodes:
        by_type[n.type] = by_type.get(n.type, 0) + 1
    summary = GraphSummary(
        issues=by_type.get("ISSUE", 0), claims=by_type.get("CLAIM", 0), evidence=by_type.get("EVIDENCE", 0),
        statutes=by_type.get("STATUTE", 0), precedents=by_type.get("PRECEDENT", 0), weak_claims=len(resp.weak_nodes),
        edge_types=sorted({e.type for e in resp.edges}),
    )
    return ArgumentMapCard(
        card_id=card_id, title="Argument map",
        subtitle=f"{resp.node_count} elements · {resp.edge_count} links · {len(resp.weak_nodes)} claim{'s' if len(resp.weak_nodes) != 1 else ''} lacking evidence",
        graph=resp, summary=summary,
        notes=["Structure derived by rules from the case profile; links show how elements relate, not legal reasoning."],
        disclaimer=Disclaimer(level="info", text="Generated structure — review against the source text. A weak flag means no evidence link was found, not that the claim lacks merit."),
        provenance=prov("graph-rules", ms, cached),
    )


# --- outcome ---------------------------------------------------------------

def round5(p: float) -> int:
    """Nearest 5%, clamped to 5–95 (the same display bounds the legacy simulator used) — false precision is a harm here."""
    return max(5, min(95, int(round(p * 20) * 5)))


def tier_for(p: float) -> tuple:
    if p >= 0.70:
        return "favorable", "Leans toward relief"
    if p >= 0.55:
        return "uncertain", "Somewhat above even odds"
    if p >= 0.45:
        return "uncertain", "Roughly even odds"
    if p >= 0.30:
        return "unfavorable", "Below even odds"
    return "unfavorable", "Well below even odds"


def centred_contributions(ml: Any) -> List[OutcomeContribution]:
    """Signed log-odds contributions relative to a typical training case: coef * (x - training mean).

    The raw model contributions are relative to zero, which makes a common feature (e.g. 'argument completeness' = 1.0
    for nearly every case) look influential when it is just ordinary. Centring shows what is unusual about THIS case.
    """
    card = model_card()
    out: List[OutcomeContribution] = []
    for fc in ml.feature_contributions:
        contribution = fc.contribution
        if card:
            if fc.feature in card["features"]:
                f = card["features"][fc.feature]
                contribution = f["coef"] * (fc.value - f["mean"])
            elif fc.feature.startswith("appellant_type="):
                key = fc.feature.split("=", 1)[1]
                a = card["appellant"].get(key)
                if a:
                    contribution = a["coef"] * (fc.value - a["share"])
        out.append(OutcomeContribution(
            feature=fc.feature, display_name=fc.display_name, value=round(fc.value, 3),
            contribution=round(contribution, 3), explanation=fc.explanation,
        ))
    # The three appellant one-hots are one decision for the user; show them as a single "Appeal type" bar.
    appellant_rows = [r for r in out if r.feature.startswith("appellant_type=")]
    if appellant_rows:
        active = max(appellant_rows, key=lambda r: r.value)
        merged = OutcomeContribution(
            feature="appellant_type", display_name="Appeal type", value=active.value,
            contribution=round(sum(r.contribution for r in appellant_rows), 3), explanation=active.explanation,
        )
        out = [r for r in out if not r.feature.startswith("appellant_type=")] + [merged]
    out.sort(key=lambda c: abs(c.contribution), reverse=True)
    return out


def drivers_summary(contribs: List[OutcomeContribution], appellant: AppellantType) -> str:
    if not contribs:
        return ""
    top = contribs[0]
    if top.feature == "appellant_type":
        who = {"accused_appeal": "the accused", "state_appeal": "the State or complainant", "unclear": "an unspecified appellant"}[appellant]
        return f"This estimate mostly reflects who is appealing ({who}); the facts extracted from the case move it by only a few points."
    direction = "up" if top.contribution > 0 else "down"
    return f"The biggest single push is {top.display_name.lower()}, moving the estimate {direction}; who is appealing still matters more than any case-specific input."


def outcome_card(card_id: str, scored: Any, appellant: AppellantType, filing_date: Optional[date],
                 profile_method: Optional[str], ms: int = 0, cached: bool = False, appellant_source: str = "user_input") -> OutcomeCard:
    ml = scored.ml
    p = float(ml.probabilities.get("succeeds", 0.0))
    tier, label = tier_for(p)
    contribs = centred_contributions(ml)
    facts = model_facts(ml.model_loaded, ml.model_version)
    caveats = [
        "Appeal type is the dominant input; the other inputs are counts and averages from the case profile, not legal merit.",
        "Trained on judgments whose outcome labels were derived from text, so label noise is part of the accuracy figure.",
    ]
    if profile_method and profile_method != "rules":
        caveats.append("The profile was improved with AI extraction; the model was trained on rule-extracted profiles, so treat this as less reliable.")
    base = model_card()["baseline_p"] if model_card() else None
    return OutcomeCard(
        card_id=card_id, title="Indicative outcome estimate",
        subtitle=f"Appeal by {APPELLANT_LABELS[appellant]}" if appellant != "unclear" else "Appeal type not specified",
        estimate=OutcomeEstimate(p_succeeds=round(p, 4), p_rounded=round5(p), tier=tier, tier_label=label),  # type: ignore[arg-type]
        inputs=OutcomeInputs(appellant_type=appellant, filing_date=filing_date, appellant_source=appellant_source),  # type: ignore[arg-type]
        model=facts, contributions=contribs, drivers_summary=drivers_summary(contribs, appellant),
        strengths=list(ml.key_strengths[:3]), weaknesses=list(ml.key_weaknesses[:3]),
        legacy=LegacyHeuristic(p=round(scored.heuristic.win_probability, 4)),
        caveats=caveats, profile_method=profile_method,
        disclaimer=Disclaimer(
            level="caution",
            text=("Indicative research estimate" + (f" — a typical case in the training data sits near {round5(base)}%" if base else "")
                  + (f". Trained on {facts.n_train} appellate judgments; cross-validated accuracy {facts.cv_accuracy:.0%} against a {facts.baseline_accuracy:.0%} base rate." if facts.n_train else "")
                  + " Not legal advice."),
        ),
        provenance=prov("logreg-binary", ms, cached, appellant_type=appellant),
    )


# --- scenarios -------------------------------------------------------------

def scenario_card(card_id: str, base: ScenarioBase, scenarios: List[ScenarioOutcome],
                  sensitivity: List[SensitivityRow], ms: int = 0) -> ScenarioCard:
    return ScenarioCard(
        card_id=card_id, title="Scenario comparison",
        subtitle=f"{len(scenarios)} scenario{'s' if len(scenarios) != 1 else ''} against the base estimate",
        model=model_facts(), base=base, scenarios=scenarios, sensitivity=sensitivity,
        disclaimer=Disclaimer(
            level="caution",
            text="This shows how the research model responds to changed inputs. It is not a prediction that changing these facts would change the real outcome.",
        ),
        provenance=prov("logreg-binary", ms),
    )


# --- sources / input / document / error ------------------------------------

def sources_card(card_id: str, question: str, excerpts: List[Dict[str, Any]], method: str = "generated") -> SourcesCard:
    return SourcesCard(
        card_id=card_id, title="Sources in the document", subtitle=f"{len(excerpts)} excerpt{'s' if len(excerpts) != 1 else ''}",
        question=question, method=method,  # type: ignore[arg-type]
        excerpts=[Excerpt(**e) for e in excerpts],
        coverage=None if excerpts else "No passage in this document matched the question.",
        provenance=prov("doc-retrieval"),
    )


def needs_input_card(pending: ForcedTool, need_appellant: bool, need_date: bool, reason: str) -> NeedsInputCard:
    fields: List[InputField] = []
    if need_appellant:
        fields.append(InputField(
            name="appellant_type", kind="select", label="Who is bringing this appeal?", required=True,
            options=[
                InputOption(value="accused_appeal", label="The accused (appealing a conviction)"),
                InputOption(value="state_appeal", label="The State or complainant (appealing an acquittal)"),
                InputOption(value="unclear", label="Not sure"),
            ],
        ))
    if need_date:
        fields.append(InputField(name="filing_date", kind="date", label="Date the appeal was filed", required=True))
    return NeedsInputCard(
        card_id=new_id("input"), title="Two details needed" if len(fields) == 2 else "One detail needed",
        reason=reason, pending=pending, fields=fields,
        hint="We never infer the appeal type — it is the strongest factor in the model. The filing date sets the precedent cutoff: only judgments decided before it are used.",
    )


def document_card(case_id: str, title: str, filename: Optional[str], word_count: int, source: str, preview: str,
                  extraction: Optional[ExtractionQuality]) -> DocumentCard:
    return DocumentCard(
        card_id=new_id("doc"), title=title or filename or "Untitled matter", case_id=case_id, filename=filename,
        word_count=word_count, source=source, preview=preview[:240], extraction=extraction,  # type: ignore[arg-type]
    )


def error_card(code: str, message: str, retryable: bool = False, retry: Optional[ForcedTool] = None,
               technical: Optional[str] = None, title: Optional[str] = None) -> ErrorCard:
    return ErrorCard(card_id=new_id("err"), title=title or "Something went wrong", code=code, message=message,
                     retryable=retryable, retry=retry, technical=technical)
