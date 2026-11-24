# Juris training pipeline

Juris is the project's own appeal-outcome model. It replaced a 187-judgment prototype (`scripts/outcome_dataset/`, kept as
history). This package builds the large corpus from the public Indian High Court archive, trains and evaluates Juris with a
leakage-controlled protocol, and exports the shipped artifact.

Data: Dattam Labs' *Indian High Court Judgments* (AWS Open Data, `s3://indian-high-court-judgments`, CC-BY-4.0, no credentials).
Credit the dataset in anything you publish. Everything under `data/juris/` except `model/` is git-ignored.

## Run order

```bash
uv venv --python 3.11 .venv-juris && uv pip install --python .venv-juris/bin/python -r scripts/juris/requirements-train.txt
PY=.venv-juris/bin/python

$PY -m scripts.juris.index_hc --min-year 2008                    # 1. metadata only (no PDFs): every criminal-appeal case + its label
$PY -m scripts.juris.fetch_text --all --tag full --labels succeeds dismissed neutral   # 2. final-order PDFs -> text (PDFs are never kept)
$PY -m scripts.juris.build_corpus                                # 3. quality gates, label cross-check, masking, tiers, near-duplicates
$PY -m scripts.juris.names --sample 20000                        # 4. proper-noun stop list (label-free)
$PY -m scripts.juris.quick_cv                                    #    optional: grouped CV on whatever is built (no test split)
$PY -m scripts.juris.run_experiment dev                          # 5. train <= 2021, select on 2022. Never reads the test split
$PY -m scripts.juris.run_experiment final                        # 6. the ONE look at 2023+ (guarded; refuses a second look)
$PY -m scripts.juris.export_artifact                             # 7. refit on everything, write juris.joblib + model_card.json
$PY -m scripts.juris.paper_tables                                # 8. LaTeX/CSV tables for the paper and the black book
$PY -m scripts.juris.render_model_card_md                        # 9. docs/MODEL_CARD.md from the card and the reports
$PY -m scripts.juris.publish_artifact publish                     # 10. upload juris.joblib to the private dataset repo (the Space downloads it; binaries are not committed)
$PY -m scripts.juris.routes attach                               # (after export) add the State-appeal route, then re-run publish_artifact
```

Helpers: `corpus_accounting` (exact per-gate drop rates and label agreement on a random sample of the fetched documents),
`extend_c_grid` (extends the regularisation grid downward when the best value sits on its boundary; validation year only),
`quick_cv` (grouped CV across tiers on whatever is built; never reads the test split).

Not done: a transformer arm (InLegalBERT embeddings or fine-tuning). It would need a GPU; the linear model's learning curve has flattened
near 77 % on the validation year, so it is the natural next experiment. Because the test split has been read once, a new arm evaluated on it
must be reported as a second look.

## What is guarded, and how

| Risk | Control |
|---|---|
| The judgment contains the answer | Three tiers (`services/juris_text.py`, shared with serving): **T0** full text (upper bound), **T1** operative order stripped (ILDC protocol), **T2** pre-reasoning only. Juris ships on T2. The leakage lexicon rate in T2 is measured and reported. |
| Wrong labels | Label = court `disposal_nature`, cross-checked against the order text (`quality.py`). Procedural endings (abated, withdrawn, not pressed, delay not condoned), interim bail/suspension orders, unreadable PDFs and metadata-vs-text contradictions are dropped and counted in `reports/corpus_funnel.json`. |
| Look-alike case types | `titles.py` accepts only confident criminal-appeal types; e.g. Rajasthan `CRLAS` (suspension of sentence) and `CRLLA` (leave to appeal) are rejected. |
| Companion appeals straddling splits | Near-duplicate removal (`build_corpus.dedup`, bottom-k Jaccard, bucketed by bench and date); clusters with conflicting labels are dropped. |
| Identity proxies | Party and judge names are masked, and a label-free proper-noun stop list removes names and places from the vocabulary (`names.py`). The cost is measured (ablation in `final.json`). |
| Temporal drift | Train <= 2021, validate 2022, test >= 2023. The test split is read once: `reports/test_touched.json`. |
| Test-set tuning | `dev` picks C and the model family on 2022 only; a gradient-boosting challenger replaces the linear model only if it wins by >= 3 points with a paired-bootstrap lower bound above 0. |
| Overstated probabilities | Platt calibration on the validation year; Brier and ECE are reported with a reliability table. |

## Known limits (state them in anything you publish)

- The appellant is read from the title's party order. A private complainant appealing an acquittal looks like an accused when
  the respondent is the State.
- Section numbers collide across Acts (IPC 302, NDPS 20, NI Act 138); the model sees numbers, not Acts.
- High Court only. Supreme Court judgments are not in the training data.
- Success rates drift upward with decision year in the source metadata; that is why the split is temporal and why the baseline is
  the majority outcome of the *test* period.
