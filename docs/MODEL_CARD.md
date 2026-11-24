# Juris — model card

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
| Training data | **107,847** Indian High Court criminal-appeal judgments, decided 2008-2026, from 41 benches (63,404 succeeded, 44,443 dismissed). Public records (Dattam Labs, CC-BY-4.0). |
| Labels | The court's own disposal record, cross-checked against the order text. Procedural endings, interim bail/suspension orders and records whose metadata and text disagree are excluded. |
| Evaluation | Trained on decisions up to 2021, calibrated on 2022, **tested once on 32,573 later cases (2023-2026)**. |
| Accuracy on the test cases | **75.3 %** (95 % CI 74.8 %–75.8 %); AUC **0.795**; macro-F1 71.9 % |
| Always guessing the more common outcome | 65.6 % |
| Appeal type alone | 73.7 % accuracy, AUC 0.643 |
| Court, year, case type and appeal type, no text | 73.1 % accuracy, AUC 0.678 |
| Calibration (test) | Brier 0.169, expected calibration error 0.050 |
| Scope | Criminal appeals. Civil and other matters get facts, precedents and the argument map, and no estimate. |
| Artifact | `juris.joblib` (sha256 `fc2a3519…`, version `juris-20261124-5d72af41`): published to the private dataset repo and downloaded by the Space at start, which accepts it only if the sha256 pinned in the committed card matches. |

### Why the leakage tiers matter

A judgment contains its own answer, so what a model is allowed to read decides what its accuracy means. The three rows below were
trained on the same 20,000 cases, so they differ only in what the model may read; the last row is the shipped model, trained on the
full training set.

| Input to the model | Accuracy | AUC |
|---|---|---|
| Full judgment (upper bound; not a prediction) | 90.7 % | 0.958 |
| Order removed, reasoning kept (the protocol used in the ILDC benchmark) | 82.7 % | 0.884 |
| **Pre-reasoning only (what Juris reads)** | **74.0 %** | **0.772** |
| Pre-reasoning only, full training set (**the shipped model**) | **75.3 %** | **0.795** |

Juris ships on the last row: it is the only input that exists for a live case.

### By court (test cases; benches with at least 100)

| Bench | Cases | Succeeded | Accuracy | AUC |
|---|---|---|---|---|
| cghccisdb | 6,641 | 81 % | 79 % | 0.73 |
| patnahcucisdb94 | 2,610 | 74 % | 79 % | 0.77 |
| karnataka_bng_old | 2,607 | 56 % | 74 % | 0.79 |
| cishclko | 2,416 | 96 % | 95 % | 0.81 |
| jhar_pg | 2,165 | 56 % | 62 % | 0.64 |
| hc_cis_mas | 1,623 | 59 % | 72 % | 0.78 |
| phhc | 1,574 | 52 % | 64 % | 0.73 |
| taphc | 1,329 | 56 % | 82 % | 0.89 |
| hcaurdb | 1,179 | 52 % | 71 % | 0.78 |
| mdubench | 1,051 | 60 % | 67 % | 0.72 |
| cisnc | 1,049 | 71 % | 78 % | 0.80 |
| calcutta_appellate_side | 817 | 57 % | 71 % | 0.76 |

## How the product presents it

- Rounded to the nearest 5 % and clamped to 5–95 %; no confidence interval is claimed on a single case.
- Wording is "indicative research estimate"; the card says what Juris reads and does not read.
- Contribution bars are **centred** on a typical training case and add up to the estimate's logit (`baseline_logit + sum(bars)`; a test enforces it).
- The legacy five-score heuristic is shown only as a collapsed, "uncalibrated" comparison row, and is the fallback if Juris fails to load.
- `appellant_type` and `filing_date` are never inferred (see `PROTOCOL.md`).
- Scenarios re-score Juris after editing what it reads (appeal type, cited sections). They show how the *model* responds, not that changing a fact would change the real outcome.

## Known limitations

1. Reads wording, not legal merit; an estimate, not a prediction of what a court will do.
2. Trained on High Court appeals; not validated for the Supreme Court or for trial-court matters.
3. Appellant type is entered by the user; a private complainant appealing an acquittal is not distinguished from the State.
4. Outcome labels come from court records and may contain residual noise.
5. About one training appeal in nine concerns bail or a sentence suspension inside the appeal (for example under section 14A of the SC/ST Act). These succeed more often (about 75% against 57% for the rest) and Juris reads them like any other appeal.
6. Success rates differ widely between benches in the source records (one bench's records show about 95%). Juris does not take the court as an input, but wording correlates with it; per-bench results are in the model card document.
7. Appeals by the State or a complainant (2,377 test cases, 9 % succeeded): the joint model could not rank them (AUC 0.50), so Juris scores them with a separate model trained only on such appeals (11,497 cases). On the test period that model reaches AUC 0.73 within State appeals (Brier 0.080 against 0.089). It was chosen on validation data and then evaluated once on the test split, a disclosed second look; its estimates are still less certain than those for the accused's own appeal.
8. The share of appeals that succeed drifts upward with decision year in the source records (55 % in training, 66 % in the test period); the temporal split and the test-period baseline account for that, and calibration was slightly under-confident in the test period (expected calibration error 5.0 %).
9. In the training data the appellant was read from the case title's party order; at serving it is whatever the user states.
10. Not legal advice. Not validated for any use that affects a person's liberty or rights.

## Changing it

Retrain with `scripts/juris/` (see its README): `run_experiment dev`, then `run_experiment final` (one look at the test split),
then `export_artifact`, then this renderer. Re-run the scenario tests and re-record the demo (`DEMO.md`).
