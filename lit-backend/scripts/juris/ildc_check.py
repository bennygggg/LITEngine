"""
Independent check on ILDC (35k Supreme Court cases, outcome text removed by its authors, i.e. a T1-like input), using the SAME TF-IDF + logistic
recipe as Juris. The public copy has no official split column, so this uses a temporal split by decision year (train <= 2015, test 2016-2020):
it shows how the recipe behaves on another court and corpus, and is NOT a re-run of the published splits.
Data: Malik et al. 2021 (CC-BY-NC), a public copy on the Hub; stored under data/juris/ildc (git-ignored).

    .venv-juris/bin/python -m scripts.juris.ildc_check
"""

import sys
import time

import numpy as np
import pandas as pd

from scripts.juris import paths
from scripts.juris.metrics import bootstrap_ci, metrics
from scripts.juris.model_def import make_juris
from scripts.juris.robustness import save

CSV = paths.DATA / "ildc" / "ILDC_complete_35k.csv"
MAX_CHARS = 30_000


def main() -> None:
    t0 = time.time()
    rows = []
    for chunk in pd.read_csv(CSV, usecols=["id", "text", "label"], chunksize=1500):
        chunk["text"] = chunk["text"].fillna("").str.slice(0, MAX_CHARS)
        rows.append(chunk)
    D = pd.concat(rows, ignore_index=True)
    D["year"] = D["id"].str.extract(r"^(\d{4})_")[0].astype(float)
    D = D.dropna(subset=["year", "label"])
    D["y"] = D["label"].astype(int)
    print(f"ILDC loaded: {len(D):,} cases, years {int(D.year.min())}-{int(D.year.max())}, share label 1 = {D.y.mean():.3f} ({time.time() - t0:.0f}s)", flush=True)
    rng = np.random.default_rng(3)
    if "--random" in sys.argv:        # a random split, closer in spirit to the published protocol (which is not temporal)
        perm = rng.permutation(len(D))
        te, tr = perm[:2600], perm[2600:22600]
        split_note = ("random 20,000 train / 2,600 test", "random", "random")
    else:
        tr_all = np.where(D["year"] <= 2015)[0]
        te = np.where(D["year"] >= 2016)[0]
        tr = rng.choice(tr_all, min(20_000, len(tr_all)), replace=False)
        split_note = ("temporal", "<= 2015", "2016-2020")
    X = lambda idx: pd.DataFrame({"text": D["text"].values[idx], "side": "unclear", "n_words": [len(t.split()) for t in D["text"].values[idx]]})
    m = make_juris(C=1.0, use_side=False).fit(X(tr), D["y"].values[tr])
    z = m.decision_function(X(te))
    p = 1 / (1 + np.exp(-z))
    yte = D["y"].values[te]
    r = metrics(yte, p)
    ci = bootstrap_ci(yte, p, n=500)
    res = {"dataset": f"ILDC (Malik et al. 2021), public Hub copy, {split_note[0]} split", "n_train": int(len(tr)), "n_test": int(len(te)), "train_years": split_note[1], "test_years": split_note[2],
           "label_1_share_test": round(float(yte.mean()), 3), "majority_acc": round(float(max(yte.mean(), 1 - yte.mean())), 4), "acc": round(float(r["acc"]), 4),
           "acc_ci95": [round(ci["acc"][0], 4), round(ci["acc"][1], 4)], "bal_acc": round(float(r["bal_acc"]), 4), "macro_f1": round(float(r["macro_f1"]), 4), "auc": round(float(r["auc"]), 4),
           "note": "uncalibrated class-weighted decision at 0; not the published splits; the authors' best model reports 78% accuracy on their own split"}
    print(res, flush=True)
    save("ildc_random_split_check" if "--random" in sys.argv else "ildc_temporal_check", res)


if __name__ == "__main__":
    sys.exit(main())
