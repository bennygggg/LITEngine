"""
Step 3: turn fetched order text into the training corpus.

Per case: readability gate, procedural-ending gate, metadata-vs-text label cross-check, name masking, leakage tiers T0/T1/T2.
Then a near-duplicate pass (companion appeals decided by one shared judgment must not straddle train and test).

    .venv-juris/bin/python -m scripts.juris.build_corpus            # all fetched text
Outputs: data/juris/corpus/part-*.parquet, keep.parquet, funnel.json
"""

import glob
import hashlib
import json
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from scripts.juris import paths
from scripts.juris.corpus import CORPUS_DIR, KEEP
from scripts.juris.quality import interlocutory_tail, is_readable, procedural_tail, tail_label
from scripts.juris.segment import leak_hits, tier1, tier2
from scripts.outcome_dataset.labeling import extract_outcome_label

MIN_WORDS = 150           # shorter documents are orders, not judgments
SKETCH_K = 64
SKETCH_WORDS = 1200
_NAME_STOP = frozenset("""state union india of the and another others anr ors ors. through its secretary home department govt government
police station honble hon'ble mr mrs ms shri smt dr justice judge chief sri kumari smt. versus vs by thr represented rep under section
district court high public prosecutor commissioner inspector superintendent director general advocate petitioner respondent appellant
accused complainant""".split())
_TOKEN = re.compile(r"[A-Za-z][A-Za-z'\-]{3,}")


def _name_regex(*names: Optional[str]) -> Optional[re.Pattern]:
    toks = set()
    for n in names:
        for t in _TOKEN.findall(n if isinstance(n, str) else ""):
            if t.lower() not in _NAME_STOP:
                toks.add(re.escape(t))
    if not toks:
        return None
    return re.compile(r"\b(?:" + "|".join(sorted(toks, key=len, reverse=True)) + r")\b", re.IGNORECASE)


def _mask(text: str, rx: Optional[re.Pattern]) -> str:
    return rx.sub("[NAME]", text) if rx else text


def _sketch(text: str) -> List[int]:
    words = re.findall(r"\w+", text.lower())[:SKETCH_WORDS]
    if len(words) < 8:
        return []
    hs = {(int.from_bytes(hashlib.blake2b(" ".join(words[i:i + 8]).encode(), digest_size=8).digest(), "little") & 0x7FFFFFFFFFFFFFFF) for i in range(len(words) - 7)}
    return sorted(hs)[:SKETCH_K]


def process_doc(row: Dict[str, Any]) -> Dict[str, Any]:
    text: str = row["text"]
    out: Dict[str, Any] = {"cnr": row["cnr"], "drop": None}
    n0 = len(text.split())
    if n0 < MIN_WORDS:
        out["drop"] = "too_short"; return out
    if not is_readable(text):
        out["drop"] = "unreadable"; return out
    if procedural_tail(text):
        out["drop"] = "procedural_ending"; return out
    res = extract_outcome_label(text)
    text_label = {"allowed": "succeeds", "partly_allowed": "succeeds", "dismissed": "dismissed"}.get(res["label"])
    meta = row["label"]
    if meta in ("succeeds", "dismissed"):
        if text_label and text_label != meta:
            out["drop"] = "label_contradiction"; return out
        label, source = meta, ("meta+text" if text_label == meta else "meta")
    else:  # neutral "disposed of": take the text's verdict only when it is clear
        if text_label and res["confidence"] >= 0.75:
            label, source = text_label, "text"
        else:
            out["drop"] = "neutral_unresolved"; return out
    rx = _name_regex(row.get("party1"), row.get("party2"), row.get("judge"))
    t1, m1 = tier1(text, res["match_start"])
    t2, m2 = tier2(text)
    t0m, t1m, t2m = _mask(text, rx), _mask(t1, rx), _mask(t2, rx)
    out.update({
        "label": label, "label_source": source, "t0": t0m, "t1": t1m, "t2": t2m,
        "n0": n0, "n1": len(t1m.split()), "n2": len(t2m.split()), "t1_reason": m1["t1_reason"], "t2_reason": m2["t2_reason"],
        "t2_leak": leak_hits(t2), "t2_label_leak": int(extract_outcome_label(t2)["label"] != "unclear"),
        "t1_leak": leak_hits(t1), "interlocutory": interlocutory_tail(text), "sketch": _sketch(text),
    })
    return out


def _bk_jaccard(a: List[int], b: List[int]) -> float:
    if len(a) == 0 or len(b) == 0:
        return 0.0
    sa, sb = set(a), set(b)
    union_k = sorted(sa | sb)[:SKETCH_K]
    return sum(1 for x in union_k if x in sa and x in sb) / len(union_k)


def dedup(meta: pd.DataFrame, threshold: float = 0.85) -> pd.DataFrame:
    """Union-find over (bench, decision_date) buckets using bottom-k Jaccard; conflicting labels in a cluster are dropped."""
    meta = meta.reset_index(drop=True)
    parent = list(range(len(meta)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for _, g in meta.groupby(["bench", "decision_date"]):
        idx = list(g.index)
        if len(idx) < 2:
            continue
        for i, a in enumerate(idx):
            for b in idx[i + 1:]:
                if _bk_jaccard(meta.at[a, "sketch"], meta.at[b, "sketch"]) >= threshold:
                    parent[find(a)] = find(b)
    meta["dup_group"] = [find(i) for i in range(len(meta))]
    keep = np.ones(len(meta), dtype=bool)
    reason = np.array([""] * len(meta), dtype=object)
    for _, g in meta.groupby("dup_group"):
        if len(g) == 1:
            continue
        ordered = list(g.sort_values("cnr").index)
        if g["label"].nunique() > 1:
            for i in ordered:
                keep[i] = False; reason[i] = "dup_label_conflict"
        else:
            for i in ordered[1:]:
                keep[i] = False; reason[i] = "near_duplicate"
    meta["keep"], meta["dedup_reason"] = keep, reason
    return meta


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true", help="re-process every shard (default: only shards without a part file)")
    ap.add_argument("--workers", type=int, default=7)
    args = ap.parse_args()
    paths.ensure_dirs()
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    if args.rebuild:
        for f in CORPUS_DIR.glob("*.parquet"):
            f.unlink()
    cand = pd.read_parquet(paths.CANDIDATES)[["cnr", "bench", "part_court", "court", "decision_year", "decision_date", "side", "ctype", "label",
                                              "label_rule", "party1", "party2", "judge", "title"]]
    drops: Dict[str, int] = {}
    seen: set = set()
    shards = sorted(glob.glob(str(paths.TEXT_DIR / "*.parquet")))
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for f in shards:
            name = Path(f).stem.replace("shard-", "part-")
            out_f = CORPUS_DIR / f"{name}.parquet"
            T = pd.read_parquet(f)
            T = T[(T["status"] == "ok") & ~T["cnr"].isin(seen)]
            seen.update(T["cnr"])
            if out_f.exists():
                continue
            D = T.merge(cand, on="cnr", how="inner", suffixes=("", "_c"))
            rows = D[["cnr", "text", "label", "party1", "party2", "judge"]].to_dict("records")
            ok = []
            for r in pool.map(process_doc, rows, chunksize=64):
                if r["drop"]:
                    drops[r["drop"]] = drops.get(r["drop"], 0) + 1
                else:
                    ok.append(r)
            R = pd.DataFrame(ok) if ok else pd.DataFrame(columns=["cnr"])
            if ok:
                R = R.merge(cand.drop(columns=["label", "party1", "party2", "judge", "title"]), on="cnr").drop(columns=["drop"])
            R.to_parquet(out_f, compression="zstd")
            print(f"  {name}: {len(R)} kept of {len(rows)}", flush=True)
    # dedup + funnel over ALL parts (light columns only)
    frames = [pd.read_parquet(f, columns=["cnr", "bench", "decision_date", "label", "sketch"]) for f in sorted(CORPUS_DIR.glob("part-*.parquet"))]
    meta = dedup(pd.concat([f for f in frames if len(f)], ignore_index=True))
    meta[["cnr", "keep", "dedup_reason", "dup_group"]].to_parquet(KEEP)
    funnel: Dict[str, Any] = {
        "candidates_with_label_or_neutral": int(cand["label"].notna().sum()), "text_docs_seen": len(seen),
        "dropped_by_reason_this_run": drops, "after_quality_and_label_filters": len(meta),
        "near_duplicate_removed": int((meta["dedup_reason"] == "near_duplicate").sum()),
        "duplicate_label_conflict_removed": int((meta["dedup_reason"] == "dup_label_conflict").sum()),
        "final_cases": int(meta["keep"].sum()), "final_label_counts": meta.loc[meta["keep"], "label"].value_counts().to_dict(),
    }
    (paths.REPORT_DIR / "corpus_funnel.json").write_text(json.dumps(funnel, indent=2))
    print(json.dumps(funnel, indent=2))


if __name__ == "__main__":
    sys.exit(main())
