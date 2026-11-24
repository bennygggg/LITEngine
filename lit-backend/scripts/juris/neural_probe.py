"""
Neural baseline on a subsample, locally (free): frozen law-ai/InLegalBERT embeddings of the first 512 tokens of the pre-reasoning text, a
logistic head, and a late fusion with the TF-IDF model, all on the SAME training and validation cases (decisions <= 2021 / 2022).
Reports AUC and balanced accuracy (threshold-free or at the balanced point), validation year only; the test split is not read.

    .venv-juris/bin/python -m scripts.juris.neural_probe [--train 8000] [--val 3000]
"""

import argparse
import json
import sys
import time

import numpy as np
from scipy.stats import rankdata
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score, roc_auc_score
from sklearn.preprocessing import StandardScaler

from scripts.juris import paths
from scripts.juris.model_def import make_juris
from scripts.juris.names import load_names
from scripts.juris.robustness import save
from scripts.juris.run_experiment import X_of, load_tier, splits

MODEL = "law-ai/InLegalBERT"


def embed(texts, batch=16):
    import torch
    from transformers import AutoModel, AutoTokenizer
    dev = "mps" if torch.backends.mps.is_available() else "cpu"
    tok, model = AutoTokenizer.from_pretrained(MODEL), AutoModel.from_pretrained(MODEL).to(dev).eval()
    try:
        model.half()
        half = True
    except Exception:  # noqa: BLE001
        half = False
    out, t0 = [], time.time()
    for i in range(0, len(texts), batch):
        enc = tok(list(texts[i:i + batch]), truncation=True, max_length=512, padding=True, return_tensors="pt").to(dev)
        with torch.no_grad():
            h = model(**enc).last_hidden_state.float()
        mask = enc["attention_mask"].unsqueeze(-1).float()
        out.append(((h * mask).sum(1) / mask.sum(1)).cpu().numpy())          # mean pooling over real tokens
        if (i // batch) % 40 == 0:
            print(f"  embedded {i + batch}/{len(texts)}  {(i + batch) / max(time.time() - t0, 1e-9):.1f} docs/s (device={dev}, fp16={half})", flush=True)
    return np.vstack(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", type=int, default=8000)
    ap.add_argument("--val", type=int, default=3000)
    args = ap.parse_args()
    D = load_tier("t2", 100)
    sp = splits(D)
    rng = np.random.default_rng(77)
    tr = rng.choice(sp["train"], min(args.train, len(sp["train"])), replace=False)
    va = rng.choice(sp["val"], min(args.val, len(sp["val"])), replace=False)
    y = (D["label"] == "succeeds").astype(int).values
    cache = paths.DATA / "emb_cache.npz"
    if cache.exists() and np.load(cache)["idx"].tolist() == np.concatenate([tr, va]).tolist():
        E = np.load(cache)["E"]
    else:
        E = embed(D["t2"].values[np.concatenate([tr, va])])
        np.savez(cache, E=E, idx=np.concatenate([tr, va]))
    Etr, Eva = E[: len(tr)], E[len(tr):]
    side = lambda idx: np.array([[s == k for k in ("accused_appeal", "state_appeal", "unclear")] for s in D["side"].values[idx]], dtype=float)
    sc = StandardScaler().fit(Etr)
    Ftr, Fva = np.hstack([sc.transform(Etr), side(tr)]), np.hstack([sc.transform(Eva), side(va)])
    best = None
    for C in (0.003, 0.01, 0.03, 0.1):
        lr = LogisticRegression(C=C, class_weight="balanced", max_iter=3000).fit(Ftr, y[tr])
        z = lr.decision_function(Fva)
        auc = roc_auc_score(y[va], z)
        if best is None or auc > best[0]:
            best = (auc, C, z)
    auc_e, C_e, z_e = best
    names = load_names() or None
    tf = make_juris(C=1.0, stop_words=names).fit(X_of(D.iloc[tr], "t2"), y[tr])
    z_t = tf.decision_function(X_of(D.iloc[va], "t2"))
    fuse = (rankdata(z_t) + rankdata(z_e)) / (2 * len(va))
    row = lambda z, thr=0.0: {"auc": round(float(roc_auc_score(y[va], z)), 4), "bal_acc": round(float(balanced_accuracy_score(y[va], (z >= thr).astype(int))), 4)}
    res = {"n_train": int(len(tr)), "n_val": int(len(va)), "model": MODEL, "pooling": "mean over the first 512 tokens of the pre-reasoning text",
           "embeddings_plus_appeal_type (LR, C=%g chosen on val)" % C_e: row(z_e), "tfidf_model_same_cases": row(z_t),
           "late_fusion (rank average)": row(fuse - 0.5)}
    print(json.dumps(res, indent=2), flush=True)
    save("neural_probe_val2022", res)


if __name__ == "__main__":
    sys.exit(main())
