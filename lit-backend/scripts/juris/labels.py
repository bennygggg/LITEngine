"""
Maps the bucket's raw `disposal_nature` strings to the binary Juris target.

    succeeds  - the appeal was allowed in whole or in part (the appellant obtained relief)
    dismissed - the appeal was dismissed on the merits
    neutral   - "disposed of" with no direction: the outcome has to come from the order's text
    None      - procedural endings (withdrawn, abated, default, infructuous, not pressed ...) and blanks: not an appeal outcome

"succeeds" always means the APPELLANT won, whoever the appellant is.
"""

import re
from typing import Optional, Tuple

# Order matters: the first matching rule wins.
_RULES = [
    ("none", re.compile(r"withdraw|abate|infructu|infract|default|non[- ]?prosecution|want of prosecution|not pressed|bail|consigned|"
                        r"converted|transfer|return|rejected as|dismissed as (?:barred|time)|other than merit|compromis|settle", re.I)),
    ("dismissed", re.compile(r"not allowed|disallowed", re.I)),
    ("succeeds", re.compile(r"part(?:ly|ially)? allowed|allowed in part|allowed/partly|allowed and remand|allowed with|\ballowed\b|"
                            r"appeal is allowed|remand", re.I)),
    ("dismissed", re.compile(r"dismiss(?:ed|al)?\b|dismised|rejected|\bdismis", re.I)),
    ("neutral", re.compile(r"dispos(?:ed|al)", re.I)),
]


def map_disposal(raw: Optional[str]) -> Tuple[Optional[str], str]:
    """Return (label, rule) where label is succeeds|dismissed|neutral|None."""
    text = (raw or "").strip()
    if not text:
        return None, "blank"
    for name, rx in _RULES:
        if rx.search(text):
            return (None if name == "none" else name), name
    return None, "unmapped"
