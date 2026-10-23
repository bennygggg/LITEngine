"""
Generate data/outcome_dataset/model/model_card.json for the shipped binary outcome model.

The card feeds three things: the Outcome card's honesty panel (N, CV accuracy vs base rate), centred feature
contributions (`coef * (x - training_mean)`, so bars read relative to a typical case instead of zero) and the
scenario engine's realistic lever ranges and warnings.

    python scripts/build_model_card.py        # needs data/outcome_dataset/dataset_v2.csv (local only)
"""

import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict

import joblib

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.outcome_dataset.train_model import FEATURE_COLUMNS, load_usable_rows  # noqa: E402

MODEL_DIR = ROOT / "data" / "outcome_dataset" / "model"
MODEL_PATH = MODEL_DIR / "outcome_classifier_binary.joblib"
REPORT = MODEL_DIR / "training_report_binary.json"
OUT = MODEL_DIR / "model_card.json"

DISPLAY = {
    "precedent_alignment": "Precedent alignment",
    "statutory_strength": "Statutory strength",
    "argument_completeness": "Argument completeness",
    "case_complexity": "Case complexity",
    "court_level": "Court level",
}
APPELLANT_DISPLAY = {
    "accused_appeal": "Appeal by the accused",
    "state_appeal": "Appeal by the State / complainant",
    "unclear": "Appeal type not specified",
}


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def main() -> None:
    rows = load_usable_rows()
    report: Dict[str, Any] = json.loads(REPORT.read_text(encoding="utf-8"))
    pipeline = joblib.load(MODEL_PATH)
    coefs = report["coefficients"]["coefficients"]["succeeds"]

    features: Dict[str, Any] = {}
    for col in FEATURE_COLUMNS:
        key = col.replace("feature_", "")
        values = [float(r[col]) for r in rows]
        features[key] = {
            "display_name": DISPLAY[key], "coef": coefs[col],
            "mean": sum(values) / len(values), "min": min(values), "max": max(values),
            "std": math.sqrt(sum((v - sum(values) / len(values)) ** 2 for v in values) / len(values)),
        }
    appellant_counts: Dict[str, int] = {}
    for r in rows:
        appellant_counts[r["appellant_type"]] = appellant_counts.get(r["appellant_type"], 0) + 1
    n = len(rows)
    appellant = {
        k: {"display_name": APPELLANT_DISPLAY[k], "coef": coefs[f"appellant_type={k}"], "share": appellant_counts.get(k, 0) / n}
        for k in APPELLANT_DISPLAY
    }
    baseline_logit = coefs["intercept"] + sum(f["coef"] * f["mean"] for f in features.values()) + sum(
        a["coef"] * a["share"] for a in appellant.values()
    )
    cv = report["cv_summary"]
    card = {
        "model_name": "Logistic regression (binary: dismissed vs succeeds)",
        "artifact": MODEL_PATH.name,
        "artifact_sha256": hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest(),
        "scope": "Criminal appeals",
        "target": "succeeds = any appellate relief, including partial relief",
        "trained_on": {
            "n": report["usable_n"], "class_balance": report["label_counts_binary"],
            "note": "Indian criminal-appeal judgments; labels derived from judgment text by rules",
        },
        "cv": {
            "folds": report["n_splits"],
            "accuracy": round(cv["new_model"]["mean_accuracy"], 4), "accuracy_std": round(cv["new_model"]["std_accuracy"], 4),
            "macro_f1": round(cv["new_model"]["mean_macro_f1"], 4),
            "baseline_accuracy": round(cv["majority"]["mean_accuracy"], 4),
            "heuristic_accuracy": round(cv["old_heuristic"]["mean_accuracy"], 4),
        },
        "intercept": coefs["intercept"],
        "features": features,
        "appellant": appellant,
        "baseline_logit": baseline_logit,
        "baseline_p": sigmoid(baseline_logit),
        "feature_extractor": {
            "embedder": "sentence-transformers/all-MiniLM-L6-v2",
            "chunker": "500 words / 50 overlap (legacy)",
            "precedent_similarity": "1/(1+d), d = squared L2 distance on L2-normalised vectors",
            "profile_extraction": "rules",
        },
        "caveats": [
            "Appeal type dominates the estimate; the other inputs move it by only a few points.",
            "Inputs are crude counts and averages derived from the case profile, not legal merit.",
            "Labels were derived from judgment text, so label noise is part of the accuracy figure.",
        ],
    }
    OUT.write_text(json.dumps(card, indent=2), encoding="utf-8")
    print(f"wrote {OUT}: n={n}, baseline_p={card['baseline_p']:.3f}, cv_acc={card['cv']['accuracy']}")


if __name__ == "__main__":
    main()
