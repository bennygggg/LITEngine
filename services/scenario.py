"""
Scenario engine — "what would the research model say if this input were different?"

Each lever changes a real input of the trained outcome model, then the case is re-scored by exactly the code path
that produced the base estimate (services/outcome_pipeline.score_case), so base and scenario are comparable by
construction. Nothing here invents effect sizes: the model is mostly a base-rate indicator by appeal type, so most
levers move the estimate by only a point or two — and the engine says so (effect_class, warnings, sensitivity table).
"""

import re
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from models.agent_schemas import (
    AppliedLever, FeatureDelta, ScenarioBase, ScenarioChanges, ScenarioOutcome, ScenarioSpec, SensitivityRow,
)
from models.schemas import SearchResult, StructuredCaseProfile
from services.agent.cards import model_card
from services.outcome_model import FEATURE_DISPLAY_NAMES, FEATURE_ORDER, predict_ml_outcome
from services.outcome_pipeline import ScoredCase, score_case

MAX_SECTIONS = 12
_SECTION = re.compile(r"^\s*(?:sec(?:tion)?\.?\s*)?(\d{1,3}[A-Za-z]?)(?:\s*\(\w+\))?(?:\s+(?:of\s+the\s+)?[A-Za-z. ]{2,30})?\s*$", re.I)
COURT_LEVELS = ("Supreme Court", "High Court", "District Court")
# Features the model card shows to be (nearly) inert, or whose effect is confounded in the training data.
CONFOUNDED = {"court_level": "Confounded in the training data (leave-granted appeals reach higher courts); not a strategy lever."}
CORRELATIONAL = {"case_complexity": "Correlational only: pressing fewer grounds is not advice to raise the odds."}


def _section_number(text: str) -> Optional[str]:
    m = _SECTION.match(text)
    return m.group(1).upper() if m else None


def _num_of(existing: str) -> Optional[str]:
    m = re.search(r"(\d{1,3}[A-Za-z]?)", existing)
    return m.group(1).upper() if m else None


def _effect_class(delta_pp: float) -> str:
    a = abs(delta_pp)
    return "large" if a >= 10 else "small" if a >= 1 else "negligible"


def _contrib_map(ml: Any) -> Dict[str, float]:
    return {fc.feature: fc.contribution for fc in ml.feature_contributions}


def apply_changes(
    profile: StructuredCaseProfile, precedents: List[SearchResult], graph_stats: Optional[Dict[str, Any]],
    appellant: str, changes: ScenarioChanges,
) -> Tuple[StructuredCaseProfile, List[SearchResult], Optional[Dict[str, Any]], str, List[AppliedLever]]:
    """Return modified copies plus a log of what was applied, clamped or rejected (and why)."""
    p = profile.model_copy(deep=True)
    precs = list(precedents)
    gs = deepcopy(graph_stats) if graph_stats else None
    appellant_out = appellant
    log: List[AppliedLever] = []

    if changes.appellant_type and changes.appellant_type != appellant:
        appellant_out = changes.appellant_type
        log.append(AppliedLever(lever="appellant_type", value=appellant_out, status="applied"))

    if changes.resolved_weak_claim_ids:
        weak = list((gs or {}).get("weak_nodes", []))
        for node_id in changes.resolved_weak_claim_ids:
            if node_id in weak:
                weak.remove(node_id)
                log.append(AppliedLever(lever="resolved_weak_claim", value=node_id, status="applied"))
            else:
                log.append(AppliedLever(lever="resolved_weak_claim", value=node_id, status="rejected",
                                        note="That claim is not flagged as weak in this map."))
        if gs is not None:
            gs["weak_nodes"] = weak

    if changes.extra_supporting_facts:
        k = min(max(changes.extra_supporting_facts, 0), 5)
        if gs is None:
            log.append(AppliedLever(lever="extra_supporting_facts", value=changes.extra_supporting_facts, status="rejected",
                                    note="No argument map is available to add facts to."))
        else:
            gs["node_count"] = int(gs.get("node_count", 0)) + k
            log.append(AppliedLever(lever="extra_supporting_facts", value=k, status="applied" if k == changes.extra_supporting_facts else "clamped"))

    for raw in changes.add_sections:
        num = _section_number(raw)
        if not num:
            log.append(AppliedLever(lever="add_section", value=raw, status="rejected", note="Not recognised as a section reference."))
        elif any(_num_of(s) == num for s in p.ipc_sections):
            log.append(AppliedLever(lever="add_section", value=raw, status="rejected", note="Already in the profile."))
        elif len(p.ipc_sections) >= MAX_SECTIONS:
            log.append(AppliedLever(lever="add_section", value=raw, status="clamped", note=f"At most {MAX_SECTIONS} sections are counted."))
        else:
            p.ipc_sections.append(f"Section {num}")
            log.append(AppliedLever(lever="add_section", value=f"Section {num}", status="applied"))

    for raw in changes.remove_sections:
        num = _section_number(raw)
        before = len(p.ipc_sections)
        p.ipc_sections = [s for s in p.ipc_sections if _num_of(s) != num] if num else p.ipc_sections
        status = "applied" if len(p.ipc_sections) < before else "rejected"
        log.append(AppliedLever(lever="remove_section", value=raw, status=status,
                                note=None if status == "applied" else "That section is not in the profile."))

    for ref in changes.exclude_precedent_refs:
        m = re.fullmatch(r"P(\d+)", ref.strip().upper())
        idx = int(m.group(1)) - 1 if m else -1
        if 0 <= idx < len(precedents) and precedents[idx] in precs:
            precs.remove(precedents[idx])
            log.append(AppliedLever(lever="exclude_precedent", value=ref.upper(), status="applied"))
        else:
            log.append(AppliedLever(lever="exclude_precedent", value=ref, status="rejected", note="No such precedent in the support set."))

    if changes.court_level:
        p.court_level = changes.court_level
        log.append(AppliedLever(lever="court_level", value=changes.court_level, status="applied",
                                note=CONFOUNDED["court_level"]))

    return p, precs, gs, appellant_out, log


def _feature_deltas(base: ScoredCase, scen: ScoredCase, appellant_from: str, appellant_to: str) -> List[FeatureDelta]:
    cb, cs = _contrib_map(base.ml), _contrib_map(scen.ml)
    rows: List[Tuple[str, Any, Any, float]] = []
    for feat in FEATURE_ORDER:
        rows.append((feat, round(base.raw_scores.get(feat, 0), 3), round(scen.raw_scores.get(feat, 0), 3), cs.get(feat, 0) - cb.get(feat, 0)))
    if appellant_from != appellant_to:
        delta = sum(v - cb.get(k, 0) for k, v in cs.items() if k.startswith("appellant_type="))
        rows.append(("appellant_type", appellant_from, appellant_to, delta))
    total = sum(abs(r[3]) for r in rows) or 1.0
    out = [
        FeatureDelta(
            feature=f, display_name=FEATURE_DISPLAY_NAMES.get(f, f.replace("_", " ").capitalize() if f == "appellant_type" else f),
            from_value=a, to_value=b, logit_delta=round(d, 4), share_of_change=round(abs(d) / total, 3),
        )
        for f, a, b, d in rows if abs(d) > 1e-9 or f == "appellant_type"
    ]
    out.sort(key=lambda x: x.share_of_change, reverse=True)
    return out


def _warnings(deltas: List[FeatureDelta], applied: List[AppliedLever]) -> List[str]:
    card = model_card()
    notes: List[str] = []
    took_effect = any(a.status in ("applied", "clamped") for a in applied)
    if not deltas and not took_effect:
        notes.append("None of the requested changes could be applied, so the estimate is unchanged.")
    elif not deltas:
        notes.append("The change was applied but left every model input unchanged — the relevant input is already saturated "
                     "(e.g. argument completeness is 100% when no claim is flagged weak) or the edits net to zero.")
    for d in deltas:
        if card and d.feature in card["features"]:
            coef = abs(card["features"][d.feature]["coef"])
            if coef < 0.05:
                notes.append(f"The model is nearly insensitive to {d.display_name.lower()} (coefficient {coef:.2f}).")
        if d.feature in CORRELATIONAL:
            notes.append(CORRELATIONAL[d.feature])
        if d.feature in CONFOUNDED:
            notes.append(CONFOUNDED[d.feature])
    return list(dict.fromkeys(notes))


def sensitivity_table(base: ScoredCase, appellant: str) -> List[SensitivityRow]:
    """One-at-a-time swing across each input's range in the training data, others held at this case's values."""
    card = model_card()
    if not card:
        return []
    rows: List[SensitivityRow] = []

    def p_with(raw: Dict[str, float], app: str) -> float:
        return float(predict_ml_outcome(raw, app).probabilities.get("succeeds", 0.0))

    for key, info in card["features"].items():
        lo, hi = info["min"], info["max"]
        if hi - lo < 1e-9:
            rows.append(SensitivityRow(feature=key, display_name=info["display_name"], p_at_low=round(p_with(base.raw_scores, appellant), 4),
                                       p_at_high=round(p_with(base.raw_scores, appellant), 4), swing_pp=0.0, kind="continuous",
                                       confounded=key in CONFOUNDED, note="No variation in the training data, so the model learned nothing about it."))
            continue
        a, b = dict(base.raw_scores, **{key: lo}), dict(base.raw_scores, **{key: hi})
        pa, pb = p_with(a, appellant), p_with(b, appellant)
        rows.append(SensitivityRow(feature=key, display_name=info["display_name"], p_at_low=round(pa, 4), p_at_high=round(pb, 4),
                                   swing_pp=round(abs(pb - pa) * 100, 1), kind="continuous", confounded=key in CONFOUNDED,
                                   note=CONFOUNDED.get(key) or CORRELATIONAL.get(key)))
    ps = {app: p_with(base.raw_scores, app) for app in ("accused_appeal", "state_appeal", "unclear")}
    rows.append(SensitivityRow(feature="appellant_type", display_name="Appeal type", p_at_low=round(min(ps.values()), 4),
                               p_at_high=round(max(ps.values()), 4), swing_pp=round((max(ps.values()) - min(ps.values())) * 100, 1),
                               kind="categorical", confounded=False,
                               note="Accused's appeal vs State's appeal vs not specified."))
    rows.sort(key=lambda r: r.swing_pp, reverse=True)
    return rows


def run_scenarios(
    profile: StructuredCaseProfile, precedents: List[SearchResult], graph_stats: Optional[Dict[str, Any]],
    appellant_type: str, specs: List[ScenarioSpec], include_sensitivity: bool = True,
) -> Tuple[ScenarioBase, List[ScenarioOutcome], List[SensitivityRow], bool]:
    """Returns (base, scenarios, sensitivity, model_loaded)."""
    base = score_case(profile, precedents, graph_stats, appellant_type)
    base_p = float(base.ml.probabilities.get("succeeds", 0.0))
    base_out = ScenarioBase(p_succeeds=round(base_p, 4), appellant_type=appellant_type,  # type: ignore[arg-type]
                            features={k: round(v, 3) for k, v in base.raw_scores.items()})
    outcomes: List[ScenarioOutcome] = []
    for i, spec in enumerate(specs):
        p, precs, gs, app, log = apply_changes(profile, precedents, graph_stats, appellant_type, spec.changes)
        scen = score_case(p, precs, gs, app)
        p_s = float(scen.ml.probabilities.get("succeeds", 0.0))
        deltas = _feature_deltas(base, scen, appellant_type, app)
        delta_pp = round((p_s - base_p) * 100, 1)
        outcomes.append(ScenarioOutcome(
            id=spec.id or f"s{i + 1}", label=spec.label, applied=log, p_succeeds=round(p_s, 4), delta_pp=delta_pp,
            feature_deltas=deltas, dominant_feature=deltas[0].feature if deltas else None,
            effect_class=_effect_class(delta_pp), warnings=_warnings(deltas, log),  # type: ignore[arg-type]
        ))
    sens = sensitivity_table(base, appellant_type) if include_sensitivity else []
    return base_out, outcomes, sens, base.ml.model_loaded
