"""Unit tests: routing, never-infer parsing, chunker offsets, artifact integrity, scenario engine, honesty maths."""

import json
import math
import shutil
from datetime import date

import pytest

from models.agent_schemas import ScenarioChanges, ScenarioSpec
from models.schemas import Parties, StructuredCaseProfile
from services.agent import cards
from services.agent.doc_index import chunk_with_offsets
from services.agent.library import clean_snippet, clean_title, court_tier, statutes_mentioned
from services.agent.routing import parse_explicit_appellant, parse_explicit_date, route, scenario_specs
from services.outcome_pipeline import score_case
from services.retrieval.artifact import load_artifact
from services.scenario import run_scenarios


def profile(**kw) -> StructuredCaseProfile:
    base = dict(parties=Parties(petitioner="A", respondent="State"), legal_issues=["a?", "b?", "c?"],
                ipc_sections=["Section 302", "Section 34"], acts_referenced=["Indian Penal Code, 1860"],
                court_level="High Court", case_type="criminal", key_facts=["f1", "f2", "f3", "f4"], relief_sought="set aside")
    base.update(kw)
    return StructuredCaseProfile(**base)


GRAPH = {"node_count": 14, "weak_nodes": []}


# --- routing: every prompt the LLM probe showed models getting wrong -----------------

@pytest.mark.parametrize("text,tool", [
    ("Give me a quick summary of the facts and parties.", "extract_case_facts"),
    ("Who are the parties and which court is this?", "extract_case_facts"),
    ("Find precedents on delay in lodging an FIR.", "search_precedents"),
    ("Which Supreme Court judgments are closest to this appeal?", "search_precedents"),
    ("Map out the arguments and show me where the claims are weak.", "build_argument_map"),
    ("Estimate the chances of success.", "assess_outcome"),
    ("Is case me appeal ke chances kya hain? Main accused hoon.", "assess_outcome"),
    ("What if the State were the appellant instead?", "run_scenario"),
    ("What if we got an independent witness to corroborate PW-1?", "run_scenario"),
    ("Compare outcomes if the State appeals versus if the accused appeals.", "run_scenario"),
    ("What does the judgment say about the recovery of the weapon?", "ask_case"),
    ("Did the trial court discuss the delay in the FIR?", "ask_case"),
    ("Do a full review of this case.", "full_review"),
])
def test_tier1_routes_the_probe_prompts(text, tool):
    r = route(text, has_case=True)
    assert r.kind == "tools" and r.tools[0].name == tool


def test_greeting_routes_to_help():
    assert route("Hi, what can you do?", True).kind == "help"


# --- never infer ---------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Estimate the chances of success.", None),
    ("The appellant was convicted under Section 302", None),            # case-text style language is not a statement
    ("I'm the accused, what are my chances?", "accused_appeal"),
    ("This is the State's appeal against acquittal", "state_appeal"),
    ("We represent the accused", "accused_appeal"),
    ("accused's appeal and the State's appeal", None),                  # contradictory -> don't guess
])
def test_parse_explicit_appellant_is_conservative(text, expected):
    assert parse_explicit_appellant(text) == expected


def test_parse_explicit_date():
    assert parse_explicit_date("filed on 2021-04-12 before the HC") == "2021-04-12"
    assert parse_explicit_date("filed last April") is None


def test_scenario_specs_split_levers_with_descriptive_labels():
    specs = scenario_specs({"appellant_type": "state_appeal", "extra_supporting_facts": 2})
    assert [s["label"] for s in specs] == ["If the State were the appellant", "With 2 more supporting facts"]
    assert specs[0]["changes"] == {"appellant_type": "state_appeal"}


# --- chunker -------------------------------------------------------------------------

def test_chunk_offsets_round_trip_and_cover_the_text():
    text = " ".join(f"Sentence number {i} says something about the appeal." for i in range(120))
    chunks = chunk_with_offsets(text, words=40, overlap=8)
    assert all(text[c.char_start:c.char_end] == c.text for c in chunks)
    assert chunks[0].char_start == 0 and chunks[-1].char_end == len(text)
    assert all(len(c.text.split()) <= 40 for c in chunks)
    assert all(a.char_start < b.char_start for a, b in zip(chunks, chunks[1:]))


def test_chunks_prefer_sentence_boundaries_and_ignore_abbreviations():
    text = ("Mr. Sharma appeared in Crl. A. No. 482 of 2021 before the court. " * 4 + "The court held that the delay was fatal. ") * 6
    chunks = chunk_with_offsets(text, words=60, overlap=10)
    assert all(c.text.rstrip().endswith(".") for c in chunks[:-1])


def test_empty_text_yields_no_chunks():
    assert chunk_with_offsets("   ") == []


# --- library helpers -----------------------------------------------------------------

def test_title_snippet_and_tier_cleaning():
    assert clean_title("6) Sk. Aziz vs The State on 24 December, 2010") == "Sk. Aziz vs The State"
    assert clean_snippet("[Cites 60 , Cited by 0 ] Supreme Court of India Foo vs Bar on 1 Jan, 2020 " + "x " * 300).endswith("…")
    assert court_tier("Supreme Court of India") == "SC" and court_tier("Kerala High Court") == "HC" and court_tier("Delhi District Court") == "other"
    assert statutes_mentioned("conviction under Section 302 and s. 34", ["Section 302", "Section 34", "Section 420"]) == ["Section 302", "Section 34"]


# --- artifact integrity --------------------------------------------------------------

def test_artifact_loader_rejects_tampering(tmp_path):
    import os
    src = os.environ["PRECEDENT_ARTIFACT_DIR"]
    good = tmp_path / "good"
    shutil.copytree(src, good)
    assert len(load_artifact(good).metadata) == 6
    with open(good / "meta.jsonl", "a", encoding="utf-8") as f:
        f.write('{"doc_id": "evil"}\n')
    with pytest.raises(ValueError, match="hash"):
        load_artifact(good)


def test_artifact_loader_requires_a_manifest(tmp_path):
    with pytest.raises(ValueError, match="manifest"):
        load_artifact(tmp_path)


# --- scenario engine -----------------------------------------------------------------

def run(specs, appellant="accused_appeal", prof=None, graph=GRAPH):
    return run_scenarios(prof or profile(), [], graph, appellant, specs)


def spec(label, **changes):
    return ScenarioSpec(label=label, changes=ScenarioChanges(**changes))


def test_appellant_swing_is_large_and_in_the_right_direction():
    base, [o], _, loaded = run([spec("state", appellant_type="state_appeal")])
    assert loaded and o.effect_class == "large" and o.delta_pp < -20 and o.dominant_feature == "appellant_type"
    base2, [o2], _, _ = run([spec("accused", appellant_type="accused_appeal")], appellant="state_appeal")
    assert o2.delta_pp > 20


def test_inert_levers_are_reported_negligible_with_an_explanation():
    _, outs, _, _ = run([spec("facts", extra_supporting_facts=3), spec("sections", add_sections=["Section 201", "Section 120B"])])
    assert all(o.effect_class == "negligible" for o in outs)
    assert any("left every model input unchanged" in w or "insensitive" in w for o in outs for w in o.warnings)


def test_levers_that_cannot_apply_are_rejected_not_silently_ignored():
    _, [o], _, _ = run([spec("bad", resolved_weak_claim_ids=["claim:nope"], remove_sections=["999"], exclude_precedent_refs=["P9"],
                             add_sections=["not a section"])])
    assert {a.status for a in o.applied} == {"rejected"}
    assert o.delta_pp == 0 and any("could be applied" in w for w in o.warnings)


def test_section_cap_and_dedupe():
    prof = profile(ipc_sections=[f"Section {n}" for n in range(300, 312)])
    _, [o], _, _ = run([spec("more", add_sections=["Section 400"])], prof=prof)
    assert o.applied[0].status == "clamped"
    _, [o2], _, _ = run([spec("dup", add_sections=["302"])])
    assert o2.applied[0].status == "rejected" and "Already" in (o2.applied[0].note or "")


def test_court_level_lever_is_flagged_as_confounded():
    _, [o], _, _ = run([spec("hc", court_level="Supreme Court")])
    assert any("Confounded" in (a.note or "") for a in o.applied) or any("Confounded" in w for w in o.warnings)


def test_sensitivity_table_ranks_appeal_type_first_and_marks_inert_inputs():
    _, _, sens, _ = run([spec("x", extra_supporting_facts=1)])
    assert sens[0].feature == "appellant_type" and sens[0].swing_pp > 20
    completeness = next(r for r in sens if r.feature == "argument_completeness")
    assert completeness.swing_pp == 0 and "No variation" in (completeness.note or "")
    assert next(r for r in sens if r.feature == "court_level").confounded


def test_base_estimate_equals_the_simulation_path():
    scored = score_case(profile(), [], GRAPH, "accused_appeal")
    base, _, _, _ = run([spec("noop")])
    assert base.p_succeeds == pytest.approx(scored.ml.probabilities["succeeds"], abs=1e-4)


# --- honesty maths -------------------------------------------------------------------

def test_round5_is_clamped_and_multiples_of_five():
    assert [cards.round5(p) for p in (0.0, 0.02, 0.37, 0.5, 0.74, 0.99, 1.0)] == [5, 5, 35, 50, 75, 95, 95]


def test_tiers_are_ordered_and_named_plainly():
    assert cards.tier_for(0.75) == ("favorable", "Leans toward relief")
    assert cards.tier_for(0.50)[0] == "uncertain" and cards.tier_for(0.33) == ("unfavorable", "Below even odds")
    assert cards.tier_for(0.1)[1] == "Well below even odds"


@pytest.mark.parametrize("appellant", ["accused_appeal", "state_appeal", "unclear"])
def test_centred_contributions_sum_to_logit_minus_baseline(appellant):
    """The bars are only honest if they add up: baseline logit + sum(centred contributions) == the model's logit."""
    card = cards.model_card()
    assert card, "model_card.json must ship with the model"
    scored = score_case(profile(), [], GRAPH, appellant)
    total = sum(c.contribution for c in cards.centred_contributions(scored.ml))
    p = scored.ml.probabilities["succeeds"]
    logit = math.log(p / (1 - p))
    assert card["baseline_logit"] + total == pytest.approx(logit, abs=0.02)


def test_drivers_summary_names_appeal_type_as_the_driver():
    scored = score_case(profile(), [], GRAPH, "accused_appeal")
    text = cards.drivers_summary(cards.centred_contributions(scored.ml), "accused_appeal")
    assert "who is appealing" in text and "the accused" in text


def test_outcome_card_flags_ai_improved_profiles():
    scored = score_case(profile(), [], GRAPH, "accused_appeal")
    card = cards.outcome_card("k", scored, "accused_appeal", date(2021, 4, 12), "llm_assisted")
    assert any("less reliable" in c for c in card.caveats)
    plain = cards.outcome_card("k", scored, "accused_appeal", date(2021, 4, 12), "rules")
    assert not any("less reliable" in c for c in plain.caveats)
