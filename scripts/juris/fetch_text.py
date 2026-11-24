"""
Step 2: download the final-order PDF for selected cases, extract text with pdftotext, keep only the text.

PDFs are never kept: bytes go to a temp file, pdftotext runs, the file is deleted. Output is zstd-parquet shards in
data/juris/text/ (columns: cnr, n_words, text, status). Re-running skips cases already present.

    .venv-juris/bin/python -m scripts.juris.fetch_text --per-bench-cap 300 --tag pilot     # stratified pilot
    .venv-juris/bin/python -m scripts.juris.fetch_text --all --tag full                     # every labelled case
"""

import argparse
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional

import httpx
import pandas as pd

from scripts.juris import paths

BASE_URL = f"https://{paths.HC_BUCKET}.s3.{paths.REGION}.amazonaws.com/"
SHARD_SIZE = 2000
_WS_RE = re.compile(r"[ \t ]+")
_NL_RE = re.compile(r"\n{3,}")


def clean_text(raw: str) -> str:
    text = raw.replace("\r", "\n").replace("\x0c", "\n\n")
    text = _WS_RE.sub(" ", text)
    text = re.sub(r" *\n *", "\n", text)
    return _NL_RE.sub("\n\n", text).strip()


def fetch_one(client: httpx.Client, cnr: str, key: str, tmpdir: Path) -> Dict[str, object]:
    for attempt in range(3):
        try:
            r = client.get(BASE_URL + key)
            if r.status_code == 200:
                break
            if r.status_code in (403, 404):
                return {"cnr": cnr, "status": f"http_{r.status_code}", "n_words": 0, "text": ""}
        except httpx.HTTPError:
            pass
        time.sleep(1.5 * (attempt + 1))
    else:
        return {"cnr": cnr, "status": "http_error", "n_words": 0, "text": ""}
    if not r.content.startswith(b"%PDF"):
        return {"cnr": cnr, "status": "not_pdf", "n_words": 0, "text": ""}
    pdf = tmpdir / f"{cnr}.pdf"
    try:
        pdf.write_bytes(r.content)
        proc = subprocess.run(["pdftotext", "-enc", "UTF-8", str(pdf), "-"], capture_output=True, timeout=90)
        text = clean_text(proc.stdout.decode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        return {"cnr": cnr, "status": "extract_error", "n_words": 0, "text": ""}
    finally:
        pdf.unlink(missing_ok=True)
    n = len(text.split())
    return {"cnr": cnr, "status": "ok" if n >= 30 else "empty", "n_words": n, "text": text}


def already_done() -> set:
    done = set()
    for f in paths.TEXT_DIR.glob("*.parquet"):
        done.update(pd.read_parquet(f, columns=["cnr"])["cnr"].tolist())
    return done


def select(args: argparse.Namespace) -> pd.DataFrame:
    D = pd.read_parquet(paths.CANDIDATES)
    D = D[D["decision_year"] >= args.min_year]
    D = D[D["label"].isin(args.labels)]
    if args.per_bench_cap:
        D = D.groupby("bench", group_keys=False).apply(lambda g: g.sample(min(len(g), args.per_bench_cap), random_state=args.seed))
    elif args.limit:
        D = D.sample(min(len(D), args.limit), random_state=args.seed)
    else:
        D = D.sample(frac=1.0, random_state=args.seed)   # shuffled, so any partial run is a representative sample
    return D


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--labels", nargs="+", default=["succeeds", "dismissed"])
    ap.add_argument("--min-year", type=int, default=2008)
    ap.add_argument("--per-bench-cap", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()
    if not (args.all or args.per_bench_cap or args.limit):
        ap.error("choose --all, --per-bench-cap or --limit")
    paths.ensure_dirs()
    sel = select(args)
    done = already_done()
    todo = sel[~sel["cnr"].isin(done)]
    print(f"selected {len(sel)}, already fetched {len(sel) - len(todo)}, to fetch {len(todo)}", flush=True)
    rows = list(zip(todo["cnr"], todo["pdf_key"]))
    shard_no = len(list(paths.TEXT_DIR.glob("*.parquet")))
    t0 = time.time()
    with tempfile.TemporaryDirectory(dir=paths.DATA) as td, httpx.Client(timeout=60, limits=httpx.Limits(max_connections=args.workers)) as client:
        tmp = Path(td)
        for start in range(0, len(rows), SHARD_SIZE):
            chunk = rows[start:start + SHARD_SIZE]
            out: List[Dict[str, object]] = []
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futs = [pool.submit(fetch_one, client, c, k, tmp) for c, k in chunk]
                for fut in as_completed(futs):
                    out.append(fut.result())
            shard = pd.DataFrame(out)
            shard["tag"] = args.tag
            shard.to_parquet(paths.TEXT_DIR / f"shard-{shard_no:05d}.parquet", compression="zstd")
            shard_no += 1
            ok = (shard["status"] == "ok").mean()
            rate = (start + len(chunk)) / max(time.time() - t0, 1e-9)
            print(f"  {start + len(chunk)}/{len(rows)}  ok={ok:.1%}  {rate:.1f} docs/s", flush=True)


if __name__ == "__main__":
    sys.exit(main())
