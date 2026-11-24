"""
Audit of the metadata labels against the order text, per bench. Reports how often the two agree, how often the ending is
procedural, and how often the PDF is unreadable - and writes the per-case verdicts that build_corpus.py uses.

    .venv-juris/bin/python -m scripts.juris.audit_labels
"""

import glob
import json
import sys

import pandas as pd

from scripts.juris import paths
from scripts.juris.quality import is_readable, procedural_tail, tail_label


def run() -> pd.DataFrame:
    T = pd.concat([pd.read_parquet(f, columns=["cnr", "status", "n_words", "text"]) for f in sorted(glob.glob(str(paths.TEXT_DIR / "*.parquet")))])
    T = T[T["status"] == "ok"].drop_duplicates("cnr")
    rows = []
    for cnr, text in zip(T["cnr"], T["text"]):
        r = {"cnr": cnr, "readable": is_readable(text), "procedural": procedural_tail(text)}
        r.update(tail_label(text))
        rows.append(r)
    A = pd.DataFrame(rows)
    out = paths.REPORT_DIR / "label_audit_cases.parquet"
    A.to_parquet(out)
    return A


def main() -> None:
    paths.ensure_dirs()
    A = run()
    C = pd.read_parquet(paths.CANDIDATES)[["cnr", "bench", "label", "decision_year"]]
    D = A.merge(C, on="cnr")
    dec = D[D["label"].isin(["succeeds", "dismissed"]) & D["readable"]]
    both = dec[dec["text_label"].notna() & ~dec["procedural"]]
    summary = {
        "docs": len(D), "unreadable_share": round(1 - D["readable"].mean(), 4),
        "meta_decisive_readable": len(dec),
        "procedural_share_of_meta_dismissed": round(dec.loc[dec.label == "dismissed", "procedural"].mean(), 4),
        "procedural_share_of_meta_succeeds": round(dec.loc[dec.label == "succeeds", "procedural"].mean(), 4),
        "text_decisive_share": round(both.shape[0] / max(len(dec), 1), 4),
        "agreement_where_both_decisive": round((both["label"] == both["text_label"]).mean(), 4),
    }
    print(json.dumps(summary, indent=2))
    g = D.assign(readable_b=D["readable"]).groupby("bench").apply(lambda x: pd.Series({
        "n": len(x), "unreadable": round(1 - x["readable"].mean(), 2), "procedural": round(x["procedural"].mean(), 2),
        "agree": round((x.loc[x.text_label.notna() & ~x.procedural & x.label.isin(["succeeds","dismissed"]), "label"]
                        == x.loc[x.text_label.notna() & ~x.procedural & x.label.isin(["succeeds","dismissed"]), "text_label"]).mean(), 2),
        "n_cmp": int((x.text_label.notna() & ~x.procedural & x.label.isin(["succeeds","dismissed"])).sum()),
    })).sort_values("n", ascending=False)
    pd.set_option("display.width", 200)
    print(g.to_string())
    (paths.REPORT_DIR / "label_audit_summary.json").write_text(json.dumps(summary, indent=2))
    g.to_csv(paths.REPORT_DIR / "label_audit_by_bench.csv")


if __name__ == "__main__":
    sys.exit(main())
