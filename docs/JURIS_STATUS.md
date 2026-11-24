# Juris: status, decisions and open items (2026-11-24)

Read this first when picking the work up in a new session. Details live in the documents it points to; nothing here is a secret.

## What exists and where

| Question | Document |
|---|---|
| What is Juris, what does it read, how good is it, what are its limits | `docs/MODEL_CARD.md` (generated; do not hand-edit) |
| Robustness, sensitivity, ablations, neural baseline, ILDC check, State-appeal model | `docs/JURIS_ROBUSTNESS.md` (generated) |
| The training corpus | `docs/JURIS_DATASHEET.md` |
| Raw results the three documents are generated from | `docs/juris-reports/*.json` (copies; the working copies in `lit-backend/data/juris/reports/` are git-ignored) |
| How to rebuild everything, and what each guard is for | `lit-backend/scripts/juris/README.md` |
| What changed and why | `CHANGELOG.md` ("Unreleased: Juris") |
| How the artifact ships and how to deploy/roll back | `docs/RUNBOOK.md` |
| The black book (rewritten around Juris; numbers come from generated macros) | `blackbook/` (untracked): sections 5.2.5 and 6.4.2, `blackbook/TODO.md`, `blackbook/README.md` |

**The black book does not contain** the robustness findings (selective prediction, rolling-origin, leave-one-bench-out, cut sensitivity, ablations, neural baseline, ILDC check): it is at the college's 80-page limit. They are in `docs/JURIS_ROBUSTNESS.md` and are meant for the paper.

## Headline results (all in `docs/MODEL_CARD.md`)

Trained on 107,847 High Court criminal-appeal judgments (2008-2026), reading only the pre-reasoning text plus the user-stated appeal type. Test (2023-26, 32,573 cases, read once): **75.3 % accuracy (95 % CI 74.8-75.8), AUC 0.795**; majority outcome 65.6 %; appeal type alone 73.7 % (AUC 0.643). Appeals by the State are scored by a second model (within-State test AUC 0.50 -> 0.73). Honest summary: respectable and defensible, not state of the art; the strength is the measurement (leakage ladder, temporal split, one look at the test split), not the headline number.

## Live state

- Branch `feat/juris` (on top of 1.0.1), three commits: `a4e7f0b` (rename + retrain), `b5f5b0e` (robustness suite), `89078a5` (State route). Not merged; there is no remote backup (GitHub is suspended). `blackbook/`, `project_report/` and `Prac4_GenAI_Meera.pdf` are untracked on purpose.
- Backend: Hugging Face Space `thebenmerlin/lit-backend` (Docker, CPU Basic), deployed by pushing the subtree split (`git subtree split --prefix=lit-backend HEAD`), live at `https://thebenmerlin-lit-backend.hf.space`; model version `juris-20261124-5d72af41`.
- Frontend: `https://lit-ngin.vercel.app` (`npx vercel --prod --yes` from the monorepo root).
- Artifact: `thebenmerlin/lit-precedent-index` (private dataset) under `juris/v2/juris.joblib` (7.8 MB; `juris/v1/` = joint model only). The committed `lit-backend/data/juris/model/model_card.json` pins its sha256; the Space downloads it at start and refuses a mismatch (falls back to the heuristic).
- Rollback: local tags `deploy/pre-state-route` (Space commit `9cce504`, previous live release, joint model + v1 artifact) and `deploy/pre-juris` (`de1c60e`, the 187-case prototype). Rolling back means force-pushing the split of that tag to the Space.
- Last verified live: ready, `juris_loaded: true`, smoke test passed, same case scored 0.447 (accused) and 0.04 (State).

## Decisions and why

- **Leakage policy:** Juris ships on the pre-reasoning text (T2); the order-stripped (ILDC-style) and full-text tiers are reported as references, not predictions.
- **The "1,505 cases" claim in the earlier black book was false** (the served model was the 187-case prototype). It is removed everywhere; keep it removed.
- **Test split:** read once by `run_experiment final` (guard file `reports/test_touched.json`). It was used twice more, both disclosed: the frozen model's per-case predictions (descriptive analyses) and the State-appeal model's confirmation. Any further model change needs its own disclosed look.
- **Binary files cannot go in the Space's git** (Hugging Face rejects them), hence the dataset-repo shipping; the serving image has no pandas.
- **Cost:** the owner wants no spend. Everything was done free; the GPU/InLegalBERT arm was dropped (the token also lacks the Jobs permission). A frozen InLegalBERT baseline was run locally and did not beat TF-IDF.
- A no-LLM demo recording was tried and rejected (follow-up and off-topic turns degrade); the demo is recorded with the LLM (`scripts/record_demo.py --verify`).

## Open items

1. Human audit: `lit-backend/data/juris/release/audit_sample_200.csv` (local, contains judgment excerpts) is generated but not filled in.
2. Supreme Court transfer (train on High Court, test on Supreme Court) was not run; the ILDC check used a public copy without official splits.
3. Neural fine-tuning (needs a GPU) was not done.
4. Merge or back up `feat/juris`; the black book and `project_report/` are untracked.
5. Black book (see `blackbook/TODO.md`): implementation-paper and plagiarism rows, copyright row, LICENSE file, timeline, dead GitHub link in Appendix E.
6. After any retrain: `export_artifact`, `routes attach`, `publish_artifact publish` (new `juris/vN` path), regenerate fixtures and the demo, `render_model_card_md`, `render_robustness_md`, `paper_tables`, refresh the black-book macros, then deploy.
