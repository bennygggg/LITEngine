"""Juris training-pipeline units: title parsing, label mapping, leakage tiers, quality gates, splits and metrics."""

import numpy as np
import pytest

from scripts.juris.labels import map_disposal
from scripts.juris.metrics import bootstrap_ci, ece, mcnemar, metrics, paired_bootstrap
from scripts.juris.quality import interlocutory_tail, is_readable, procedural_tail
from scripts.juris.titles import appellant_side, is_criminal_appeal, normalise_type, parse_title
from services.juris_text import leak_hits, tier1, tier2


# --- which case types count as criminal appeals ---------------------------------------------------

@pytest.mark.parametrize("title", [
    "CRA/88/2015 of RAMESH Vs STATE OF M.P.", "CRL.A/300/2011 of MUKUNDAN Vs UNNIKRISHNAN", "CRA-S/12/2020 of A Vs STATE OF PUNJAB",
    "CR. APP (SJ)/272/2023 of LALLU Vs The State of Bihar", "Crl.A(J)/5/2023 of SUDESH Vs The State of Tripura",
    "JCRLA/31/2019 of NILA Vs STATE OF ODISHA", "APEAL/467/2016 of AVINASH Vs THE STATE OF MAHARASHTRA", "CRA(DB)/959/2019 of X Vs STATE",
])
def test_criminal_appeals_are_recognised(title):
    p = parse_title(title)
    assert is_criminal_appeal(p["ctype"], p["party1"], p["party2"]), title


@pytest.mark.parametrize("title", [
    "CRLAS/2711/2023 of DIWAKAR Vs STATE OF RAJASTHAN",          # suspension of sentence inside an appeal, not the appeal
    "CRLLA/267/2022 of DAMODAR Vs KAILASH",                       # leave to appeal
    "CR.RA/273/2020 of AVNI Vs STATE OF GUJARAT",                 # criminal revision
    "CRM(A)/5507/2023 of X Vs STATE", "CRMA/1609/2023 of X Vs Y",  # criminal miscellaneous applications (bail)
    "BAIL/28372/2022 of PRASHANT Vs STATE", "WP/1182/2021 of CHETAN Vs THE STATE", "APP/24/2024 of SUNDRIAMMAL Vs NEW KAMAL KUNJ SOCIETY",
])
def test_look_alikes_are_rejected(title):
    p = parse_title(title)
    assert not is_criminal_appeal(p["ctype"], p["party1"], p["party2"]), title


def test_title_parsing_handles_missing_parties_and_odd_types():
    assert parse_title(None)["ctype"] == ""
    p = parse_title("CRA/88/2015 of RAMESH")                 # no "Vs": party2 is None, never NaN
    assert p["party2"] is None and appellant_side(p["party1"], p["party2"]) == "unclear"
    assert normalise_type("Crl. A (J)") == "CRLA(J)"


def test_appellant_side_comes_from_party_order():
    assert appellant_side("STATE OF U.P.", "RAM SINGH") == "state_appeal"
    assert appellant_side("RAM SINGH", "STATE OF U.P. THROUGH SHO") == "accused_appeal"
    assert appellant_side("A", "B") == "unclear"
    assert appellant_side("STATE OF BIHAR", "STATE OF U.P.") == "unclear"


# --- labels ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("raw,label", [
    ("Allowed/Partly Allowed on merits", "succeeds"), ("ALLOWED", "succeeds"), ("PARTLY ALLOWED NO COSTS", "succeeds"), ("ALLOWED AND REMANDED", "succeeds"),
    ("Dismissed on merits", "dismissed"), ("DISMISSED", "dismissed"), ("Rejected", "dismissed"), ("Not Allowed", "dismissed"),
    ("Disposed off/Decided on merits", "neutral"), ("DISPOSED OF", "neutral"),
    ("Dismiss other than merit(DD/Non Prosec./Abated)", None), ("Withdrawn", None), ("DISMISSED AS WITHDRAWN", None), ("Abated", None),
    ("BAIL GRANTED", None), ("Dismissed for Non-Prosecution", None), ("", None), (None, None),
])
def test_disposal_mapping(raw, label):
    assert map_disposal(raw)[0] == label


# --- quality gates --------------------------------------------------------------------------------

def test_readability_gate_rejects_symbol_text():
    assert is_readable("The appellant was convicted by the trial court and the appeal is directed against that order of the court. " * 20)
    assert not is_readable("! 2  3  ( '  ,-  $  0,, . 10,00  0 0,00 9  !  !  \" ! # !  # & '  ! " * 30)


def test_procedural_and_interlocutory_endings_are_detected():
    assert procedural_tail("x " * 500 + "In view of the death of the sole respondent the appeal stands abated and is dismissed.")
    assert procedural_tail("x " * 500 + "The appeal is dismissed as not pressed.")
    assert not procedural_tail("x " * 500 + "We find no merit in the appeal and it is dismissed.")
    assert interlocutory_tail("x " * 500 + "The sentence is suspended during the pendency of the appeal and the appellant be released on bail.")
    assert not interlocutory_tail("x " * 500 + "The conviction is set aside and the appellant is acquitted. Bail bonds are discharged.")


# --- leakage tiers --------------------------------------------------------------------------------

def make_judgment() -> str:
    facts = "The prosecution case is that the deceased was attacked near the market. " * 40
    grounds = "Learned counsel for the appellant submitted that the witnesses are interested and the recovery is doubtful. " * 30
    reasoning = "ANALYSIS\nWe have carefully perused the record. In our view the testimony of PW-1 is reliable and consistent. " * 30
    order = "\nORDER\nThe appeal is dismissed. The conviction and sentence are upheld.\n"
    return facts + "\n\n" + grounds + "\n\n" + reasoning + order


def test_t2_cuts_before_the_reasoning_and_leaks_nothing():
    text = make_judgment()
    t2, meta = tier2(text)
    assert "ANALYSIS" not in t2 and "In our view" not in t2 and leak_hits(t2) == 0
    assert "prosecution case" in t2 and 0.1 < meta["t2_frac"] <= 0.6


def test_t1_strips_the_order_but_keeps_the_reasoning():
    text = make_judgment()
    t1, _ = tier1(text)
    assert leak_hits(text) > 0 and leak_hits(t1) == 0
    assert "In our view" in t1 and "The appeal is dismissed" not in t1


def test_verdict_lexicon_matches_real_operative_wording():
    for s in ["The criminal appeal is partly allowed to the extent indicated", "Accordingly the conviction is set aside",
              "the appellant is hereby acquitted", "this appeal fails and is dismissed", "The appeal stands allowed"]:
        assert leak_hits(s) > 0, s
    assert leak_hits("The learned Sessions Judge convicted the accused under Section 302.") == 0


# --- metrics --------------------------------------------------------------------------------------

def test_metrics_and_intervals_behave():
    rng = np.random.default_rng(0)
    y = rng.integers(0, 2, 2000)
    p = np.clip(y * 0.6 + rng.normal(0.2, 0.2, 2000), 0.01, 0.99)
    m = metrics(y, p)
    assert 0.5 < m["auc"] <= 1 and 0 <= m["ece"] <= 1 and m["n"] == 2000
    ci = bootstrap_ci(y, p, n=200)
    assert ci["acc"][0] <= m["acc"] <= ci["acc"][1]
    chance = metrics(y, rng.random(2000))
    assert abs(chance["auc"] - 0.5) < 0.05 and abs(chance["acc"] - 0.5) < 0.05
    d = paired_bootstrap(y, p, rng.random(2000), "auc", n=200)
    assert d["lo"] > 0                                          # a real signal beats noise
    assert mcnemar(y, p, p)["p_value"] == 1.0                   # identical predictors never differ
    assert ece(np.array([0, 1] * 50), np.full(100, 0.5)) == pytest.approx(0.0, abs=1e-9)


def test_temporal_split_keeps_test_years_out_of_training():
    pd = pytest.importorskip("pandas", reason="training-environment test")
    from scripts.juris.run_experiment import splits, TRAIN_MAX, VAL_YEAR, TEST_MIN
    D = pd.DataFrame({"decision_year": list(range(2008, 2027)) * 3})
    sp = splits(D)
    yr = D["decision_year"].values
    assert yr[sp["train"]].max() <= TRAIN_MAX and set(yr[sp["val"]]) == {VAL_YEAR} and yr[sp["test"]].min() >= TEST_MIN
    assert not (set(sp["train"]) & set(sp["test"])) and not (set(sp["val"]) & set(sp["test"]))
