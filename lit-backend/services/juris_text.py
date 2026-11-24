"""
Leakage tiers (shared by training and serving: one definition, so the two can never disagree).

Leakage tiers. A judgment contains the answer, so what the model may read has to be controlled and measured.

    T0  full text                         upper bound, not a prediction
    T1  order stripped (ILDC protocol)    the operative order is cut; the court's own REASONING stays
    T2  pre-reasoning (what Juris ships)  header, facts, trial-court findings, grounds and submissions only; cut at the
                                          earliest of: a reasoning cue, a verdict phrase, or 60 % of the document

T2 is the honest match for a live case: a user uploads facts and grounds, and there is no appellate reasoning yet.
"""

import re
from typing import Dict, Optional, Tuple

# Phrases that state the appellate court's own result. Used to cut T2/T1 and to MEASURE leakage afterwards.
VERDICT_RE = re.compile(
    r"\b(?:appeals?|petitions?|revisions?)\b[^.\n]{0,80}?\b(?:is|are|stands?|shall\s+stand|be|hereby)\b[^.\n]{0,40}?"
    r"\b(?:allowed|dismissed|partly\s+allowed|partially\s+allowed|rejected|succeeds|fails)\b"
    r"|\b(?:conviction|convictions|sentences?|judgments?|orders?|acquittal)\b[^.\n]{0,60}?\b(?:is|are|stands?|shall\s+stand|be|hereby)\b[^.\n]{0,20}?"
    r"\b(?:set\s+aside|upheld|confirmed|maintained|modified|restored|quashed)\b"
    r"|\b(?:appellants?|accused)\b[^.\n]{0,40}?\b(?:is|are|stands?|hereby)\b[^.\n]{0,15}?\b(?:acquitted|convicted)\b"
    r"|\b(?:allowed|dismissed)\s+(?:accordingly|as\s+above)\b|\bdisposed\s+of\s+(?:accordingly|in\s+the\s+above)"
    r"|\bappeal\s+(?:is\s+)?(?:partly|partially)\s+allowed\b",
    re.IGNORECASE,
)

_CUES = [
    # headings that open the court's own analysis
    r"^[ \t]*(?:\d+[.)]?[ \t]*)?(?:analysis|discussion|reasoning|consideration|findings?|observations?|conclusion)s?"
    r"(?:[ \t]+and[ \t]+(?:findings?|discussion|conclusion)s?)?[ \t]*:?[ \t]*$",
    # the court turns from the parties' cases to its own view
    r"\b(?:having\s+(?:heard|considered|perused|gone\s+through)|we\s+have\s+(?:carefully\s+|given\s+(?:our\s+)?(?:anxious|careful|thoughtful)\s+)?"
    r"(?:heard|considered|perused|gone\s+through|examined)|i\s+have\s+(?:carefully\s+)?(?:heard|considered|perused|gone\s+through|examined)"
    r"|upon\s+(?:a\s+)?(?:careful\s+|due\s+)?(?:perusal|consideration)|on\s+(?:a\s+)?(?:careful\s+|due\s+)?(?:perusal|consideration|re-?appreciation)"
    r"|after\s+(?:hearing|considering|perusing|carefully))\b",
    r"\bpoints?\s+for\s+(?:determination|consideration)\b|\bquestions?\s+(?:for|that)\s+(?:determination|consideration|arises?)\b"
    r"|\b(?:the\s+)?(?:only\s+|main\s+)?(?:issue|question|point)\s+(?:that\s+|which\s+)?(?:arises|falls|requires|emerges|for\s+(?:determination|consideration))\b",
    r"\b(?:in\s+(?:my|our)\s+(?:considered\s+|humble\s+)?(?:view|opinion)|this\s+court\s+(?:finds|is\s+of\s+the\s+view|has\s+considered)"
    r"|we\s+(?:find|are\s+of\s+the\s+(?:view|opinion))|i\s+(?:find|am\s+of\s+the\s+(?:view|opinion)))\b",
]
CUE_RE = re.compile("|".join(f"(?:{c})" for c in _CUES), re.IGNORECASE | re.MULTILINE)

T2_CAP = 0.60          # never keep more than this fraction of the document
MIN_HEAD_FRAC = 0.10   # a cue before this point is the opening of the document, not the start of reasoning
MIN_HEAD_CHARS = 1200
T1_WINDOW = 0.35       # the operative order is searched for in the last 35 % of the text


def _paragraph_start(text: str, pos: int, floor: int = 0) -> int:
    """Back off to the previous blank line so a cut never lands mid-sentence."""
    i = text.rfind("\n\n", floor, pos)
    return i if i != -1 else pos


def tier1(text: str, op_start: Optional[int] = None) -> Tuple[str, Dict[str, object]]:
    """Strip the operative order (and anything after it); keep the court's reasoning.

    `op_start` is where the label extractor located the operative phrase (when it found one); otherwise the verdict
    lexicon is used, and as a last resort the final 8 % is dropped (flagged `fallback`; such rows can still leak)."""
    n = len(text)
    start = int(n * (1 - T1_WINDOW))
    cands = []
    if op_start is not None and op_start >= start:
        cands.append(("label", op_start))
    m = VERDICT_RE.search(text, start)
    if m:
        cands.append(("verdict", m.start()))
    if cands:
        reason, pos = min(cands, key=lambda c: c[1])
        cut = _paragraph_start(text, pos, start)
        return text[:cut].rstrip(), {"t1_reason": reason, "t1_frac": round(cut / n, 3)}
    cut = int(n * 0.92)
    return text[:cut].rstrip(), {"t1_reason": "fallback", "t1_frac": 0.92}


def tier2(text: str, apply_cap: bool = True) -> Tuple[str, Dict[str, object]]:
    """Facts, trial-court findings, grounds and submissions only.

    `apply_cap=False` (used at serving for short documents, which are filings and not judgments) still cuts at a reasoning cue or a
    verdict phrase but does not throw away the last 40 % of a short document."""
    n = len(text)
    floor = max(MIN_HEAD_CHARS, int(n * MIN_HEAD_FRAC)) if apply_cap else min(MIN_HEAD_CHARS, n // 2)
    cap = int(n * T2_CAP) if apply_cap else n
    candidates = {"cap": cap}
    m = CUE_RE.search(text, floor)
    if m:
        candidates["cue"] = m.start()
    v = VERDICT_RE.search(text, floor // 2)
    if v:
        candidates["verdict"] = v.start()
    reason = min(candidates, key=candidates.get)
    cut = _paragraph_start(text, candidates[reason], floor // 2)
    return text[:cut].rstrip(), {"t2_reason": reason, "t2_frac": round(cut / n, 3)}


def leak_hits(text: str) -> int:
    return len(VERDICT_RE.findall(text))
