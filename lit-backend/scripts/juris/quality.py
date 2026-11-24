"""Text-quality and label-audit helpers: catch unreadable PDFs, procedural endings and metadata/text disagreements."""

import re
from typing import Dict, Optional

from scripts.outcome_dataset.labeling import extract_outcome_label

_STOP = frozenset("the of and to in is that was for by with on as are be this it at or from which not been has have".split())
_TOKEN_RE = re.compile(r"[A-Za-z]+")
TAIL_CHARS = 1500

# An appeal that ended for a reason other than the merits. "Dismissed" in the metadata can still mean one of these.
PROCEDURAL_RE = re.compile(
    r"\babat(?:e|es|ed|ement)\b|not\s+pressed|not\s+being\s+pressed|\bwithdraw(?:n|al|s)?\b|infructuous|\bcompromis|\bsettle(?:d|ment)\b|"
    r"\b(?:has|have)\s+(?:since\s+)?died|death\s+of\s+the|non[- ]?prosecution|want\s+of\s+prosecution|for\s+default|"
    r"delay\b.{0,60}\b(?:condon|not\s+condon|not\s+found\s+sufficient)|barred\s+by\s+(?:limitation|time)|time[- ]barred|"
    r"no\s+one\s+(?:appears|appeared)|none\s+(?:appears|appeared)|not\s+admitted",
    re.IGNORECASE | re.DOTALL,
)


def stopword_rate(text: str) -> float:
    tokens = _TOKEN_RE.findall(text[:30000].lower())
    if not tokens:
        return 0.0
    return sum(1 for t in tokens if t in _STOP) / len(tokens)


def is_readable(text: str, min_rate: float = 0.08) -> bool:
    """Judgments in English run at roughly 0.15-0.25; image-font PDFs that decode to symbols sit near zero."""
    return stopword_rate(text) >= min_rate


def tail_label(text: str) -> Dict[str, object]:
    """What the operative end of the document says, mapped to the Juris target (succeeds | dismissed | None)."""
    res = extract_outcome_label(text)
    label: Optional[str] = {"allowed": "succeeds", "partly_allowed": "succeeds", "dismissed": "dismissed"}.get(res["label"])
    return {"text_label": label, "text_conf": float(res["confidence"]), "text_match_start": res["match_start"]}


# The order decides an application INSIDE a pending appeal (bail, suspension of sentence, admission), not the appeal itself.
INTERLOCUTORY_RE = re.compile(
    r"pendency of (?:the|this)|during (?:the )?pendency|till (?:the )?disposal of|until (?:the )?disposal of|released on bail|enlarged on bail|"
    r"appeal (?:is|be|stands) admitted|\badmit\b|suspension of|sentence (?:is|shall be|stands) suspended|suspended during",
    re.IGNORECASE,
)


def interlocutory_tail(text: str) -> bool:
    return bool(INTERLOCUTORY_RE.search(text[-TAIL_CHARS:]))


def procedural_tail(text: str) -> bool:
    return bool(PROCEDURAL_RE.search(text[-TAIL_CHARS:]))
