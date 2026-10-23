"""
Test environment: no torch, no network, no LLM. Embeddings are a hashed bag-of-words (EMBEDDING_BACKEND=fake) and
the precedent library is a tiny synthetic artifact built here, so the whole agent flow runs in about a second.

The environment must be set BEFORE the app is imported (settings and the embedder singleton are created at import).
"""

import hashlib
import json
import os
import tempfile
from pathlib import Path

import numpy as np

_ARTIFACT_DIR = Path(tempfile.mkdtemp(prefix="lit-test-artifact-"))
os.environ.update(
    EMBEDDING_BACKEND="fake", LLM_PROVIDER="none", ENV="development", PRECEDENT_ARTIFACT_DIR=str(_ARTIFACT_DIR),
    PRECEDENT_ARTIFACT_REPO="", HUGGINGFACE_API_KEY="", AGENT_ORPHAN_CANCEL_S="1", AGENT_RUN_TIMEOUT_S="30",
)

# Synthetic "judgments": (doc_id, title, court, date, text). One undated and one later than the test filing date,
# so the temporal-validity rule is exercised.
JUDGMENTS = [
    ("j1", "Ravi vs State of Rajasthan on 5 March, 2015", "Rajasthan High Court", "2015-03-05",
     "Section 302 IPC murder conviction appeal eleven hour delay in lodging FIR unexplained interested eyewitness testimony recovery of weapon Section 27 Evidence Act"),
    ("j2", "Mohan vs State of Gujarat on 9 July, 2018", "Gujarat High Court", "2018-07-09",
     "Appeal against conviction Section 302 IPC sole eyewitness interested witness corroboration required delay in FIR benefit of doubt acquittal"),
    ("j3", "State of Punjab vs Gurmeet on 12 May, 2009", "Supreme Court of India", "2009-05-12",
     "State appeal against acquittal Section 378 CrPC interference with acquittal only if view perverse eyewitness testimony medical evidence"),
    ("j4", "Anita vs State of Kerala on 2 Feb, 2023", "Kerala High Court", "2023-02-02",
     "Section 138 Negotiable Instruments Act cheque dishonour statutory notice presumption legally enforceable debt"),
    ("j5", "Undated Matter vs State", "Delhi High Court", None,
     "Section 302 IPC murder eleven hour delay FIR eyewitness weapon recovery"),
    ("j6", "Suresh vs State of Bihar on 1 Jan, 2024", "Patna High Court", "2024-01-01",
     "Section 302 IPC murder eleven hour delay FIR interested eyewitness weapon recovery panch witness"),
]


def _build_artifact() -> None:
    from services.embedder import fake_embedding

    vectors = np.array([fake_embedding(j[4]) for j in JUDGMENTS], dtype=np.float32)
    np.save(_ARTIFACT_DIR / "vectors.npy", vectors)
    with open(_ARTIFACT_DIR / "meta.jsonl", "w", encoding="utf-8") as f:
        for doc_id, title, court, date, text in JUDGMENTS:
            f.write(json.dumps({"doc_id": doc_id, "title": title, "url": f"https://example.test/doc/{doc_id}", "court": court,
                                "date": date, "text": text, "chunk_index": 0, "total_chunks": 1}) + "\n")

    def digest(name: str) -> dict:
        p = _ARTIFACT_DIR / name
        return {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size}

    manifest = {"artifact_version": "test", "counts": {"chunks": len(JUDGMENTS), "docs": len(JUDGMENTS), "dated_docs": 5, "undated_chunks": 1},
                "files": {"vectors.npy": digest("vectors.npy"), "meta.jsonl": digest("meta.jsonl")}}
    (_ARTIFACT_DIR / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


_build_artifact()
