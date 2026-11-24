"""
Robustness and sensitivity analyses for Juris. Everything here uses the development years (<= 2022) except `testpreds`, which re-fits the
FROZEN shipped configuration and writes its per-case test predictions for descriptive analyses (a disclosed second use of the test split by
an unchanged model; no choice depends on it).

    .venv-juris/bin/python -m scripts.juris.robustness cut|rolling|lobo|ablate|side|testpreds
Results are merged into data/juris/reports/robustness.json.
"""

import json
import re
import sys
import time
from typing import Any, Dict

import numpy as np
import pandas as pd

from scripts.juris import paths
from scripts.juris.metrics import metrics
from scripts.juris.model_def import make_juris
from scripts.juris.names import load_names
from scripts.juris.run_experiment import (X_of, fit_calibrated, load_tier, prob, splits, side_X, TRAIN_MAX)
from services import juris_text as jt
from services.juris_text import leak_hits

OUT = paths.REPORT_DIR / "robustness.json"
CAP = 20_000
NAMES = load_names() or None


def save(key: str, value: Any) -> None:
    cur = json.loads(OUT.read_text()) if OUT.exists() else {}
    cur[key] = value
    OUT.write_text(json.dumps(cur, indent=2, default=float))


def fit_eval(Xtr, ytr, Xva, yva, **kw) -> Dict[str, float]:
    m = fit_calibrated(lambda: make_juris(C=1.0, stop_words=NAMES, **kw), Xtr, ytr, Xva, yva)
    r = metrics(yva, prob(m, Xva))
    return {k: round(float(r[k]), 4) for k in ("acc", "bal_acc", "macro_f1", "auc", "brier", "ece")} | {"n_train": int(len(ytr)), "n_eval": int(len(yva))}


def cut_variant(text: str, cap: float, cues: bool) -> str:
    saved = (jt.T2_CAP, jt.CUE_RE)
    jt.T2_CAP = cap
    if not cues:
        jt.CUE_RE = re.compile(r"(?!x)x")
    try:
        return jt.tier2(text)[0]
    finally:
        jt.T2_CAP, jt.CUE_RE = saved


def frame(texts, side) -> pd.DataFrame:
    return pd.DataFrame({"text": list(texts), "side": list(side), "n_words": [len(t.split()) for t in texts]})


def cmd_cut() -> None:
    D = load_tier("t0", 100)
    sp = splits(D)
    rng = np.random.default_rng(21)
    tr = rng.choice(sp["train"], min(CAP, len(sp["train"])), replace=False)
    va = sp["val"]
    y = (D["label"] == "succeeds").astype(int).values
    rows = []
    for cap, cues in [(0.30, True), (0.45, True), (0.60, True), (0.75, True), (0.90, True), (0.60, False), (1.0, False)]:
        t0 = time.time()
        Ttr = [cut_variant(t, cap, cues) for t in D["t0"].values[tr]]
        Tva = [cut_variant(t, cap, cues) for t in D["t0"].values[va]]
        r = fit_eval(frame(Ttr, D["side"].values[tr]), y[tr], frame(Tva, D["side"].values[va]), y[va])
        r |= {"cap": cap, "reasoning_cues": cues, "mean_words_kept": round(float(np.mean([len(t.split()) for t in Tva])), 1),
              "docs_with_verdict_phrase_pct": round(100 * float(np.mean([leak_hits(t) > 0 for t in Tva])), 2)}
        rows.append(r)
        print(f"  cap={cap} cues={cues}: acc={r['acc']:.3f} auc={r['auc']:.3f} words={r['mean_words_kept']} leak%={r['docs_with_verdict_phrase_pct']} ({time.time() - t0:.0f}s)", flush=True)
    save("cut_sensitivity_val2022", rows)


def cmd_rolling() -> None:
    D = load_tier("t2", 100)
    y = (D["label"] == "succeeds").astype(int).values
    X = X_of(D, "t2")
    yr = D["decision_year"].values
    rng = np.random.default_rng(5)
    rows = []
    for origin in (2017, 2018, 2019, 2020, 2021):
        tr = np.where(yr <= origin)[0]
        tr = rng.choice(tr, min(30_000, len(tr)), replace=False)
        te = np.where(yr == origin + 1)[0]
        r = fit_eval(X.iloc[tr], y[tr], X.iloc[te], y[te])
        side = fit_calibrated(lambda: make_juris(use_text=False, use_sections=False), side_X(D.iloc[tr]), y[tr], side_X(D.iloc[te]), y[te])
        rs = metrics(y[te], prob(side, side_X(D.iloc[te])))
        r |= {"train_years": f"<= {origin}", "test_year": origin + 1, "majority_acc": round(float(max(y[te].mean(), 1 - y[te].mean())), 4),
              "side_only_acc": round(float(rs["acc"]), 4), "side_only_auc": round(float(rs["auc"]), 4)}
        rows.append(r)
        print(f"  train<={origin} -> {origin + 1}: acc={r['acc']:.3f} auc={r['auc']:.3f} | majority={r['majority_acc']:.3f} side-only auc={r['side_only_auc']:.3f}", flush=True)
    save("rolling_origin", rows)


def cmd_lobo() -> None:
    D = load_tier("t2", 100)
    D = D[D["decision_year"] <= 2022].reset_index(drop=True)
    y = (D["label"] == "succeeds").astype(int).values
    X = X_of(D, "t2")
    rng = np.random.default_rng(9)
    rows = []
    for bench in D["bench"].value_counts().head(8).index:
        te = np.where(D["bench"].values == bench)[0]
        tr = np.where(D["bench"].values != bench)[0]
        tr = rng.choice(tr, min(30_000, len(tr)), replace=False)
        if len(np.unique(y[te])) < 2:
            continue
        r = fit_eval(X.iloc[tr], y[tr], X.iloc[te], y[te])
        r |= {"held_out_bench": bench, "majority_acc": round(float(max(y[te].mean(), 1 - y[te].mean())), 4), "succeeds_share": round(float(y[te].mean()), 3)}
        rows.append(r)
        print(f"  held out {bench} (n={len(te)}): acc={r['acc']:.3f} auc={r['auc']:.3f} majority={r['majority_acc']:.3f}", flush=True)
    save("leave_one_bench_out_to2022", rows)


def cmd_ablate() -> None:
    D = load_tier("t2", 100)
    sp = splits(D)
    y = (D["label"] == "succeeds").astype(int).values
    X = X_of(D, "t2")
    rng = np.random.default_rng(31)
    tr = rng.choice(sp["train"], min(CAP, len(sp["train"])), replace=False)
    va = sp["val"]
    rows = {}
    rows["full model"] = fit_eval(X.iloc[tr], y[tr], X.iloc[va], y[va])
    rows["no cited-section indicators"] = fit_eval(X.iloc[tr], y[tr], X.iloc[va], y[va], use_sections=False)
    rows["no appeal type (text only)"] = fit_eval(X.iloc[tr], y[tr], X.iloc[va], y[va], use_side=False, use_sections=False)
    rows["unigrams only"] = fit_eval(X.iloc[tr], y[tr], X.iloc[va], y[va], ngram_range=(1, 1))
    head = lambda d: frame([" ".join(t.split()[: max(40, int(0.15 * len(t.split())))]) for t in d["t2"]], d["side"])
    rows["first 15% of the pre-reasoning text only"] = fit_eval(head(D.iloc[tr]), y[tr], head(D.iloc[va]), y[va])
    tail = lambda d: frame([" ".join(t.split()[int(0.5 * len(t.split())):]) for t in d["t2"]], d["side"])
    rows["last half of the pre-reasoning text only"] = fit_eval(tail(D.iloc[tr]), y[tr], tail(D.iloc[va]), y[va])
    for k, r in rows.items():
        print(f"  {k:46s} acc={r['acc']:.3f} auc={r['auc']:.3f} bal={r['bal_acc']:.3f}", flush=True)
    save("ablations_val2022_trained_on_20k", rows)


def cmd_side() -> None:
    D = load_tier("t2", 100)
    sp = splits(D)
    y = (D["label"] == "succeeds").astype(int).values
    X = X_of(D, "t2")
    tr, va = sp["train"], sp["val"]
    joint = fit_calibrated(lambda: make_juris(C=1.0, stop_words=NAMES), X.iloc[tr], y[tr], X.iloc[va], y[va])
    pj = prob(joint, X.iloc[va])
    side = D["side"].values
    out = {}
    for s in ("accused_appeal", "state_appeal", "unclear"):
        trs, vas = tr[side[tr] == s], va[side[va] == s]
        if len(vas) < 100 or len(np.unique(y[vas])) < 2:
            continue
        m = fit_calibrated(lambda: make_juris(C=1.0, stop_words=NAMES), X.iloc[trs], y[trs], X.iloc[vas], y[vas])
        out[s] = {"n_val": int(len(vas)), "succeeds_share": round(float(y[vas].mean()), 3),
                  "joint_model_auc_within_side": round(float(metrics(y[vas], pj[np.isin(va, vas)])["auc"]), 4),
                  "side_specific_model_auc": round(float(metrics(y[vas], prob(m, X.iloc[vas]))["auc"]), 4)}
        print(f"  {s}: joint AUC {out[s]['joint_model_auc_within_side']:.3f} vs side-specific {out[s]['side_specific_model_auc']:.3f} (n={len(vas)})", flush=True)
    save("side_specific_models_val2022", out)


def cmd_testpreds() -> None:
    """Re-fit the FROZEN shipped configuration (C=1, no recency, names removed) and store per-case test predictions (no text)."""
    D = load_tier("t2", 100)
    sp = splits(D)
    y = (D["label"] == "succeeds").astype(int).values
    X = X_of(D, "t2")
    tr, va, te = sp["train"], sp["val"], sp["test"]
    m = fit_calibrated(lambda: make_juris(C=1.0, stop_words=NAMES), X.iloc[tr], y[tr], X.iloc[va], y[va])
    p = prob(m, X.iloc[te])
    r = metrics(y[te], p)
    ref = json.loads((paths.REPORT_DIR / "final.json").read_text())["tiers"]["T2 pre-reasoning (ships)"]
    head = D["t2"].str.slice(0, 2500).str.lower()
    pred = pd.DataFrame({"cnr": D["cnr"].values[te], "y": y[te], "p": p, "bench": D["bench"].values[te], "year": D["decision_year"].values[te],
                         "side": D["side"].values[te], "bailish": head.values[te].astype(str)})
    pred["bailish"] = pred["bailish"].str.contains(r"\bbail\b|14[- ]?a\b|section\s*14\s*\(?a")
    pred.to_parquet(paths.REPORT_DIR / "test_predictions.parquet")
    out: Dict[str, Any] = {"reproduces_final_report": bool(abs(r["acc"] - ref["acc"]) < 1e-9 and abs(r["auc"] - ref["auc"]) < 1e-9),
                           "acc": round(float(r["acc"]), 4), "auc": round(float(r["auc"]), 4)}
    conf = np.abs(p - 0.5)
    order = np.argsort(-conf)
    curve = []
    for cov in (1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3):
        k = int(len(p) * cov)
        idx = order[:k]
        curve.append({"coverage": cov, "accuracy": round(float(((p[idx] >= 0.5) == y[te][idx]).mean()), 4), "n": int(k)})
    out["selective_prediction"] = curve
    out["majority_acc_all"] = round(float(max(y[te].mean(), 1 - y[te].mean())), 4)
    sub = {}
    for name, mask in (("bail-type appeals", pred["bailish"].values), ("other appeals", ~pred["bailish"].values)):
        mm = metrics(y[te][mask], p[mask])
        sub[name] = {"n": int(mask.sum()), "succeeds_share": round(float(y[te][mask].mean()), 3), "acc": round(float(mm["acc"]), 4), "auc": round(float(mm["auc"]), 4),
                     "bal_acc": round(float(mm["bal_acc"]), 4)}
    out["subgroups_test"] = sub
    for k in ("selective_prediction", "subgroups_test"):
        print(k, json.dumps(out[k]), flush=True)
    print("reproduces the reported test result:", out["reproduces_final_report"], out["acc"], out["auc"], flush=True)
    save("frozen_model_test_analysis", out)


def cmd_sidetest() -> None:
    """DISCLOSED SECOND USE of the test split. A State-appeal-specific model was chosen on VALIDATION data (it beat the joint model within State
    appeals: AUC 0.74 vs 0.61). Here it is evaluated once on the test period, replacing the joint model's predictions for State appeals only."""
    D = load_tier("t2", 100)
    sp = splits(D)
    y = (D["label"] == "succeeds").astype(int).values
    X = X_of(D, "t2")
    side = D["side"].values
    tr, va, te = sp["train"], sp["val"], sp["test"]
    trs, vas, tes = tr[side[tr] == "state_appeal"], va[side[va] == "state_appeal"], te[side[te] == "state_appeal"]
    m = fit_calibrated(lambda: make_juris(C=1.0, stop_words=NAMES), X.iloc[trs], y[trs], X.iloc[vas], y[vas])
    p_state = prob(m, X.iloc[tes])
    pred = pd.read_parquet(paths.REPORT_DIR / "test_predictions.parquet").set_index("cnr")
    cn = D["cnr"].values
    joint = pred.loc[cn[te], "p"].values.copy()
    comb = joint.copy()
    is_state = side[te] == "state_appeal"
    comb[is_state] = p_state                       # same order: te is ascending and tes = te[is_state]
    yt = y[te]
    out: Dict[str, Any] = {"n_state_train": int(len(trs)), "n_state_val": int(len(vas)), "n_state_test": int(len(tes)), "state_test_succeeds_share": round(float(y[tes].mean()), 4)}
    for name, pp, mask in (("joint model, State appeals", joint, is_state), ("State-specific model, State appeals", comb, is_state),
                           ("joint model, all test cases", joint, np.ones(len(te), bool)), ("combined (State-specific for State appeals), all test cases", comb, np.ones(len(te), bool))):
        r = metrics(yt[mask], pp[mask])
        out[name] = {k: round(float(r[k]), 4) for k in ("acc", "bal_acc", "macro_f1", "auc", "brier", "ece")}
        print(f"  {name:62s} acc={r['acc']:.3f} bal={r['bal_acc']:.3f} auc={r['auc']:.3f} brier={r['brier']:.3f}", flush=True)
    save("state_specific_model_test_second_look", out)


if __name__ == "__main__":
    {"sidetest": cmd_sidetest, "cut": cmd_cut, "rolling": cmd_rolling, "lobo": cmd_lobo, "ablate": cmd_ablate, "side": cmd_side, "testpreds": cmd_testpreds}[sys.argv[1]]()
