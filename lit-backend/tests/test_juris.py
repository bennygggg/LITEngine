"""
Juris serving logic, tested on a small synthetic model so these tests do not depend on the shipped artifact
(tests/test_juris_packaging.py and the agent-flow tests exercise the real one).
"""

import math
import random

import numpy as np
import pytest

from scripts.juris.model_def import make_juris
from services import juris
from services.juris_features import CalibratedJuris, extract_sections
from services.scenario import add_section_to_text, remove_section_from_text

SUCCESS_WORDS = "contradictions delay unreliable witness benefit doubt".split()
DISMISS_WORDS = "recovered consistent reliable eyewitness corroborated motive".split()
FILLER = ("the appellant was tried by the learned sessions judge for offences under section 302 and section 34 of the indian penal code "
          "on the allegation that the incident occurred near the village and the prosecution examined several witnesses ").split()


def make_doc(rng: random.Random, succeeds: bool, n: int = 160, with_cue: bool = True) -> str:
    words = FILLER * 3
    bias = SUCCESS_WORDS if succeeds else DISMISS_WORDS
    body = [rng.choice(words + bias * 2) for _ in range(n)]
    cut = int(n * 0.45)
    reasoning = ["\n\nANALYSIS\n"] if with_cue else []
    return " ".join(body[:cut]) + "".join(reasoning) + " ".join(body[cut:]) + " "


@pytest.fixture(scope="module")
def synthetic():
    rng = random.Random(0)
    docs, sides, ys = [], [], []
    for i in range(400):
        s = i % 2 == 0
        docs.append(make_doc(rng, s))
        sides.append(rng.choice(["accused_appeal", "state_appeal", "unclear"]))
        ys.append(int(s))
    X = np.array([[d, sd, len(d.split())] for d, sd in zip(docs, sides)], dtype=object)
    y = np.array(ys)
    pipe = make_juris(C=2.0, min_df=2, max_features=2000).fit(X, y)
    cal = CalibratedJuris(pipe, a=1.0, b=0.0, meta={"schema": juris.ARTIFACT_SCHEMA, "version": "juris-test"})
    cal.finalize(X)
    return cal, X, y


@pytest.fixture()
def loaded(synthetic, monkeypatch):
    monkeypatch.setattr(juris, "_model", synthetic[0])
    return synthetic[0]


def test_validate_accepts_a_good_artifact_and_rejects_bad_ones(synthetic):
    cal = synthetic[0]
    juris._validate(cal)
    with pytest.raises(ValueError, match="not a CalibratedJuris"):
        juris._validate(cal.pipeline)
    bad = CalibratedJuris(cal.pipeline, meta={"schema": "something-else"})
    with pytest.raises(ValueError, match="schema"):
        juris._validate(bad)


def test_prediction_is_a_calibrated_distribution(loaded, synthetic):
    X = synthetic[1]
    r = juris.predict_juris(X[0, 0], "accused_appeal")
    assert r.model_loaded and r.model_version == "juris-test" and r.input_basis == "case_text"
    assert r.probabilities["dismissed"] + r.probabilities["succeeds"] == pytest.approx(1.0)
    assert r.predicted_class in ("succeeds", "dismissed") and r.words_read and r.words_read >= juris.MIN_WORDS


@pytest.mark.parametrize("appellant", ["accused_appeal", "state_appeal", "unclear"])
def test_contributions_add_up_to_the_logit(loaded, synthetic, appellant):
    """The bars are only honest if they add up: baseline logit + sum(contributions) == the model's logit."""
    X = synthetic[1]
    for i in (0, 1, 7):
        r = juris.predict_juris(X[i, 0], appellant)
        total = sum(c.contribution for c in r.feature_contributions)
        p = r.probabilities["succeeds"]
        assert loaded.baseline_logit + total == pytest.approx(math.log(p / (1 - p)), abs=1e-6)


def test_appellant_type_is_an_input_not_an_inference(loaded):
    """A text that says 'State of X versus Y' must not change the appeal type the user gave."""
    text = "State of Rajasthan versus Mohan Lal. " + make_doc(random.Random(3), True)
    r = juris.predict_juris(text, "unclear")
    side = {c.feature: c.value for c in r.feature_contributions if c.feature.startswith("appellant_type=")}
    assert side["appellant_type=unclear"] == 1.0 and side["appellant_type=state_appeal"] == 0.0
    assert juris.predict_juris(text, "not-a-type").feature_contributions  # unknown values degrade to "unclear", they never raise


def test_serving_ignores_a_verdict_appended_to_the_document(loaded):
    """The same pre-reasoning cut as in training: a document that ends with the court's order must read the same as without it."""
    base = make_doc(random.Random(5), True, n=700)
    with_order = base + "\nThe appeal is allowed. The conviction is set aside and the appellant is acquitted of all charges."
    a, b = juris.predict_juris(base, "accused_appeal"), juris.predict_juris(with_order, "accused_appeal")
    assert a.probabilities["succeeds"] == pytest.approx(b.probabilities["succeeds"], abs=1e-12)
    assert a.words_read == b.words_read


def test_pre_cut_text_is_read_whole(loaded):
    text = make_doc(random.Random(6), True, n=600)
    assert juris.predict_juris(text, "unclear", pre_cut=True).words_read == len(text.split())
    assert juris.predict_juris(text, "unclear").words_read < len(text.split())


def test_too_little_text_returns_a_marked_stub_not_a_guess(loaded):
    r = juris.predict_juris("The appellant was convicted.", "accused_appeal")
    assert not r.model_loaded and "too little text" in r.explanation_sentences[0].lower()


def test_not_loaded_falls_back_cleanly(monkeypatch):
    monkeypatch.setattr(juris, "_model", None)
    r = juris.predict_juris("anything " * 100, "accused_appeal")
    assert not r.model_loaded and r.predicted_class == "unknown" and not juris.is_juris_loaded()


def test_reshape_into_the_legacy_result_is_bounded(loaded, synthetic):
    r = juris.predict_juris(synthetic[1][0, 0], "accused_appeal")
    sim = juris.juris_to_simulation_result(r)
    assert juris.PROB_MIN <= sim.win_probability <= juris.PROB_MAX
    assert all(0 <= s.weight <= 1 and 0 <= s.raw_score <= 1 for s in sim.score_breakdown)
    assert sum(s.weight for s in sim.score_breakdown) == pytest.approx(1.0, abs=0.02)


# --- scenario text edits ---------------------------------------------------------------

def test_extract_sections_reads_lists_and_subsections():
    assert extract_sections("convicted under Sections 302/34 IPC and u/s 498A, also section 304B(1)") == ["302", "304B", "34", "498A"]
    assert extract_sections("no statute is cited here") == []


def test_add_and_remove_a_section_edit_the_text_juris_reads():
    text = "He was charged under Sections 302, 34 and 201 of the IPC."
    assert "201" not in extract_sections(remove_section_from_text(text, "201"))
    assert extract_sections(remove_section_from_text(text, "201")) == ["302", "34"]
    assert extract_sections(remove_section_from_text("under Section 302 only", "302")) == []
    assert "120B" in extract_sections(add_section_to_text(text, "120B"))


def test_a_short_filing_is_only_cut_at_a_verdict_or_cue(loaded):
    short = make_doc(random.Random(8), True, n=150, with_cue=False)
    assert juris.prepare_text(short)[1] == len(short.split())
    leaky = short + " The appeal is allowed and the conviction is set aside."
    assert juris.prepare_text(leaky)[1] <= len(short.split()) + 1
