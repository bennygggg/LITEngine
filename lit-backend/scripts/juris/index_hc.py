"""
Step 1 of the Juris corpus: find every High Court criminal appeal with a usable outcome label, from the bucket's METADATA
only (no PDFs). Columns are projected, so the large `raw_html` column is never read.

    .venv-juris/bin/python -m scripts.juris.index_hc --min-year 2008            # all partitions (resumable)
    .venv-juris/bin/python -m scripts.juris.index_hc --years 2023 --force       # redo one year

Output: data/juris/index/hc_criminal_appeals.parquet - one row per CNR (the latest order decides the outcome).
"""

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import pyarrow.fs as pafs
import pyarrow.parquet as pq

from scripts.juris import paths
from scripts.juris.labels import map_disposal
from scripts.juris.titles import _APPEAL_TYPE_RE, _BOMBAY_TYPE_RE, appellant_side, is_criminal_appeal, parse_title

COLUMNS = ["court_code", "title", "cnr", "decision_date", "disposal_nature", "judge", "pdf_link", "court"]
_PREFIX_RE = r"^\s*(?:R/)?([^/]{1,40}?)\s*/\s*\d+\s*/\s*\d{4}\s+of\s"
_FAST_RE = f"(?:{_APPEAL_TYPE_RE.pattern.strip('^$')})|(?:{_BOMBAY_TYPE_RE.pattern.strip('^$')})"


def _s3() -> pafs.S3FileSystem:
    return pafs.S3FileSystem(anonymous=True, region=paths.REGION)


def list_partitions(refresh: bool = False) -> List[Dict[str, Any]]:
    cache = paths.INDEX_DIR / "partitions.json"
    if cache.exists() and not refresh:
        return json.loads(cache.read_text())
    sel = pafs.FileSelector(f"{paths.HC_BUCKET}/metadata/parquet", recursive=True)
    out = []
    for info in _s3().get_file_info(sel):
        if info.type != pafs.FileType.File or not info.path.endswith(".parquet"):
            continue
        kv = dict(x.split("=", 1) for x in info.path.split("/") if "=" in x)
        out.append({"year": int(kv["year"]), "court": kv["court"], "bench": kv["bench"], "path": info.path, "size": info.size})
    paths.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out))
    return out


def part_file(p: Dict[str, Any]) -> Path:
    return paths.PARTS_DIR / f"year={p['year']}" / f"court={p['court']}" / f"bench={p['bench']}.parquet"


def _read(p: Dict[str, Any]) -> pd.DataFrame:
    local = paths.LOCAL_HC_METADATA / f"year={p['year']}" / f"court={p['court']}" / f"bench={p['bench']}" / "metadata.parquet"
    if local.exists():
        table = pq.read_table(local, columns=COLUMNS)
    else:
        table = pq.read_table(p["path"], filesystem=_s3(), columns=COLUMNS)
    df = table.to_pandas()
    for c in ("court_code", "title", "cnr", "disposal_nature", "judge", "pdf_link", "court"):
        df[c] = df[c].astype("string")
    df["decision_date"] = pd.to_datetime(df["decision_date"], errors="coerce")
    return df


def filter_partition(df: pd.DataFrame, p: Dict[str, Any]) -> pd.DataFrame:
    """Vectorised pre-filter on the case-type token, then the strict per-row checks on the survivors only."""
    pre = df["title"].fillna("").str.extract(_PREFIX_RE, expand=False).fillna("")
    norm = pre.str.upper().str.replace(r"[\s.]", "", regex=True)
    cand = df[norm.str.fullmatch(_FAST_RE)].copy()
    if cand.empty:
        return cand
    parsed = pd.DataFrame([parse_title(t) for t in cand["title"]], index=cand.index)
    cand = pd.concat([cand, parsed], axis=1)
    keep = [is_criminal_appeal(c or "", a, b) for c, a, b in zip(cand.ctype, cand.party1, cand.party2)]
    cand = cand[keep].copy()
    if cand.empty:
        return cand
    cand["side"] = [appellant_side(a, b) for a, b in zip(cand.party1, cand.party2)]
    mapped = [map_disposal(x) for x in cand["disposal_nature"]]
    cand["label"] = [m[0] for m in mapped]
    cand["label_rule"] = [m[1] for m in mapped]
    cand["part_year"], cand["part_court"], cand["bench"] = p["year"], p["court"], p["bench"]
    base = cand["pdf_link"].fillna("").str.split("/").str[-1]
    cand["pdf_key"] = ("data/pdf/year=" + str(p["year"]) + "/court=" + p["court"] + "/bench=" + p["bench"] + "/" + base).where(base != "")
    return cand.drop(columns=["court_code"])


def process(p: Dict[str, Any], force: bool) -> Dict[str, Any]:
    out = part_file(p)
    if out.exists() and not force:
        return {"p": p, "skipped": True, "rows": None}
    t0 = time.time()
    try:
        df = _read(p)
        res = filter_partition(df, p)
    except Exception as exc:  # noqa: BLE001 - one bad partition must not stop a 1,500-partition run
        return {"p": p, "error": str(exc)[:160]}
    out.parent.mkdir(parents=True, exist_ok=True)
    res.to_parquet(out, compression="zstd")
    return {"p": p, "rows": len(df), "kept": len(res), "secs": round(time.time() - t0, 1)}


def combine() -> pd.DataFrame:
    files = sorted(paths.PARTS_DIR.rglob("*.parquet"))
    frames = [pd.read_parquet(f) for f in files]
    frames = [f for f in frames if len(f)]
    allrows = pd.concat(frames, ignore_index=True)
    # one row per case (CNR); the LATEST order is the final disposal
    allrows = allrows.dropna(subset=["cnr"]).sort_values("decision_date")
    final = allrows.groupby("cnr", as_index=False).tail(1).copy()
    final["decision_year"] = final["decision_date"].dt.year
    funnel = {
        "partitions_with_appeals": len(frames), "appeal_order_rows": len(allrows), "unique_cases": len(final),
        "label_counts": final["label"].fillna("none").value_counts().to_dict(),
        "label_rules_for_none": final.loc[final["label"].isna(), "label_rule"].value_counts().head(12).to_dict(),
    }
    paths.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    final.to_parquet(paths.CANDIDATES, compression="zstd")
    (paths.INDEX_DIR / "index_funnel.json").write_text(json.dumps(funnel, indent=2, default=str))
    print(json.dumps(funnel, indent=2, default=str))
    return final


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-year", type=int, default=2008)
    ap.add_argument("--years", type=int, nargs="*", help="restrict to these decision years")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--refresh-listing", action="store_true")
    ap.add_argument("--combine-only", action="store_true")
    args = ap.parse_args()
    paths.ensure_dirs()
    if not args.combine_only:
        parts = [p for p in list_partitions(args.refresh_listing) if p["year"] >= args.min_year and (not args.years or p["year"] in args.years)]
        print(f"{len(parts)} partitions to process", flush=True)
        done = 0
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = [pool.submit(process, p, args.force) for p in parts]
            for fut in as_completed(futs):
                r = fut.result(); done += 1
                if "error" in r:
                    print(f"  ERROR {r['p']['year']}/{r['p']['court']}/{r['p']['bench']}: {r['error']}", flush=True)
                elif done % 50 == 0 or done == len(parts):
                    print(f"  {done}/{len(parts)} partitions", flush=True)
    combine()


if __name__ == "__main__":
    sys.exit(main())
