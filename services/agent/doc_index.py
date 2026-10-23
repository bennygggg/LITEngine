"""
Per-case retrieval for "ask the case": chunks with character offsets, embedded once per case.

Chunks are ~180 words so they fit MiniLM's 256-token window (the legacy 500-word chunks were silently truncated to
the first third). This index is internal to one uploaded document; it is NOT the precedent library, so changing its
chunking cannot affect the outcome model's inputs.
"""

import re
from dataclasses import dataclass
from typing import Dict, List

import numpy as np

from services.embedder import embedder_service

CHUNK_WORDS = 180
CHUNK_OVERLAP = 30
SNAP_WINDOW = 35  # look this many words back from the cut for a sentence boundary
_STOP = frozenset(
    "the a an of to in on at by for and or but is are was were be been being this that these those with from as it its "
    "he she they them his her their what which who whom whose when where why how did does do not no any all there "
    "about into than then also case court".split()
)
_WORD = re.compile(r"[a-z0-9]+")


@dataclass
class DocChunk:
    index: int
    text: str
    char_start: int
    char_end: int


@dataclass
class DocIndex:
    chunks: List[DocChunk]
    matrix: np.ndarray  # (n, dim) float32, L2-normalised


def _ends_sentence(token: str) -> bool:
    t = token.rstrip('"\')]')
    if not t or t[-1] not in ".?!":
        return False
    # "No.", "Mr.", "v.", "S." and similar abbreviations are not sentence ends
    return not (t[-1] == "." and len(t.rstrip(".")) <= 3)


def chunk_with_offsets(text: str, words: int = CHUNK_WORDS, overlap: int = CHUNK_OVERLAP) -> List[DocChunk]:
    spans = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
    n = len(spans)
    chunks: List[DocChunk] = []
    i = 0
    while i < n:
        j = min(i + words, n)
        if j < n:
            for k in range(j, max(i + words - SNAP_WINDOW, i + 1), -1):
                if _ends_sentence(text[spans[k - 1][0] : spans[k - 1][1]]):
                    j = k
                    break
        start, end = spans[i][0], spans[j - 1][1]
        chunks.append(DocChunk(index=len(chunks), text=text[start:end], char_start=start, char_end=end))
        if j >= n:
            break
        i = max(j - overlap, i + 1)
    return chunks


async def build_index(text: str) -> DocIndex:
    chunks = chunk_with_offsets(text)
    if not chunks:
        return DocIndex(chunks=[], matrix=np.zeros((0, embedder_service.dimension), dtype=np.float32))
    vectors = np.array(await embedder_service.embed_texts([c.text for c in chunks]), dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return DocIndex(chunks=chunks, matrix=vectors / norms)


def _terms(text: str) -> set:
    return {w for w in _WORD.findall(text.lower()) if len(w) > 3 and w not in _STOP}


async def retrieve(index: DocIndex, question: str, top_k: int = 5) -> List[Dict]:
    """Top-k chunks by cosine, re-ranked a little by exact term overlap (names, section numbers, dates)."""
    if not index.chunks:
        return []
    q = np.array(await embedder_service.embed_query(question), dtype=np.float32)
    norm = np.linalg.norm(q)
    q = q / norm if norm else q
    cosines = index.matrix @ q
    shortlist = np.argsort(-cosines)[: max(top_k * 3, 12)]
    q_terms = _terms(question)
    scored = []
    for i in shortlist:
        overlap = (len(q_terms & _terms(index.chunks[int(i)].text)) / len(q_terms)) if q_terms else 0.0
        scored.append((float(cosines[i]) + 0.15 * overlap, int(i)))
    scored.sort(reverse=True)
    out = []
    for rank, (_, i) in enumerate(scored[:top_k], start=1):
        c = index.chunks[i]
        out.append({
            "ref": f"S{rank}", "text": c.text, "cosine": round(float(cosines[i]), 4),
            "chunk_index": c.index, "char_start": c.char_start, "char_end": c.char_end,
        })
    return out
