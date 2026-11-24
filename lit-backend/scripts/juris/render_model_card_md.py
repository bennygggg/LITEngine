"""
Render docs/MODEL_CARD.md from data/juris/model/model_card.json and data/juris/reports/final.json, so the document never
states a number the shipped model does not have.

    .venv-juris/bin/python -m scripts.juris.render_model_card_md
"""

import json
import sys
from pathlib import Path

from scripts.juris import paths

DOC = paths.BACKEND.parent / "docs" / "MODEL_CARD.md"


def p(x: float, d: int = 1) -> str:
    return f"{100 * x:.{d}f} %"


def main() -> None:
    card = json.loads((paths.MODEL_DIR / "model_card.json").read_text())
    final = json.loads((paths.REPORT_DIR / "final.json").read_text())
    ev, tr = card["evaluation"], card["trained_on"]
    t = final["tiers"]
    t2 = t["T2 pre-reasoning (ships)"]
    t1, t0, t2c = t["T1 order-stripped (same capped training set)"], t["T0 full text (same capped training set)"], t["T2 pre-reasoning (same capped training set)"]
    cap = final["n"]["tier_comparison_train_cap"]
    b = final["baselines"]
    ci = t2["ci"]["acc"]
    side, meta, maj = b["side_only"], b["meta_only(bench,year,ctype,side)"], b["majority"]
    sides = {r["side"]: r for r in final["by_side"]}
    weak = ""
    route = next((r for r in card.get("routes", []) if r["side"] == "state_appeal"), None)
    if "state_appeal" in sides and route:
        st, ev2 = sides["state_appeal"], route["evaluation"]
        weak = (f"Appeals by the State or a complainant ({st['n']:,} test cases, {p(st['succeeds_share'], 0)} succeeded): the joint model could not rank them "
                f"(AUC {st['auc']:.2f}), so Juris scores them with a separate model trained only on such appeals ({route['trained_on_n']:,} cases). On the test period that model "
                f"reaches AUC {ev2['auc_within_state_appeals']:.2f} within State appeals (Brier {ev2['brier']:.3f} against {ev2['joint_model_brier']:.3f}). It was chosen on validation data and "
                f"then evaluated once on the test split, a disclosed second look; its estimates are still less certain than those for the accused's own appeal.")
    elif "state_appeal" in sides:
        st = sides["state_appeal"]
        weak = (f"For appeals by the State or a complainant ({st['n']:,} test cases, {p(st['succeeds_share'], 0)} succeeded) Juris is right {p(st['acc'], 0)} of the time "
                f"but cannot rank such appeals against each other (AUC {st['auc']:.2f}): it returns the base rate, and the card says so.")
    extras = []
    if weak:
        extras.append(weak)
    extras.append(f"The share of appeals that succeed drifts upward with decision year in the source records ({p(final['n']['train_succeeds_share'], 0)} in training, "
                  f"{p(final['n']['test_succeeds_share'], 0)} in the test period); the temporal split and the test-period baseline account for that, and calibration was slightly "
                  f"under-confident in the test period (expected calibration error {p(t2['ece'])}).")
    extras.append("In the training data the appellant was read from the case title's party order; at serving it is whatever the user states.")
    extras.append("Not legal advice. Not validated for any use that affects a person's liberty or rights.")
    rows = "\n".join(f"| {r['bench']} | {r['n']:,} | {p(r['succeeds_share'], 0)} | {p(r['acc'], 0)} | {r['auc']:.2f} |" for r in final["by_bench"][:12])
    DOC.write_text(f"""# Juris — model card

Machine-readable source: `lit-backend/data/juris/model/model_card.json` (written by `scripts/juris/export_artifact.py`; the app reads it
at runtime so the UI never states a number the model does not have). This file is rendered from that card and
`data/juris/reports/final.json` by `scripts/juris/render_model_card_md.py`. Pipeline and guardrails: `lit-backend/scripts/juris/README.md`. Robustness, sensitivity and ablation results: `JURIS_ROBUSTNESS.md`. Corpus datasheet: `JURIS_DATASHEET.md`.

## What it is

Juris is the project's own appeal-outcome model. For a **criminal appeal** it estimates the probability of *any appellate
relief* (`succeeds`: allowed in whole or in part) rather than dismissal on the merits. It is a regularised logistic regression
over word and phrase weights (TF-IDF), who is appealing, the sections cited and the length of the text, followed by Platt
calibration. It is linear on purpose: every weight is a phrase or input a reader can inspect, which is what the card shows.

**What it reads.** The facts, trial-court findings, grounds and submissions in the document — the **pre-reasoning** part, cut by the
same code in training and serving (`services/juris_text.py`) — plus the appeal type the user states. It never sees the appellate
court's own reasoning or order, so it cannot read the answer off a judgment, and it never infers who is appealing from the text.

| | |
|---|---|
| Training data | **{tr['n']:,}** Indian High Court criminal-appeal judgments, decided {tr['period']}, from {tr['courts']} benches ({tr['class_balance']['succeeds']:,} succeeded, {tr['class_balance']['dismissed']:,} dismissed). Public records (Dattam Labs, CC-BY-4.0). |
| Labels | The court's own disposal record, cross-checked against the order text. Procedural endings, interim bail/suspension orders and records whose metadata and text disagree are excluded. |
| Evaluation | Trained on decisions up to 2021, calibrated on 2022, **tested once on {ev['n_test']:,} later cases ({ev['period']})**. |
| Accuracy on the test cases | **{p(t2['acc'])}** (95 % CI {p(ci[0])}–{p(ci[1])}); AUC **{t2['auc']:.3f}**; macro-F1 {p(t2['macro_f1'])} |
| Always guessing the more common outcome | {p(maj['acc'])} |
| Appeal type alone | {p(side['acc'])} accuracy, AUC {side['auc']:.3f} |
| Court, year, case type and appeal type, no text | {p(meta['acc'])} accuracy, AUC {meta['auc']:.3f} |
| Calibration (test) | Brier {t2['brier']:.3f}, expected calibration error {t2['ece']:.3f} |
| Scope | Criminal appeals. Civil and other matters get facts, precedents and the argument map, and no estimate. |
| Artifact | `juris.joblib` (sha256 `{card['artifact_sha256'][:8]}…`, version `{card['version']}`): published to the private dataset repo and downloaded by the Space at start, which accepts it only if the sha256 pinned in the committed card matches. |

### Why the leakage tiers matter

A judgment contains its own answer, so what a model is allowed to read decides what its accuracy means. The three rows below were
trained on the same {cap:,} cases, so they differ only in what the model may read; the last row is the shipped model, trained on the
full training set.

| Input to the model | Accuracy | AUC |
|---|---|---|
| Full judgment (upper bound; not a prediction) | {p(t0['acc'])} | {t0['auc']:.3f} |
| Order removed, reasoning kept (the protocol used in the ILDC benchmark) | {p(t1['acc'])} | {t1['auc']:.3f} |
| **Pre-reasoning only (what Juris reads)** | **{p(t2c['acc'])}** | **{t2c['auc']:.3f}** |
| Pre-reasoning only, full training set (**the shipped model**) | **{p(t2['acc'])}** | **{t2['auc']:.3f}** |

Juris ships on the last row: it is the only input that exists for a live case.

### By court (test cases; benches with at least 100)

| Bench | Cases | Succeeded | Accuracy | AUC |
|---|---|---|---|---|
{rows}

## How the product presents it

- Rounded to the nearest 5 % and clamped to 5–95 %; no confidence interval is claimed on a single case.
- Wording is "indicative research estimate"; the card says what Juris reads and does not read.
- Contribution bars are **centred** on a typical training case and add up to the estimate's logit (`baseline_logit + sum(bars)`; a test enforces it).
- The legacy five-score heuristic is shown only as a collapsed, "uncalibrated" comparison row, and is the fallback if Juris fails to load.
- `appellant_type` and `filing_date` are never inferred (see `PROTOCOL.md`).
- Scenarios re-score Juris after editing what it reads (appeal type, cited sections). They show how the *model* responds, not that changing a fact would change the real outcome.

## Known limitations

""" + "\n".join(f"{i}. {x}" for i, x in enumerate([x for x in card["limits"] if not x.startswith("Appeals by the State")] + extras, 1)) + """

## Changing it

Retrain with `scripts/juris/` (see its README): `run_experiment dev`, then `run_experiment final` (one look at the test split),
then `export_artifact`, then this renderer. Re-run the scenario tests and re-record the demo (`DEMO.md`).
""")
    print(f"wrote {DOC}")


if __name__ == "__main__":
    sys.exit(main())
