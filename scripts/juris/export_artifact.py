"""
Export the shipped Juris artifact (data/juris/model/juris.joblib + model_card.json).

The accuracy printed on the card comes from reports/final.json (the model trained on <= 2021, calibrated on 2022, evaluated once
on 2023+). The SHIPPED model is then refit on every kept case (more data, same hyperparameters), with the Platt scaler fitted on
grouped out-of-fold scores so it is not fitted on cases the model was trained on.

    .venv-juris/bin/python -m scripts.juris.export_artifact [--allow-dev-card]
"""

import argparse
import hashlib
import json
import sys
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold

from scripts.juris import paths
from scripts.juris.model_def import make_juris
from scripts.juris.names import load_names
from scripts.juris.run_experiment import X_of, load_tier, platt, recency_weights
from services.juris_features import CalibratedJuris

SIZE_BUDGET_MB = 9.5   # HF git rejects non-LFS files over 10 MB


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-dev-card", action="store_true", help="build the card from dev.json when final.json does not exist (not for shipping)")
    ap.add_argument("--min-t2-words", type=int, default=100)
    ap.add_argument("--max-features", type=int, default=0, help="override the vocabulary size (0 = use the value that fits the size budget)")
    args = ap.parse_args()
    paths.ensure_dirs()
    t0 = time.time()
    final_p, dev_p = paths.REPORT_DIR / "final.json", paths.REPORT_DIR / "dev.json"
    if final_p.exists():
        report, status = json.loads(final_p.read_text()), "final"
    elif args.allow_dev_card and dev_p.exists():
        report, status = json.loads(dev_p.read_text()), "dev-only"
    else:
        sys.exit("No reports/final.json: run `run_experiment final` first (or pass --allow-dev-card for a non-shipping test artifact).")
    cfg_c = (report.get("config") or report)["best_C" if "best_C" in report else "C"]
    cfg_h = (report.get("config") or report).get("recency_H")
    names = load_names() or None

    D = load_tier("t2", args.min_t2_words)           # the same merits-judgment filter that training and evaluation used
    y = (D["label"] == "succeeds").astype(int).values
    X = X_of(D, "t2")
    print(f"export: refit on {len(D)} cases, C={cfg_c}", flush=True)

    best = None
    for max_features in ([args.max_features] if args.max_features else [150_000, 120_000, 90_000, 60_000]):
        w_all = recency_weights(D["decision_year"].values, cfg_h, int(D["decision_year"].max()))
        pipe = make_juris(C=cfg_c, stop_words=names, max_features=max_features)
        pipe.fit(X, y) if w_all is None else pipe.fit(X, y, clf__sample_weight=w_all)
        cal = CalibratedJuris(pipe, meta={})
        # Platt scaler from grouped out-of-fold decision values (3 folds)
        oof = np.zeros(len(D))
        for tr, te in StratifiedGroupKFold(n_splits=3, shuffle=True, random_state=42).split(X, y, D["cnr"].values):
            fold = make_juris(C=cfg_c, stop_words=names, max_features=max_features)
            fold.fit(X.iloc[tr], y[tr]) if w_all is None else fold.fit(X.iloc[tr], y[tr], clf__sample_weight=w_all[tr])
            oof[te] = fold.decision_function(X.iloc[te])
        cal.a, cal.b = platt(oof, y)
        cal.finalize(X)
        p_train = cal.predict_proba(X)[:, 1]
        if status == "final":
            ev = report["tiers"]["T2 pre-reasoning (ships)"]
            base = report["baselines"]["majority"]
            n_info = report["n"]
        else:   # a non-shipping test artifact: validation-year numbers, labelled as such
            vr = report["val_results"]
            ev = {**vr[f"juris_lr C={cfg_c}"], "ci": {}}
            base = vr["majority"]
            n_info = {"test": report["n_val"]}
        meta = {
            "schema": "juris-text-v1", "version": f"juris-{time.strftime('%Y%m%d')}-{hashlib.sha256(np.asarray(pipe.named_steps['clf'].coef_).tobytes()).hexdigest()[:8]}",
            "trained_on_n": int(len(D)), "C": cfg_c, "recency_H": cfg_h, "max_features": max_features, "built_at": time.strftime("%Y-%m-%d %H:%M:%S"), "card_status": status,
        }
        cal.meta = meta
        out = paths.MODEL_DIR / "juris.joblib"
        joblib.dump(cal, out, compress=3)
        size_mb = out.stat().st_size / 1e6
        print(f"  max_features={max_features}: {size_mb:.2f} MB", flush=True)
        best = (cal, p_train, ev, base, n_info, size_mb, meta)
        if size_mb <= SIZE_BUDGET_MB:
            break
    cal, p_train, ev, base, n_info, size_mb, meta = best
    if size_mb > SIZE_BUDGET_MB:
        print(f"WARNING: artifact is {size_mb:.1f} MB, over the {SIZE_BUDGET_MB} MB git budget; ship it through the private HF artifact repo instead.")
    sha = hashlib.sha256((paths.MODEL_DIR / "juris.joblib").read_bytes()).hexdigest()
    yrs = D["decision_year"]
    split_cfg = report.get("config", {})
    card = {
        "model_name": "Juris", "version": meta["version"], "artifact": "juris.joblib", "artifact_sha256": sha, "schema": meta["schema"],
        "scope": "Criminal appeals (trained on Indian High Court criminal-appeal judgments)",
        "target": "succeeds = the appeal was allowed in whole or in part (the appellant obtained relief); dismissed = dismissed on the merits",
        "reads": "the facts, trial-court findings and grounds in the document (never the appellate court's own reasoning) plus who is appealing",
        "trained_on": {"n": int(len(D)), "class_balance": {"succeeds": int(y.sum()), "dismissed": int(len(y) - y.sum())},
                       "period": f"{int(yrs.min())}-{int(yrs.max())}", "courts": int(D["bench"].nunique()),
                       "note": "Public High Court judgments (Dattam Labs open data, CC-BY-4.0); labels from court disposal records cross-checked against the order text"},
        "evaluation": {
            "status": status, "split": f"trained on decisions up to {split_cfg.get('train_max', 2021)}, calibrated on {split_cfg.get('val_year', 2022)}, tested once on {split_cfg.get('test_min', 2023)} onward",
            "period": (f"{split_cfg.get('test_min', 2023)}-{int(yrs.max())}" if status == "final" else "2022 (validation year, dev-only)"), "n_test": n_info.get("test"), "accuracy": ev.get("acc"), "accuracy_ci": (ev.get("ci") or {}).get("acc"),
            "auc": ev.get("auc"), "macro_f1": ev.get("macro_f1"), "balanced_accuracy": ev.get("bal_acc"), "brier": ev.get("brier"), "ece": ev.get("ece"),
            "baseline_accuracy": base.get("acc"),
        },
        "baseline_p": float(p_train.mean()), "baseline_logit": float(cal.baseline_logit),
        "limits": [
            "Reads wording, not legal merit; an estimate, not a prediction of what a court will do.",
            "Trained on High Court appeals; not validated for the Supreme Court or for trial-court matters.",
            "Appellant type is entered by the user; a private complainant appealing an acquittal is not distinguished from the State.",
            "Outcome labels come from court records and may contain residual noise.",
            'About one training appeal in nine concerns bail or a sentence suspension inside the appeal (for example under section 14A of the SC/ST Act). These succeed more often (about 75% against 57% for the rest) and Juris reads them like any other appeal.',
            "Success rates differ widely between benches in the source records (one bench's records show about 95%). Juris does not take the court as an input, but wording correlates with it; per-bench results are in the model card document.",
        ],
    }
    (paths.MODEL_DIR / "model_card.json").write_text(json.dumps(card, indent=2, default=str))
    print(f"wrote juris.joblib ({size_mb:.2f} MB, sha {sha[:8]}) and model_card.json [{status}] in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    sys.exit(main())
