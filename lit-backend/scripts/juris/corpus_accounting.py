"""
Exact gate accounting on a random sample of the fetched documents (the shards are in random order, so a sample of them is a random
sample of the corpus): how many documents each gate removes, and how often the court record and the order text agree.

    .venv-juris/bin/python -m scripts.juris.corpus_accounting --sample 20000
"""

import argparse
import glob
import json
import sys
from concurrent.futures import ProcessPoolExecutor

import pandas as pd

from scripts.juris import paths
from scripts.juris.build_corpus import process_doc
from scripts.juris.quality import interlocutory_tail
from scripts.outcome_dataset.labeling import extract_outcome_label


def tally(row: dict) -> dict:
    """process_doc, plus the metadata-vs-text agreement among documents where both are decisive."""
    out = process_doc(row)
    res = extract_outcome_label(row["text"])
    text_label = {"allowed": "succeeds", "partly_allowed": "succeeds", "dismissed": "dismissed"}.get(res["label"])
    out["both_decisive"] = bool(row["label"] in ("succeeds", "dismissed") and text_label)
    out["agree"] = bool(out["both_decisive"] and row["label"] == text_label)
    out["words"] = len(row["text"].split())
    return {k: out.get(k) for k in ("drop", "label_source", "both_decisive", "agree", "words", "interlocutory", "n0")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=20000)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    cand = pd.read_parquet(paths.CANDIDATES)[["cnr", "label", "party1", "party2", "judge"]]
    shards = sorted(glob.glob(str(paths.TEXT_DIR / "*.parquet")))
    T = pd.concat([pd.read_parquet(f, columns=["cnr", "status", "text"]) for f in shards[:30]])
    T = T[T["status"] == "ok"].sample(min(args.sample, len(T)), random_state=3).merge(cand, on="cnr")
    rows = T[["cnr", "text", "label", "party1", "party2", "judge"]].to_dict("records")
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        res = pd.DataFrame(list(pool.map(tally, rows, chunksize=64)))
    n = len(res)
    drops = res["drop"].fillna("kept").value_counts()
    bd = res["both_decisive"].sum()
    out = {
        "sample_documents": n,
        "share_by_outcome": {k: round(float(v) / n, 4) for k, v in drops.items()},
        "agreement_where_metadata_and_text_both_decisive": round(float(res["agree"].sum()) / max(int(bd), 1), 4),
        "n_both_decisive": int(bd),
        "kept_label_source": res.loc[res["drop"].isna(), "label_source"].value_counts().to_dict(),
        "kept_interlocutory_tail_share": round(float(res.loc[res["drop"].isna(), "interlocutory"].astype(bool).mean()), 4),
        "kept_under_800_words_share": round(float((res.loc[res["drop"].isna(), "n0"] < 800).mean()), 4),
    }
    (paths.REPORT_DIR / "gate_breakdown_sample.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    sys.exit(main())
