"""
Precedent library search for the agent — the same FAISS index and temporal-validity rule the REST route uses
(`decision_before`: unknown or later dates can never support a precedent), plus a true cosine, court tier and the
statutes a hit actually mentions. In-process only; never calls Kanoon.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

from models.schemas import SearchResult
from services.embedder import embedder_service
from services.precedent_filter import decision_before

_HEADER = re.compile(r"^\[Cites[^\]]*\]\s*")
SNIPPET_CHARS = 300


@dataclass
class LibraryHit:
    doc_id: str
    title: str
    court: Optional[str]
    court_tier: str
    date: Optional[str]
    url: str
    snippet: str
    cosine: float
    similarity_score: float
    matched_statutes: List[str] = field(default_factory=list)
    text: str = ""

    def as_search_result(self) -> SearchResult:
        """Shape the graph builder and the outcome heuristic consume (legacy score, not cosine)."""
        return SearchResult(
            title=self.title, url=self.url, doc_id=self.doc_id, court=self.court, date=self.date,
            snippet=self.snippet, similarity_score=min(max(self.similarity_score, 0.0), 1.0),
        )


@dataclass
class LibrarySearch:
    query: str
    hits: List[LibraryHit]
    before_date: Optional[date]
    undated_excluded: int
    index: Dict[str, Any]


def court_tier(court: Optional[str]) -> str:
    c = (court or "").lower()
    if "supreme" in c:
        return "SC"
    if "high court" in c:
        return "HC"
    return "other"


_TITLE_LEAD = re.compile(r"^\s*\d+\)\s*")
_TITLE_DATE = re.compile(r"\s+on\s+\d{1,2}\s+\w+,?\s+\d{4}\s*$")


def clean_title(title: str) -> str:
    """Kanoon titles carry scrape artifacts ('6) Sk. Aziz vs The State on 24 December, 2010'); the date has its own field."""
    return _TITLE_DATE.sub("", _TITLE_LEAD.sub("", title or "")).strip()


def clean_snippet(text: str) -> str:
    t = _HEADER.sub("", text or "")
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) <= SNIPPET_CHARS:
        return t
    cut = t[:SNIPPET_CHARS].rsplit(" ", 1)[0]
    return cut + "…"


def statutes_mentioned(text: str, sections: List[str]) -> List[str]:
    """Which of the case's section numbers appear in this passage (e.g. 'Section 302' -> s.302)."""
    found: List[str] = []
    for s in sections:
        m = re.search(r"(\d+[A-Za-z]?)", s)
        if not m:
            continue
        num = m.group(1)
        if re.search(rf"\b(?:section|sec\.?|s\.)\s*{re.escape(num)}\b", text, re.I) and s not in found:
            found.append(s)
    return found


async def search_library(
    query: str,
    top_k: int = 5,
    before_date: Optional[date] = None,
    tier: str = "any",
    sections: Optional[List[str]] = None,
) -> LibrarySearch:
    index = embedder_service.index_info()
    if embedder_service.is_empty:
        return LibrarySearch(query, [], before_date, 0, index)

    vec = await embedder_service.embed_query(query)
    # Chunks of one judgment crowd the head of the ranking, and the date/tier filters drop more, so scan wide.
    pool = embedder_service.total_vectors if (before_date or tier != "any") else max(top_k * 6, 30)
    raw = embedder_service.search(vec, top_k=pool)

    hits: List[LibraryHit] = []
    seen: set = set()
    undated: set = set()
    for r in raw:
        meta = r["metadata"]
        doc_id = meta.get("doc_id", "")
        if doc_id in seen:
            continue
        if before_date and not decision_before(meta.get("date"), before_date):
            if not meta.get("date"):
                undated.add(doc_id)
            continue
        if tier != "any" and court_tier(meta.get("court")) != tier:
            continue
        seen.add(doc_id)
        text = meta.get("text", "")
        hits.append(LibraryHit(
            doc_id=doc_id, title=clean_title(meta.get("title", "")), court=meta.get("court"), court_tier=court_tier(meta.get("court")),
            date=meta.get("date"), url=meta.get("url", ""), snippet=clean_snippet(text),
            cosine=r["cosine"], similarity_score=r["similarity_score"],
            matched_statutes=statutes_mentioned(text, sections or []), text=text,
        ))
        if len(hits) >= top_k:
            break
    return LibrarySearch(query, hits, before_date, len(undated), index)
