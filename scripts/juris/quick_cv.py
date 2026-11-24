"""
Gate G1 / dev loop: grouped cross-validation on whatever corpus is built, across leakage tiers and baselines.
Uses NO held-out test split (that one is touched exactly once, by evaluate.py --final).

    .venv-juris/bin/python -m scripts.juris.quick_cv --folds 5
"""

import argparse
import json
import sys
import time

import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score, roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold

from scripts.juris import paths
from scripts.juris.corpus import KEEP, load_corpus
from scripts.juris.model_def import make_juris
from scripts.juris.names import load_names


def frame(D: pd.DataFrame, tier: str) -> pd.DataFrame:
    X = pd.DataFrame({"text": D[tier], "side": D["side"], "n_words": D["n" + tier[1]]})
    return X


def metrics(y, p, thr=0.5):
    pred = (p >= thr).astype(int)
    return {"acc": accuracy_score(y, pred), "bal_acc": balanced_accuracy_score(y, pred), "macro_f1": f1_score(y, pred, average="macro"),
            "auc": roc_auc_score(y, p)}


def cv(D: pd.DataFrame, make, tier_cols, folds: int, groups, y) -> dict:
    sgkf = StratifiedGroupKFold(n_splits=folds, shuffle=True, random_state=42)
    oof = np.zeros(len(D))
    for tr, te in sgkf.split(D, y, groups):
        m = make()
        Xtr, Xte = tier_cols(D.iloc[tr]), tier_cols(D.iloc[te])
        m.fit(Xtr, y[tr])
        oof[te] = m.predict_proba(Xte)[:, 1]
    return metrics(y, oof)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--min-t2-words", type=int, default=100)
    ap.add_argument("--C", type=float, default=4.0)
    args = ap.parse_args()
    D = load_corpus()
    D = D[D["n2"] >= args.min_t2_words].reset_index(drop=True)
    y = (D["label"] == "succeeds").astype(int).values
    groups = D["cnr"].values
    print(f"corpus {len(D)} cases; succeeds share {y.mean():.3f}; benches {D['bench'].nunique()}; years {D['decision_year'].min()}-{D['decision_year'].max()}")
    base = {"majority_acc": max(y.mean(), 1 - y.mean())}
    out = {"n": len(D), "succeeds_share": float(y.mean()), "baselines": base}
    side_only = lambda d: pd.DataFrame({"text": [""] * len(d), "side": d["side"].values, "n_words": 0})
    meta_only = lambda d: pd.DataFrame({"text": (d["bench"] + " yr" + d["decision_year"].astype(str) + " " + d["ctype"].fillna("")).values,
                                        "side": d["side"].values, "n_words": 0})
    t0 = time.time()
    res = {}
    res["side_only"] = cv(D, lambda: make_juris(use_text=False, use_sections=False), side_only, args.folds, groups, y)
    res["meta_only(bench,year,ctype,side)"] = cv(D, lambda: make_juris(min_df=3, use_sections=False), meta_only, args.folds, groups, y)
    names = load_names() or None
    res["T2 + proper nouns kept (ablation)"] = cv(D, lambda: make_juris(C=args.C), lambda d: frame(d, "t2"), args.folds, groups, y)
    print("  T2 + proper nouns kept (ablation)  " + "  ".join(f"{k}={v:.3f}" for k, v in res["T2 + proper nouns kept (ablation)"].items()), flush=True)
    for tier, name in (("t2", "T2 pre-reasoning (ships)"), ("t1", "T1 order-stripped (ILDC-style)"), ("t0", "T0 full text (upper bound)")):
        res[name] = cv(D, lambda: make_juris(C=args.C, stop_words=names), lambda d, t=tier: frame(d, t), args.folds, groups, y)
        print(f"  {name:34s} " + "  ".join(f"{k}={v:.3f}" for k, v in res[name].items()), flush=True)
    for k in ("side_only", "meta_only(bench,year,ctype,side)"):
        print(f"  {k:34s} " + "  ".join(f"{a}={b:.3f}" for a, b in res[k].items()))
    print("majority baseline accuracy:", round(base["majority_acc"], 3), " secs", round(time.time() - t0))
    out["cv"] = res
    (paths.REPORT_DIR / "quick_cv.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    sys.exit(main())
