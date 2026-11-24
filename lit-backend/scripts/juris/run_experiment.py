"""
Juris experiments: temporal split, model selection on the validation year, ONE look at the test split.

    .venv-juris/bin/python -m scripts.juris.run_experiment dev     # train <= 2021, tune on 2022; never reads the test split
    .venv-juris/bin/python -m scripts.juris.run_experiment final   # applies the dev choice to 2023+ exactly once (guarded)

Reports land in data/juris/reports/ (dev.json, final.json, paper/*.csv|tex).
"""

import argparse
import json
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from scripts.juris import paths
from scripts.juris.corpus import KEEP, load_corpus
from scripts.juris.metrics import bootstrap_ci, mcnemar, metrics, paired_bootstrap, reliability
from scripts.juris.model_def import make_juris, make_lgbm
from scripts.juris.names import load_names
from services.juris_features import CalibratedJuris

TRAIN_MAX, VAL_YEAR, TEST_MIN = 2021, 2022, 2023
C_GRID = [1, 2, 4, 8]
TOUCHED = paths.REPORT_DIR / "test_touched.json"


MIN_DOC_WORDS = 800   # merits judgments: shorter documents are mostly orders on bail / suspension of sentence inside a pending appeal


def load_tier(tier: str, min_t2_words: int, min_doc_words: int = MIN_DOC_WORDS, keep_interlocutory: bool = False) -> pd.DataFrame:
    cols = ["cnr", "bench", "decision_year", "side", "ctype", "label", "n0", "n1", "n2", "t2_reason", "interlocutory", tier]
    D = load_corpus(columns=sorted(set(cols)))
    D = D[(D["n2"] >= min_t2_words) & (D["n0"] >= min_doc_words)]
    if not keep_interlocutory:
        D = D[~D["interlocutory"].astype(bool)]
    return D.reset_index(drop=True)


def X_of(D: pd.DataFrame, tier: str) -> pd.DataFrame:
    return pd.DataFrame({"text": D[tier].values, "side": D["side"].values, "n_words": D["n" + tier[1]].values})


def meta_X(D: pd.DataFrame) -> pd.DataFrame:
    text = (D["bench"].astype(str) + " yr" + D["decision_year"].astype(str) + " " + D["ctype"].fillna("").astype(str)).values
    return pd.DataFrame({"text": text, "side": D["side"].values, "n_words": 0})


def side_X(D: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({"text": [""] * len(D), "side": D["side"].values, "n_words": 0})


def platt(z: np.ndarray, y: np.ndarray) -> Tuple[float, float]:
    lr = LogisticRegression(C=1e6, solver="lbfgs").fit(z.reshape(-1, 1), y)
    return float(lr.coef_[0][0]), float(lr.intercept_[0])


def recency_weights(years: np.ndarray, half_scale: Optional[float], ref_year: int) -> Optional[np.ndarray]:
    """w = exp((year - ref_year) / H): recent decisions count more (the outcome mix drifts over the years). None = unweighted."""
    return None if not half_scale else np.exp((np.asarray(years, dtype=float) - ref_year) / half_scale)


def fit_calibrated(make: Callable, Xtr, ytr, Xval, yval, w: Optional[np.ndarray] = None) -> CalibratedJuris:
    pipe = make()
    if w is None:
        pipe.fit(Xtr, ytr)
    else:
        pipe.fit(Xtr, ytr, clf__sample_weight=w)
    cal = CalibratedJuris(pipe)
    a, b = platt(cal.decision_function(Xval), yval)
    cal.a, cal.b = a, b
    return cal


def prob(model: CalibratedJuris, X) -> np.ndarray:
    return model.predict_proba(X)[:, 1]


def splits(D: pd.DataFrame) -> Dict[str, np.ndarray]:
    yr = D["decision_year"].values
    return {"train": np.where(yr <= TRAIN_MAX)[0], "val": np.where(yr == VAL_YEAR)[0], "test": np.where(yr >= TEST_MIN)[0]}


def majority_probs(ytr: np.ndarray, n: int) -> np.ndarray:
    return np.full(n, ytr.mean())


# ---------------------------------------------------------------------------------------------- dev

def dev(args: argparse.Namespace) -> None:
    t0 = time.time()
    names = load_names() or None
    D = load_tier("t2", args.min_t2_words)
    sp = splits(D)
    y = (D["label"] == "succeeds").astype(int).values
    tr, va = sp["train"], sp["val"]
    print(f"dev: {len(D)} cases | train {len(tr)} (<= {TRAIN_MAX}) | val {len(va)} ({VAL_YEAR}) | test {len(sp['test'])} (not read)", flush=True)
    X = X_of(D, "t2")
    out: Dict[str, Any] = {"n_total": len(D), "n_train": len(tr), "n_val": len(va), "n_test_reserved": len(sp["test"]),
                           "val_succeeds_share": float(y[va].mean()), "train_succeeds_share": float(y[tr].mean())}
    res: Dict[str, Dict[str, float]] = {}
    res["majority"] = metrics(y[va], majority_probs(y[tr], len(va)))
    for name, mk, fx in (("side_only", lambda: make_juris(use_text=False, use_sections=False), side_X),
                         ("meta_only(bench,year,ctype,side)", lambda: make_juris(min_df=3, use_sections=False), meta_X)):
        m = fit_calibrated(mk, fx(D.iloc[tr]), y[tr], fx(D.iloc[va]), y[va])
        res[name] = metrics(y[va], prob(m, fx(D.iloc[va])))
        print(f"  {name:36s} " + "  ".join(f"{k}={v:.3f}" for k, v in res[name].items() if k in ("acc", "bal_acc", "auc")), flush=True)
    # C grid for the shipped linear model (calibration uses the same val year: fine for SELECTION; the test is untouched)
    best_c, best_ll, lr_models = None, 9e9, {}
    for C in (args.c_grid or C_GRID):
        m = fit_calibrated(lambda C=C: make_juris(C=C, stop_words=names), X.iloc[tr], y[tr], X.iloc[va], y[va])
        r = metrics(y[va], prob(m, X.iloc[va]))
        res[f"juris_lr C={C}"] = r
        print(f"  juris_lr C={C:<5} " + "  ".join(f"{k}={v:.3f}" for k, v in r.items() if k in ("acc", "bal_acc", "auc", "logloss", "ece")), flush=True)
        if r["logloss"] < best_ll:
            best_c, best_ll = C, r["logloss"]
        lr_models[C] = m
    out["best_C"] = best_c
    lr_best = lr_models[best_c]
    # recency weighting: adopted only if it improves validation log-loss by a clear margin
    out["recency_H"] = None
    yrs = D["decision_year"].values
    for H in (() if args.skip_recency else (4.0, 8.0)):
        m = fit_calibrated(lambda: make_juris(C=best_c, stop_words=names), X.iloc[tr], y[tr], X.iloc[va], y[va], recency_weights(yrs[tr], H, TRAIN_MAX))
        r = metrics(y[va], prob(m, X.iloc[va]))
        res[f"juris_lr C={best_c} recency H={H:g}"] = r
        print(f"  juris_lr C={best_c} recency H={H:<4g} " + "  ".join(f"{k}={v:.3f}" for k, v in r.items() if k in ("acc", "bal_acc", "auc", "logloss", "ece")), flush=True)
        if r["logloss"] < best_ll - 0.004:
            best_ll, out["recency_H"], lr_best = r["logloss"], H, m
    p_lr = prob(lr_best, X.iloc[va])
    # non-linear challenger and the promotion rule
    if not args.skip_lgbm:
        lg = fit_calibrated(lambda: make_lgbm(stop_words=names), X.iloc[tr], y[tr], X.iloc[va], y[va], recency_weights(yrs[tr], out["recency_H"], TRAIN_MAX))
        p_lg = prob(lg, X.iloc[va])
        res["lightgbm"] = metrics(y[va], p_lg)
        diff = paired_bootstrap(y[va], p_lg, p_lr, "acc")
        out["promotion_lgbm_vs_lr_val_acc"] = diff
        promote = diff["diff"] >= 0.03 and diff["lo"] > 0
        out["selected_model"] = "lightgbm" if promote else "juris_lr"
        print(f"  lightgbm  acc={res['lightgbm']['acc']:.3f} auc={res['lightgbm']['auc']:.3f} | vs LR paired dAcc={diff['diff']:+.3f} [{diff['lo']:+.3f},{diff['hi']:+.3f}] -> {out['selected_model']}", flush=True)
    else:
        out["selected_model"] = "juris_lr"
    # learning curve on the validation year
    curve = []
    rng = np.random.default_rng(5)
    for n in [2500, 10000, 25000, 50000, 75000]:
        if n > len(tr):
            break
        idx = rng.choice(tr, n, replace=False)
        m = fit_calibrated(lambda: make_juris(C=best_c, stop_words=names), X.iloc[idx], y[idx], X.iloc[va], y[va], recency_weights(yrs[idx], out["recency_H"], TRAIN_MAX))
        r = metrics(y[va], prob(m, X.iloc[va]))
        curve.append({"n_train": n, "acc": r["acc"], "auc": r["auc"], "macro_f1": r["macro_f1"]})
        print(f"  learning curve n={n:<7} acc={r['acc']:.3f} auc={r['auc']:.3f}", flush=True)
    curve.append({"n_train": len(tr), "acc": res[f"juris_lr C={best_c}"]["acc"], "auc": res[f"juris_lr C={best_c}"]["auc"], "macro_f1": res[f"juris_lr C={best_c}"]["macro_f1"]})
    out["val_results"], out["learning_curve"], out["secs"] = res, curve, round(time.time() - t0)
    (paths.REPORT_DIR / "dev.json").write_text(json.dumps(out, indent=2))
    print("wrote reports/dev.json", flush=True)


# ---------------------------------------------------------------------------------------------- final

def final(args: argparse.Namespace) -> None:
    if TOUCHED.exists() and not args.allow_retest:
        sys.exit(f"The test split was already evaluated ({TOUCHED}). Refusing to look again without --allow-retest.")
    cfg = json.loads((paths.REPORT_DIR / "dev.json").read_text())
    C, selected, H = cfg["best_C"], cfg["selected_model"], cfg.get("recency_H")
    names = load_names() or None
    TOUCHED.write_text(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "C": C, "selected": selected}))
    t0 = time.time()
    out: Dict[str, Any] = {"config": {"C": C, "selected_model": selected, "recency_H": H, "min_t2_words": args.min_t2_words, "train_max": TRAIN_MAX,
                                      "val_year": VAL_YEAR, "test_min": TEST_MIN}}
    tiers: Dict[str, Dict[str, Any]] = {}
    preds: Dict[str, np.ndarray] = {}
    TIER_CAP = 20_000        # T0/T1 vocabularies of full judgments do not fit an 8 GB machine at 100k documents; the comparison uses one cap for all tiers
    for tier, label in (("t2", "T2 pre-reasoning (ships)"), ("t1", "T1 order-stripped (ILDC-style)"), ("t0", "T0 full text (upper bound)")):
        D = load_tier(tier, args.min_t2_words)
        sp = splits(D)
        y = (D["label"] == "succeeds").astype(int).values
        tr, va, te = sp["train"], sp["val"], sp["test"]
        X = X_of(D, tier)
        yrs_all = D["decision_year"].values
        sub = tr if len(tr) <= TIER_CAP else np.random.default_rng(11).choice(tr, TIER_CAP, replace=False)
        if tier == "t2":                                   # the shipped configuration: full training set
            m = fit_calibrated(lambda: make_juris(C=C, stop_words=names), X.iloc[tr], y[tr], X.iloc[va], y[va], recency_weights(yrs_all[tr], H, TRAIN_MAX))
            p = prob(m, X.iloc[te])
            tiers[label] = {**metrics(y[te], p), "ci": bootstrap_ci(y[te], p)}
            print(f"  {label:44s} " + "  ".join(f"{k}={v:.3f}" for k, v in tiers[label].items() if k in ("acc", "bal_acc", "macro_f1", "auc", "brier", "ece")), flush=True)
            D2, sp2, y2, X2, p_t2, model_t2 = D, sp, y, X, p, m
            preds["juris"] = p
            out["n"] = {"total": len(D), "train": len(tr), "val": len(va), "test": len(te),
                        "test_succeeds_share": float(y[te].mean()), "train_succeeds_share": float(y[tr].mean()), "tier_comparison_train_cap": TIER_CAP}
        # like-for-like tier comparison: identical capped training subsample for every tier
        label_c = label.split(" (")[0] + " (same capped training set)"
        mc = fit_calibrated(lambda: make_juris(C=C, stop_words=names), X.iloc[sub], y[sub], X.iloc[va], y[va], recency_weights(yrs_all[sub], H, TRAIN_MAX))
        pc = prob(mc, X.iloc[te])
        tiers[label_c] = {**metrics(y[te], pc), "ci": bootstrap_ci(y[te], pc)}
        print(f"  {label_c:44s} " + "  ".join(f"{k}={v:.3f}" for k, v in tiers[label_c].items() if k in ("acc", "bal_acc", "macro_f1", "auc")), flush=True)
        if tier != "t2":
            del D, X
    out["tiers"] = tiers
    te, tr, va = sp2["test"], sp2["train"], sp2["val"]
    yte = y2[te]
    # baselines and ablations, all on the same test cases
    base: Dict[str, Dict[str, Any]] = {}
    pm = majority_probs(y2[tr], len(te)); base["majority"] = {**metrics(yte, pm)}
    for name, mk, fx in (("side_only", lambda: make_juris(use_text=False, use_sections=False), side_X),
                         ("meta_only(bench,year,ctype,side)", lambda: make_juris(min_df=3, use_sections=False), meta_X)):
        mm = fit_calibrated(mk, fx(D2.iloc[tr]), y2[tr], fx(D2.iloc[va]), y2[va]); pp = prob(mm, fx(D2.iloc[te]))
        preds[name] = pp; base[name] = {**metrics(yte, pp), "ci": bootstrap_ci(yte, pp)}
    mk = fit_calibrated(lambda: make_juris(C=C), X2.iloc[tr], y2[tr], X2.iloc[va], y2[va])
    pp = prob(mk, X2.iloc[te]); preds["T2 + proper nouns kept"] = pp; base["T2 + proper nouns kept (ablation)"] = {**metrics(yte, pp), "ci": bootstrap_ci(yte, pp)}
    rng = np.random.default_rng(3)
    ys = rng.permutation(y2[tr])
    msh = fit_calibrated(lambda: make_juris(C=C, stop_words=names), X2.iloc[tr], ys, X2.iloc[va], y2[va])
    base["shuffled-label sanity (should be ~chance)"] = {**metrics(yte, prob(msh, X2.iloc[te]))}
    if selected == "lightgbm" or args.with_lgbm:
        lg = fit_calibrated(lambda: make_lgbm(stop_words=names), X2.iloc[tr], y2[tr], X2.iloc[va], y2[va]); pl = prob(lg, X2.iloc[te])
        preds["lightgbm"] = pl; base["lightgbm (challenger)"] = {**metrics(yte, pl), "ci": bootstrap_ci(yte, pl)}
    out["baselines"] = base
    out["paired_tests_vs_juris"] = {
        k: {"mcnemar": mcnemar(yte, preds["juris"], v), "delta_acc": paired_bootstrap(yte, preds["juris"], v, "acc"),
            "delta_auc": paired_bootstrap(yte, preds["juris"], v, "auc")}
        for k, v in preds.items() if k != "juris"}
    # breakdowns
    pj = preds["juris"]
    Dte = D2.iloc[te].assign(y=yte, p=pj)
    def grp(col: str, top: Optional[int] = None) -> List[Dict[str, Any]]:
        rows = []
        for key, g in Dte.groupby(col):
            if len(g) >= 100 and g["y"].nunique() > 1:
                m_ = metrics(g["y"].values, g["p"].values)
                rows.append({col: str(key), "n": len(g), "succeeds_share": float(g["y"].mean()), "acc": m_["acc"], "auc": m_["auc"], "bal_acc": m_["bal_acc"]})
        rows.sort(key=lambda r: -r["n"])
        return rows[:top] if top else rows
    out["by_bench"], out["by_year"], out["by_side"] = grp("bench", 25), grp("decision_year"), grp("side")
    out["reliability"] = reliability(yte, pj)
    out["t2_cut_reason_share"] = D2["t2_reason"].value_counts(normalize=True).round(4).to_dict()
    out["secs"] = round(time.time() - t0)
    (paths.REPORT_DIR / "final.json").write_text(json.dumps(out, indent=2, default=str))
    print("wrote reports/final.json (test split now marked as touched)", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["dev", "final"])
    ap.add_argument("--min-t2-words", type=int, default=100)
    ap.add_argument("--skip-lgbm", action="store_true")
    ap.add_argument("--skip-recency", action="store_true")
    ap.add_argument("--c-grid", type=float, nargs="*", default=None)
    ap.add_argument("--with-lgbm", action="store_true")
    ap.add_argument("--allow-retest", action="store_true")
    args = ap.parse_args()
    paths.ensure_dirs()
    (dev if args.stage == "dev" else final)(args)


if __name__ == "__main__":
    sys.exit(main())
