"""
Side-specific routes. The joint model could not rank appeals by the State (test AUC 0.50); a model trained only on State appeals did (0.73,
chosen on validation data, then evaluated once more on the test period: a disclosed second look; see docs/JURIS_ROBUSTNESS.md). This module
fits that route and attaches it to the shipped artifact, so State appeals are scored by it and every other appeal by the unchanged joint model.

    .venv-juris/bin/python -m scripts.juris.routes attach     # loads data/juris/model/juris.joblib, adds the State route, rewrites it and the card
"""

import hashlib
import json
import sys
import time

import joblib
import numpy as np
from sklearn.model_selection import StratifiedGroupKFold

from scripts.juris import paths
from scripts.juris.model_def import make_juris
from scripts.juris.names import load_names
from scripts.juris.run_experiment import X_of, load_tier, platt
from services.juris_features import CalibratedJuris

SIDE = "state_appeal"


def fit_state_route(D, X, y, names, C: float = 1.0) -> CalibratedJuris:
    """Fit on every State appeal in the corpus; Platt scaling from grouped out-of-fold scores within those appeals."""
    idx = np.where(D["side"].values == SIDE)[0]
    Xs, ys = X.iloc[idx], y[idx]
    oof = np.zeros(len(idx))
    for tr, te in StratifiedGroupKFold(n_splits=3, shuffle=True, random_state=42).split(Xs, ys, D["cnr"].values[idx]):
        fold = make_juris(C=C, stop_words=names).fit(Xs.iloc[tr], ys[tr])
        oof[te] = fold.decision_function(Xs.iloc[te])
    a, b = platt(oof, ys)
    cal = CalibratedJuris(make_juris(C=C, stop_words=names).fit(Xs, ys), a=a, b=b, meta={"route": SIDE, "n": int(len(idx))})
    cal.finalize(Xs)
    cal.baseline_p_ = float(cal.predict_proba(Xs)[:, 1].mean())
    return cal


def route_card_entry(n: int, succeeds: int) -> dict:
    rb = json.loads((paths.REPORT_DIR / "robustness.json").read_text())["state_specific_model_test_second_look"]
    j, s = rb["joint model, State appeals"], rb["State-specific model, State appeals"]
    return {
        "side": SIDE, "trained_on_n": n, "class_balance": {"succeeds": succeeds, "dismissed": n - succeeds},
        "evaluation": {"status": "chosen on validation data, then evaluated once on the test period (a disclosed second look at the test split)",
                       "n_test": rb["n_state_test"], "succeeds_share_test": rb["state_test_succeeds_share"],
                       "auc_within_state_appeals": s["auc"], "joint_model_auc_within_state_appeals": j["auc"],
                       "brier": s["brier"], "joint_model_brier": j["brier"], "accuracy": s["acc"]},
    }


def attach() -> None:
    names = load_names() or None
    D = load_tier("t2", 100)
    y = (D["label"] == "succeeds").astype(int).values
    X = X_of(D, "t2")
    art = paths.MODEL_DIR / "juris.joblib"
    card_p = paths.MODEL_DIR / "model_card.json"
    card = json.loads(card_p.read_text())
    cal = joblib.load(art)
    cal.baseline_p_ = float(card["baseline_p"])
    t0 = time.time()
    route = fit_state_route(D, X, y, names)
    cal.side_models = {SIDE: route}
    h = hashlib.sha256(np.asarray(cal.pipeline.named_steps["clf"].coef_).tobytes() + np.asarray(route.pipeline.named_steps["clf"].coef_).tobytes()).hexdigest()[:8]
    cal.meta = {**cal.meta, "version": f"juris-{time.strftime('%Y%m%d')}-{h}", "routes": [SIDE]}
    joblib.dump(cal, art, compress=3)
    n_state = route.meta["n"]
    card["version"] = cal.meta["version"]
    card["artifact_sha256"] = hashlib.sha256(art.read_bytes()).hexdigest()
    card["routes"] = [route_card_entry(n_state, int(y[np.where(D["side"].values == SIDE)[0]].sum()))]
    card["reads"] = card["reads"]
    limit = ("Appeals by the State or a complainant are scored by a separate model trained only on such appeals (about 9% succeed). It ranks them well above chance "
             "(AUC 0.73 on the test period) but from far fewer cases, so its estimates are less certain than those for the accused's own appeal.")
    card["limits"] = [x for x in card["limits"] if "State" not in x or "appellant" in x.lower()] + ([limit] if limit not in card["limits"] else [])
    card_p.write_text(json.dumps(card, indent=2))
    print(f"attached the State route ({n_state:,} State appeals) in {time.time() - t0:.0f}s: version {cal.meta['version']}, "
          f"artifact {art.stat().st_size / 1e6:.2f} MB, sha {card['artifact_sha256'][:8]}")


if __name__ == "__main__":
    {"attach": attach}[sys.argv[1]]()
