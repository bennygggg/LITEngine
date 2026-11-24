"""Extend the dev C grid downward when the best value sits on its boundary (writes into reports/dev.json; validation year only)."""

import json
import sys

from scripts.juris import paths
from scripts.juris.model_def import make_juris
from scripts.juris.names import load_names
from scripts.juris.metrics import metrics
from scripts.juris.run_experiment import X_of, fit_calibrated, load_tier, prob, recency_weights, splits, TRAIN_MAX


def main() -> None:
    p = paths.REPORT_DIR / "dev.json"
    dev = json.loads(p.read_text())
    names = load_names() or None
    D = load_tier("t2", 100)
    sp = splits(D)
    y = (D["label"] == "succeeds").astype(int).values
    tr, va = sp["train"], sp["val"]
    X = X_of(D, "t2")
    H = dev.get("recency_H")
    best_c = dev["best_C"]
    best_ll = dev["val_results"][f"juris_lr C={best_c}"]["logloss"]
    for C in (0.5, 0.25):
        if C >= min(dev_c for dev_c in [best_c]):
            pass
        m = fit_calibrated(lambda: make_juris(C=C, stop_words=names), X.iloc[tr], y[tr], X.iloc[va], y[va], recency_weights(D["decision_year"].values[tr], H, TRAIN_MAX))
        r = metrics(y[va], prob(m, X.iloc[va]))
        dev["val_results"][f"juris_lr C={C}"] = r
        print(f"  juris_lr C={C:<5} " + "  ".join(f"{k}={v:.3f}" for k, v in r.items() if k in ("acc", "bal_acc", "auc", "logloss", "ece")), flush=True)
        if r["logloss"] < best_ll - 0.001:
            best_c, best_ll = C, r["logloss"]
        else:
            break                       # no improvement: the optimum is interior
    dev["best_C"] = best_c
    dev["c_grid_extended"] = True
    p.write_text(json.dumps(dev, indent=2))
    print("best_C =", best_c)


if __name__ == "__main__":
    sys.exit(main())
