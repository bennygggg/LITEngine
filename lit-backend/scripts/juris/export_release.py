"""
Release package (local, git-ignored): IDs + labels + splits (NO court text, so nothing here redistributes the source PDFs) and a 200-case
audit sheet for a human reviewer. The datasheet is docs/JURIS_DATASHEET.md.

    .venv-juris/bin/python -m scripts.juris.export_release
"""

import sys

import numpy as np
import pandas as pd

from scripts.juris import paths
from scripts.juris.run_experiment import load_tier, splits

OUT = paths.DATA / "release"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    D = load_tier("t0", 100)
    D["t2"] = load_tier("t2", 100).set_index("cnr").loc[D["cnr"], "t2"].values
    cand = pd.read_parquet(paths.CANDIDATES)[["cnr", "court", "title", "ctype", "pdf_key"]].drop_duplicates("cnr")
    sp = splits(D)
    split = np.array(["train"] * len(D), dtype=object)
    split[sp["val"]] = "validation"
    split[sp["test"]] = "test"
    cols = D[["cnr", "bench", "decision_year", "side", "label", "n0", "n2"]].copy()
    cols["split"] = split
    rel = cols.merge(cand[["cnr", "court", "ctype", "pdf_key"]], on="cnr", how="left")
    rel.to_csv(OUT / "juris_cases.csv.gz", index=False, compression="gzip")
    print(f"wrote {OUT / 'juris_cases.csv.gz'}: {len(rel):,} cases, splits {rel['split'].value_counts().to_dict()}")
    rng = np.random.default_rng(2026)
    pick = rng.choice(len(D), 200, replace=False)
    sheet = pd.DataFrame({
        "cnr": D["cnr"].values[pick], "bench": D["bench"].values[pick], "year": D["decision_year"].values[pick], "label_in_corpus": D["label"].values[pick],
        "t2_last_700_chars": [t[-700:] for t in D["t2"].values[pick]] if "t2" in D else "", "operative_end_of_judgment_last_700_chars": [t[-700:] for t in D["t0"].values[pick]],
        "REVIEW_t2_contains_a_verdict_or_the_courts_conclusion (y/n)": "", "REVIEW_corpus_label_matches_the_judgment (y/n)": "", "REVIEW_notes": "",
    })
    sheet.to_csv(OUT / "audit_sample_200.csv", index=False)
    print(f"wrote {OUT / 'audit_sample_200.csv'} (fill the REVIEW_ columns; local only: it contains judgment excerpts)")


if __name__ == "__main__":
    sys.exit(main())
