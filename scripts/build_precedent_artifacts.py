"""
Convert the 188 MB JSON precedent index into a compact, hash-verified artifact.

    data/outcome_dataset/precedent_index.json   (13,591 chunk vectors as nested JSON lists)
        ->  <out>/vectors.npy     float32 (n, 384), values identical to what the old loader fed FAISS
            <out>/meta.jsonl      one JSON object per chunk (same fields as the old metadata, ints coerced)
            <out>/manifest.json   version, counts, sha256 per file, embedder/chunker identity, score transform

The vectors are NOT re-embedded: the outcome model's `precedent_alignment` input was computed from exactly these
vectors with this embedder and chunking, so changing any of them silently shifts the model's inputs (see plan §5.7).

Usage (from lit-backend/):
    python scripts/build_precedent_artifacts.py                       # build to data/precedent_artifacts/v1
    python scripts/build_precedent_artifacts.py --verify              # also prove search results match the JSON path
    python scripts/build_precedent_artifacts.py --verify-only --out data/precedent_artifacts/v1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEFAULT_SRC = ROOT / "data" / "outcome_dataset" / "precedent_index.json"
DEFAULT_OUT = ROOT / "data" / "precedent_artifacts" / "v1"
ARTIFACT_VERSION = "v1"
EMBEDDER = "sentence-transformers/all-MiniLM-L6-v2"

# The six bundled sample matters' retrieval queries double as the equivalence-check workload.
VERIFY_QUERIES = [
    "Appeal against conviction under Section 302 IPC based solely on eyewitness testimony, delayed FIR and unrecovered weapon",
    "State appeal under Section 378 CrPC against acquittal in a Section 376 IPC prosecution, delay in complaint",
    "Cheque dishonour prosecution under Section 138 Negotiable Instruments Act, statutory notice and presumption",
    "Dowry death Section 304B IPC presumption under Section 113B Evidence Act",
    "Cheating and criminal breach of trust Section 420 IPC dishonest intention at inception",
    "Cruelty by husband Section 498A IPC vague allegations and quashing",
    "Interested witness testimony and requirement of corroboration in murder trial",
    "Recovery of weapon under Section 27 Evidence Act and independent panch witness",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def build(src: Path, out: Path) -> Dict[str, Any]:
    t0 = time.time()
    print(f"loading {src} ({src.stat().st_size / 1e6:.0f} MB) ...")
    data = json.loads(src.read_text(encoding="utf-8"))
    vectors = np.array(data["vectors"], dtype=np.float32)  # same conversion the old loader used
    metadata: List[Dict[str, Any]] = data["metadata"]
    if len(vectors) != len(metadata):
        raise SystemExit(f"vector/metadata mismatch: {len(vectors)} vs {len(metadata)}")
    dim = int(data.get("dimension", vectors.shape[1]))
    if vectors.shape[1] != dim:
        raise SystemExit(f"dimension mismatch: {vectors.shape[1]} vs {dim}")

    norms = np.linalg.norm(vectors, axis=1)
    out.mkdir(parents=True, exist_ok=True)
    np.save(out / "vectors.npy", vectors)

    with open(out / "meta.jsonl", "w", encoding="utf-8") as f:
        for m in metadata:
            row = dict(m)
            row["chunk_index"] = int(row.get("chunk_index", 0))
            row["total_chunks"] = int(row.get("total_chunks", 1))
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    doc_ids = {m["doc_id"] for m in metadata}
    dated_docs = {m["doc_id"] for m in metadata if m.get("date")}
    courts = Counter(m.get("court") for m in metadata)
    manifest = {
        "artifact_version": ARTIFACT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {"file": src.name, "bytes": src.stat().st_size, "sha256": sha256_file(src)},
        "embedder": EMBEDDER,
        "dimension": dim,
        "chunker": {"unit": "words", "size": 500, "overlap": 50,
                    "note": "legacy chunking — MiniLM truncates at 256 tokens; frozen for outcome-model parity"},
        "score_transform": "similarity_score = 1/(1+d) where d is squared L2 distance on L2-normalised vectors; "
                           "cosine = 1 - d/2",
        "counts": {"chunks": len(metadata), "docs": len(doc_ids), "dated_docs": len(dated_docs),
                   "undated_chunks": sum(1 for m in metadata if not m.get("date"))},
        "vector_norm": {"min": float(norms.min()), "max": float(norms.max())},
        "top_courts": courts.most_common(8),
        "files": {name: {"sha256": sha256_file(out / name), "bytes": (out / name).stat().st_size}
                  for name in ("vectors.npy", "meta.jsonl")},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"built {out} in {time.time() - t0:.1f}s: {manifest['counts']}, "
          f"vectors {manifest['files']['vectors.npy']['bytes'] / 1e6:.1f} MB, "
          f"meta {manifest['files']['meta.jsonl']['bytes'] / 1e6:.1f} MB")
    return manifest


def verify(src: Path, out: Path, use_model: bool = True) -> bool:
    """Prove the artifact answers identically to the legacy JSON path (same FAISS flat-L2 search)."""
    # Embed the queries BEFORE importing faiss: on macOS arm64, loading faiss first and then running torch
    # inference in the same process segfaults (OpenMP runtime clash). Linux (the Space) is unaffected.
    queries: np.ndarray
    if use_model:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(EMBEDDER)
        queries = model.encode(VERIFY_QUERIES, normalize_embeddings=True).astype(np.float32)
    import faiss

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    for name, info in manifest["files"].items():
        if sha256_file(out / name) != info["sha256"]:
            print(f"FAIL hash mismatch: {name}")
            return False

    legacy = json.loads(src.read_text(encoding="utf-8"))
    old_vecs = np.array(legacy["vectors"], dtype=np.float32)
    old_meta = legacy["metadata"]
    new_vecs = np.load(out / "vectors.npy")
    new_meta = [json.loads(line) for line in (out / "meta.jsonl").read_text(encoding="utf-8").splitlines()]

    if not np.array_equal(old_vecs, new_vecs):
        print("FAIL vectors differ")
        return False
    if [m["doc_id"] for m in old_meta] != [m["doc_id"] for m in new_meta]:
        print("FAIL metadata order differs")
        return False

    if not use_model:
        rng = np.random.default_rng(7)
        queries = old_vecs[rng.choice(len(old_vecs), 8, replace=False)]

    idx_old = faiss.IndexFlatL2(old_vecs.shape[1])
    idx_old.add(old_vecs)
    idx_new = faiss.IndexFlatL2(new_vecs.shape[1])
    idx_new.add(new_vecs)
    d_old, i_old = idx_old.search(queries, 10)
    d_new, i_new = idx_new.search(queries, 10)
    ok = np.array_equal(i_old, i_new) and np.allclose(d_old, d_new, atol=1e-7)
    print(f"{'OK  ' if ok else 'FAIL'} top-10 ids/distances identical across {len(queries)} queries "
          f"({'MiniLM queries' if use_model else 'self-queries'})")

    # Show what a criminal-law query now returns (this is what the demo needs).
    top = i_new[0][:5]
    for rank, i in enumerate(top, 1):
        m = new_meta[int(i)]
        d = float(d_new[0][rank - 1])
        print(f"   {rank}. {m['title'][:70]} | {m.get('court')} | {m.get('date')} | cosine {1 - d / 2:.3f}")
    return bool(ok)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--verify", action="store_true", help="build, then verify against the JSON path")
    ap.add_argument("--verify-only", action="store_true")
    ap.add_argument("--no-model", action="store_true", help="verify with self-queries instead of loading MiniLM")
    args = ap.parse_args()

    if not args.verify_only:
        build(args.src, args.out)
    if args.verify or args.verify_only:
        sys.exit(0 if verify(args.src, args.out, use_model=not args.no_model) else 1)


if __name__ == "__main__":
    main()
