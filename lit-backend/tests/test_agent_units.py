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

from pathlib import Path  # noqa: E402

CASE = (Path(__file__).parent / "fixtures" / "criminal_case.txt").read_text(encoding="utf-8")


def run(specs, appellant="accused_appeal", prof=None, graph=GRAPH, text=CASE):
    return run_scenarios(prof or profile(), [], graph, appellant, specs, True, text)


def spec(label, **changes):
    return ScenarioSpec(label=label, changes=ScenarioChanges(**changes))


def test_appellant_swing_is_in_the_right_direction():
    base, [o], _, loaded = run([spec("state", appellant_type="state_appeal")])
    assert loaded and o.delta_pp < -5 and o.effect_class in ("large", "small") and o.dominant_feature == "appellant_type"
    base2, [o2], _, _ = run([spec("accused", appellant_type="accused_appeal")], appellant="state_appeal")
    assert o2.delta_pp > 5


def test_cited_section_levers_edit_what_juris_reads():
    _, [o], _, _ = run([spec("add", add_sections=["Section 498A"])])
    assert o.applied[0].status == "applied" and any(w for w in o.warnings if "what-if on the model" in w)
    _, [o2], _, _ = run([spec("remove", remove_sections=["302"])])
    assert o2.applied[0].status == "applied"


def test_levers_that_juris_does_not_use_are_rejected_with_the_reason():
    _, [o], _, _ = run([spec("old levers", resolved_weak_claim_ids=["claim:nope"], extra_supporting_facts=3, exclude_precedent_refs=["P1"],
                             court_level="Supreme Court")])
    assert {a.status for a in o.applied} == {"rejected"} and all(a.note for a in o.applied)
    assert any("does not use" in (a.note or "") for a in o.applied)
    assert o.delta_pp == 0 and o.effect_class == "negligible" and any("could be applied" in w for w in o.warnings)


def test_levers_that_cannot_apply_are_rejected_not_silently_ignored():
    _, [o], _, _ = run([spec("bad", remove_sections=["999"], add_sections=["not a section"])])
    assert {a.status for a in o.applied} == {"rejected"}
    assert o.delta_pp == 0 and any("could be applied" in w for w in o.warnings)


def test_section_cap_and_dedupe():
    crowded = "The appellant was charged under " + ", ".join(f"Section {n}" for n in range(300, 312)) + ". " + CASE
    _, [o], _, _ = run([spec("more", add_sections=["Section 400"])], text=crowded)
    assert o.applied[0].status == "clamped"
    _, [o2], _, _ = run([spec("dup", add_sections=["302"])])
    assert o2.applied[0].status == "rejected" and "Already" in (o2.applied[0].note or "")


def test_sensitivity_table_ranks_appeal_type_among_the_inputs():
    _, _, sens, _ = run([spec("x", appellant_type="state_appeal")])
    assert sens and sens[0].swing_pp >= sens[-1].swing_pp
    appeal = next(r for r in sens if r.feature == "appellant_type")
    assert appeal.swing_pp > 5 and appeal.kind == "categorical"


def test_base_estimate_equals_the_simulation_path():
    scored = score_case(profile(), [], GRAPH, "accused_appeal", CASE)
    base, _, _, _ = run([spec("noop")])
    assert base.p_succeeds == pytest.approx(scored.juris.probabilities["succeeds"], abs=1e-4)


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
    scored = score_case(profile(), [], GRAPH, appellant, CASE)
    total = sum(c.contribution for c in cards.centred_contributions(scored.juris))
    p = scored.juris.probabilities["succeeds"]
    logit = math.log(p / (1 - p))
    assert card["baseline_logit"] + total == pytest.approx(logit, abs=0.02)


def test_drivers_summary_names_appeal_type_as_a_driver():
    scored = score_case(profile(), [], GRAPH, "accused_appeal", CASE)
    text = cards.drivers_summary(cards.centred_contributions(scored.juris), "accused_appeal")
    assert "who is appealing" in text and "the accused" in text


def test_state_appeals_carry_a_base_rate_caveat():
    scored = score_case(profile(), [], GRAPH, "state_appeal", CASE)
    caveats = cards.outcome_card("k", scored, "state_appeal", None, "rules").caveats
    assert any("base rate" in c for c in caveats)
    assert not any("base rate" in c for c in cards.outcome_card("k", score_case(profile(), [], GRAPH, "accused_appeal", CASE), "accused_appeal", None, "rules").caveats)


def test_outcome_card_flags_a_thin_profile_summary_and_carries_the_model_facts():
    full = score_case(profile(), [], GRAPH, "accused_appeal", CASE)
    card = cards.outcome_card("k", full, "accused_appeal", date(2021, 4, 12), "rules")
    assert card.model.name == "Juris" and card.model.n_train and not any("short structured summary" in c for c in card.caveats)
    assert any("never sees the appellate court" in c for c in card.caveats)
    thin = score_case(profile(key_facts=["f " * 30] * 3), [], GRAPH, "accused_appeal")      # no case text: a summary built from the profile
    if thin.juris.model_loaded:
        assert thin.juris.input_basis == "profile_summary"
        assert any("short structured summary" in c for c in cards.outcome_card("k", thin, "accused_appeal", None, "rules").caveats)


def test_fixture_index_returns_a_real_cosine():
    """The legacy fixture vectors were unnormalised, so search reported cosines like -174; they must stay within [-1, 1]."""
    import numpy as np
    from services.embedder import embedder_service

    if embedder_service.index_source != "fixture" or embedder_service.is_empty:
        embedder_service.load_index()
    if embedder_service.index_source != "fixture":
        return  # a real artifact is configured in this environment; nothing to check
    rng = np.random.default_rng(0)
    for hit in embedder_service.search(rng.normal(size=384).tolist(), 3):
        assert -1.0 <= hit["cosine"] <= 1.0


# ---- one-liners -------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("What happened exactly? One liner please", True),
    ("give me a one-line summary", True), ("in one sentence, who won?", True), ("tl;dr", True), ("TLDR of the facts", True),
    ("briefly, what are the issues", True), ("short answer: was the FIR delayed?", True), ("keep it short", True),
    ("Who are the parties?", False), ("Summarise this matter and tell me what is at stake.", False),
    ("What does the appellant's brief argue about the FIR?", False), ("Is the line of cases consistent?", False),
])
def test_brevity_is_read_from_the_users_own_words(text, expected):
    from services.agent.routing import parse_brevity
    assert parse_brevity(text) is expected


@pytest.mark.parametrize("raw,expected", [
    ("The appellant is alleged to have killed the deceased with a kulhari. A key caveat is that the chain is contested.",
     "The appellant is alleged to have killed the deceased with a kulhari."),
    ("The weapon was recovered under Section 27 [S4]. Next, read the record.", "The weapon was recovered under Section 27 [S4]."),
    ("The weapon was recovered. [S4][S5] Next, read the record.", "The weapon was recovered [S4][S5]."),
    ("In State v. Rajasthan the court noted the delay. It then moved on.", "In State v. Rajasthan the court noted the delay."),
    ("Sec. 302 IPC is invoked against Dr. Sharma.", "Sec. 302 IPC is invoked against Dr. Sharma."),
    ("No terminal punctuation here", "No terminal punctuation here."),
    ("The FIR was lodged eleven hours after the occurrence[S2]", "The FIR was lodged eleven hours after the occurrence [S2]."),
    ("He was convicted [S1][S3] on that basis.", "He was convicted on that basis [S1][S3]."),
    ("- It was a hit and run.\n\nSecond sentence.", "It was a hit and run."),
])
def test_one_sentence_cuts_to_the_first_sentence_and_keeps_its_citations(raw, expected):
    from services.agent.sanitize import one_sentence
    assert one_sentence(raw) == expected


def test_one_sentence_caps_runaway_length():
    from services.agent.sanitize import one_sentence
    out = one_sentence(" ".join(["word"] * 120) + ".")
    assert len(out.split()) <= 40 and out.endswith("…")


def test_a_passage_that_starts_mid_sentence_is_not_quoted_as_a_fragment():
    from services.agent.narration import _from_first_full_sentence
    assert _from_first_full_sentence("after heavy rain. The learned trial court accepted this in part. The appellant contends") == "The learned trial court accepted this in part. The appellant contends"
    assert _from_first_full_sentence("The appellant was convicted. Later") == "The appellant was convicted. Later"
    assert _from_first_full_sentence("no boundary at all") == "no boundary at all"


@pytest.mark.parametrize("asked,searched", [
    ("What happened exactly? One liner please", "What happened?"),
    ("In one sentence, was there any delay in lodging the FIR?", "was there any delay in lodging the FIR?"),
    ("tl;dr of what the prosecution says happened", "of what the prosecution says happened"),
    ("Does the judgment say anything about recovery of the weapon?", "Does the judgment say anything about recovery of the weapon?"),
    ("one liner please", "one liner please"),     # nothing left once the filler is gone: keep what the user wrote
])
def test_request_style_filler_is_kept_out_of_the_document_search(asked, searched):
    from services.agent.routing import retrieval_query
    assert retrieval_query(asked) == searched


def test_every_passage_starts_at_the_start_of_a_sentence():
    """Passages cut mid-sentence lost their subject ("he was falsely implicated"), so the model could credit a claim to the wrong party."""
    from services.agent.doc_index import chunk_with_offsets
    text = open("tests/fixtures/demo_matter.txt", encoding="utf-8").read().strip()
    chunks = chunk_with_offsets(text)
    assert len(chunks) > 3
    for c in chunks:
        assert c.text == text[c.char_start:c.char_end]
        assert c.text[:1].isupper() or c.text[:1].isdigit(), f"passage {c.index} starts mid-sentence: {c.text[:50]!r}"
    # coverage: nothing is lost between passages
    assert chunks[0].char_start == 0 and chunks[-1].char_end == len(text)
    assert all(b.char_start < a.char_end for a, b in zip(chunks, chunks[1:]))   # they overlap rather than leave gaps
