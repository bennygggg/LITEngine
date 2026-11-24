"""
Scenario engine — "what would Juris say if this input were different?"

Juris reads the pre-reasoning case text and who is appealing, so only changes to those are real levers:

    appellant_type            who is bringing the appeal
    add_sections / remove_sections   statute sections cited in the case (applied by editing the text Juris reads)

The levers of the earlier five-score model (resolved weak claims, extra supporting facts, precedent support, court level) are
not inputs to Juris. They are reported as `rejected` with that reason, never silently ignored. Every scenario is re-scored by
exactly the code path that produced the base estimate (services/outcome_pipeline.score_case), so base and scenario are
comparable by construction. Nothing here invents effect sizes, and the engine says when a change barely moves the estimate.
"""

import re
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from models.agent_schemas import (
    AppliedLever, FeatureDelta, ScenarioBase, ScenarioChanges, ScenarioOutcome, ScenarioSpec, SensitivityRow,
)
from models.schemas import Parties, SearchResult, StructuredCaseProfile
from services.juris import prepare_text, profile_to_text
from services.juris_features import _SECTION_GROUP, extract_sections
from services.outcome_pipeline import ScoredCase, score_case

MAX_SECTIONS = 12
NOT_A_JURIS_INPUT = "Juris does not use this input: it reads the case text and who is appealing."
_SECTION = re.compile(r"^\s*(?:sec(?:tion)?\.?\s*)?(\d{1,3}[A-Za-z]?)(?:\s*\(\w+\))?(?:\s+(?:of\s+the\s+)?[A-Za-z. ]{2,30})?\s*$", re.I)


def _section_number(text: str) -> Optional[str]:
    m = _SECTION.match(text)
    return m.group(1).upper() if m else None


def _effect_class(delta_pp: float) -> str:
    a = abs(delta_pp)
    return "large" if a >= 10 else "small" if a >= 1 else "negligible"


def _contrib_map(juris: Any) -> Dict[str, float]:
    return {fc.feature: fc.contribution for fc in juris.feature_contributions}


def add_section_to_text(text: str, num: str) -> str:
    return f"{text.rstrip()}\nSection {num}."


def remove_section_from_text(text: str, num: str) -> str:
    """Drop one section number from every 'Section(s) ...' citation group; a group left with no number disappears."""
    pat = re.compile(rf"(?<![0-9A-Za-z]){re.escape(num)}[A-Za-z]?(?:\s*\([0-9a-z]{{1,3}}\))*(?![0-9A-Za-z])", re.I)

    def repl(m: "re.Match[str]") -> str:
        prefix = m.string[m.start():m.start(1)]
        rest = pat.sub("", m.group(1))
        return prefix + rest if re.search(r"\d", rest) else ""

    return _SECTION_GROUP.sub(repl, text)


def apply_changes(
    profile: StructuredCaseProfile, precedents: List[SearchResult], graph_stats: Optional[Dict[str, Any]],
    appellant: str, changes: ScenarioChanges, read_text: str,
) -> Tuple[StructuredCaseProfile, List[SearchResult], Optional[Dict[str, Any]], str, str, List[AppliedLever]]:
    """Return modified copies plus a log of what was applied, clamped or rejected (and why)."""
    p = profile.model_copy(deep=True)
    gs = deepcopy(graph_stats) if graph_stats else None
    appellant_out, text = appellant, read_text
    log: List[AppliedLever] = []

    if changes.appellant_type and changes.appellant_type != appellant:
        appellant_out = changes.appellant_type
        log.append(AppliedLever(lever="appellant_type", value=appellant_out, status="applied"))

    cited = set(extract_sections(text))
    for raw in changes.add_sections:
        num = _section_number(raw)
        if not num:
            log.append(AppliedLever(lever="add_section", value=raw, status="rejected", note="Not recognised as a section reference."))
        elif num in cited:
            log.append(AppliedLever(lever="add_section", value=raw, status="rejected", note="Already cited in the case text."))
        elif len(cited) >= MAX_SECTIONS:
            log.append(AppliedLever(lever="add_section", value=raw, status="clamped", note=f"At most {MAX_SECTIONS} sections are counted."))
        else:
            text = add_section_to_text(text, num)
            cited.add(num)
            p.ipc_sections.append(f"Section {num}")
            log.append(AppliedLever(lever="add_section", value=f"Section {num}", status="applied"))

    for raw in changes.remove_sections:
        num = _section_number(raw)
        if num and num in cited:
            text = remove_section_from_text(text, num)
            cited.discard(num)
            p.ipc_sections = [s for s in p.ipc_sections if _section_number(s) != num]
            log.append(AppliedLever(lever="remove_section", value=raw, status="applied"))
        else:
            log.append(AppliedLever(lever="remove_section", value=raw, status="rejected", note="That section is not cited in the case text."))

    for node_id in changes.resolved_weak_claim_ids:
        log.append(AppliedLever(lever="resolved_weak_claim", value=node_id, status="rejected", note=NOT_A_JURIS_INPUT))
    if changes.extra_supporting_facts:
        log.append(AppliedLever(lever="extra_supporting_facts", value=changes.extra_supporting_facts, status="rejected", note=NOT_A_JURIS_INPUT))
    for ref in changes.exclude_precedent_refs:
        log.append(AppliedLever(lever="exclude_precedent", value=ref, status="rejected", note=NOT_A_JURIS_INPUT))
    if changes.court_level:
        log.append(AppliedLever(lever="court_level", value=changes.court_level, status="rejected",
                                note="Juris is trained on High Court criminal appeals and does not use the court as an input."))

    return p, list(precedents), gs, appellant_out, text, log


def _feature_deltas(base: ScoredCase, scen: ScoredCase, appellant_from: str, appellant_to: str) -> List[FeatureDelta]:
    cb, cs = _contrib_map(base.juris), _contrib_map(scen.juris)
    rows: List[Tuple[str, str, Any, Any, float]] = []
    if appellant_from != appellant_to:
        delta = sum(cs.get(k, 0.0) - cb.get(k, 0.0) for k in set(cb) | set(cs) if k.startswith("appellant_type="))
        rows.append(("appellant_type", "Appeal type", appellant_from, appellant_to, delta))
    for feat in sorted(k for k in set(cb) | set(cs) if k.startswith("section_")):
        d = cs.get(feat, 0.0) - cb.get(feat, 0.0)
        if abs(d) > 1e-9:
            num = feat.split("_", 1)[1]
            rows.append((feat, f"Section {num} cited", "cited" if abs(cb.get(feat, 0.0)) > 1e-9 else "not cited",
                         "cited" if abs(cs.get(feat, 0.0)) > 1e-9 else "not cited", d))
    total = sum(abs(r[4]) for r in rows) or 1.0
    out = [
        FeatureDelta(feature=f, display_name=name, from_value=a, to_value=b, logit_delta=round(d, 4), share_of_change=round(abs(d) / total, 3))
        for f, name, a, b, d in rows
    ]
    out.sort(key=lambda x: x.share_of_change, reverse=True)
    return out


def _warnings(deltas: List[FeatureDelta], applied: List[AppliedLever], delta_pp: float) -> List[str]:
    notes: List[str] = []
    took_effect = any(a.status in ("applied", "clamped") for a in applied)
    if not took_effect:
        notes.append("None of the requested changes could be applied, so the estimate is unchanged.")
    elif not deltas:
        notes.append("The change was applied but left every Juris input unchanged, so the estimate did not move.")
    elif abs(delta_pp) < 1:
        notes.append("Juris is nearly insensitive to this change: the estimate moves by less than a point.")
    if any(a.lever.endswith("section") and a.status == "applied" for a in applied):
        notes.append("Editing a cited section changes the text Juris reads; it is a what-if on the model, not a prediction that the charge would change.")
    return list(dict.fromkeys(notes))


def _blank_profile() -> StructuredCaseProfile:
    return StructuredCaseProfile(parties=Parties(petitioner=None, respondent=None))


def _p(appellant: str, text: str) -> float:
    return float(score_case(_blank_profile(), [], None, appellant, text, pre_cut=True).juris.probabilities.get("succeeds", 0.0))


def sensitivity_table(base: ScoredCase, appellant: str, read_text: str) -> List[SensitivityRow]:
    """One-at-a-time swings: the three appeal types, and removing each cited section Juris has a learned weight for."""
    ps = {app: _p(app, read_text) for app in ("accused_appeal", "state_appeal", "unclear")}
    rows = [SensitivityRow(feature="appellant_type", display_name="Appeal type", p_at_low=round(min(ps.values()), 4),
                           p_at_high=round(max(ps.values()), 4), swing_pp=round((max(ps.values()) - min(ps.values())) * 100, 1),
                           kind="categorical", confounded=False, note="Accused's appeal vs State's appeal vs not specified.")]
    base_p = float(base.juris.probabilities.get("succeeds", 0.0))
    for feat in [c.feature for c in base.juris.feature_contributions if c.feature.startswith("section_") and abs(c.contribution) > 1e-9][:5]:
        num = feat.split("_", 1)[1]
        p = _p(appellant, remove_section_from_text(read_text, num))
        rows.append(SensitivityRow(feature=feat, display_name=f"Section {num} cited", p_at_low=round(min(base_p, p), 4), p_at_high=round(max(base_p, p), 4),
                                   swing_pp=round(abs(base_p - p) * 100, 1), kind="categorical", confounded=False,
                                   note="Effect of removing this section from the text Juris reads."))
    rows.sort(key=lambda r: r.swing_pp, reverse=True)
    return rows


def run_scenarios(
    profile: StructuredCaseProfile, precedents: List[SearchResult], graph_stats: Optional[Dict[str, Any]],
    appellant_type: str, specs: List[ScenarioSpec], include_sensitivity: bool = True, case_text: Optional[str] = None,
) -> Tuple[ScenarioBase, List[ScenarioOutcome], List[SensitivityRow], bool]:
    """Returns (base, scenarios, sensitivity, model_loaded). Scenarios edit the text Juris actually reads (after its pre-reasoning cut)."""
    has_text = bool(case_text and case_text.strip())
    read_text = prepare_text(case_text)[0] if has_text else profile_to_text(profile)
    base = score_case(profile, precedents, graph_stats, appellant_type, read_text, pre_cut=True)
    base_p = float(base.juris.probabilities.get("succeeds", 0.0))
    base_out = ScenarioBase(p_succeeds=round(base_p, 4), appellant_type=appellant_type,  # type: ignore[arg-type]
                            features={"words_read": float(base.juris.words_read or 0)})
    outcomes: List[ScenarioOutcome] = []
    for i, spec in enumerate(specs):
        p, precs, gs, app, text_s, log = apply_changes(profile, precedents, graph_stats, appellant_type, spec.changes, read_text)
        scen = score_case(p, precs, gs, app, text_s, pre_cut=True)
        p_s = float(scen.juris.probabilities.get("succeeds", 0.0))
        deltas = _feature_deltas(base, scen, appellant_type, app)
        delta_pp = round((p_s - base_p) * 100, 1)
        outcomes.append(ScenarioOutcome(
            id=spec.id or f"s{i + 1}", label=spec.label, applied=log, p_succeeds=round(p_s, 4), delta_pp=delta_pp,
            feature_deltas=deltas, dominant_feature=deltas[0].feature if deltas else None,
            effect_class=_effect_class(delta_pp), warnings=_warnings(deltas, log, delta_pp),  # type: ignore[arg-type]
        ))
    sens = sensitivity_table(base, appellant_type, read_text) if include_sensitivity and base.juris.model_loaded else []
    return base_out, outcomes, sens, base.juris.model_loaded
