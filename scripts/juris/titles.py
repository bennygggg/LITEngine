"""
Parsing of the HC bucket's `title` field: "{TYPE}/{NUMBER}/{YEAR} of {PARTY1} Vs {PARTY2}".

Only case types we are CONFIDENT are criminal appeals are accepted. Look-alikes are rejected on purpose, e.g. Rajasthan
`CRLAS` (a suspension-of-sentence application inside an appeal), `CRLLA` (leave to appeal), `CRRA`/`CRR` (revisions) and
`CRMA`/`CRM(A)` (criminal miscellaneous applications, mostly bail). Their `disposal_nature` says nothing about the appeal.
"""

import re
from typing import Dict, Optional

_TITLE_RE = re.compile(
    r"^\s*(?:R/)?(?P<type>[^/]{1,40}?)\s*/\s*(?P<num>\d+)\s*/\s*(?P<year>\d{4})\s+of\s+(?P<parties>.*)$", re.IGNORECASE | re.DOTALL
)
_VS_RE = re.compile(r"\s+vs\.?\s+", re.IGNORECASE)

# Normalised case type: upper-case, spaces and dots removed ("Crl.A(J)" -> "CRLA(J)", "CR. APP (SJ)" -> "CRAPP(SJ)").
_APPEAL_TYPE_RE = re.compile(
    r"^(?:"
    r"J?CRLA(?:\((?:MD|J|D|S|AS|AD|DB|SB|HC)\))?"      # Crl.A, Crl.A(MD), Crl.A(J), JCRLA (Orissa jail appeals)
    r"|CRLAD|CRLJA|CRJA|CRAA|CRIA|JAPL"                  # Rajasthan/Uttarakhand/J&K/Goa/UP jail appeals
    r"|CRA(?:-(?:S|D|SB|DB|AS|AD|SJ))?(?:\((?:DB|SB|SJ|D|S|V)\))?"   # CRA, CRA-S, CRA-D, CRA(DB), CRA(SJ)
    r"|CRAPP(?:\((?:SJ|DB|V)\))?"                        # Patna: Cr. App (SJ) / (DB)
    r")$"
)
# Bombay's criminal appeals are filed as plain "APEAL"/"APPA"; the same prefixes elsewhere are civil, so require a State party.
_BOMBAY_TYPE_RE = re.compile(r"^(?:APEAL|APPA)$")

_STATE_RE = re.compile(
    r"\b(STATE|UNION OF INDIA|U\.?O\.?I|CBI|CENTRAL BUREAU|NATIONAL INVESTIGATION|NIA|NARCOTICS|DIRECTORATE|ENFORCEMENT|CUSTOMS|"
    r"EXCISE|UNION TERRITORY|U\.?T\.? OF|GOVT|GOVERNMENT|POLICE|INSPECTOR|SUPERINTENDENT|COMMISSIONER|REPUBLIC|COLLECTOR|S\.?H\.?O)\b",
    re.IGNORECASE,
)


def normalise_type(raw: str) -> str:
    return re.sub(r"[\s.]", "", raw or "").upper()


def parse_title(title: Optional[str]) -> Dict[str, Optional[str]]:
    m = _TITLE_RE.match(title or "")
    if not m:
        return {"ctype": "", "number": None, "case_year": None, "party1": None, "party2": None}
    parties = _VS_RE.split(m.group("parties").strip(), maxsplit=1)
    return {
        "ctype": normalise_type(m.group("type")), "number": m.group("num"), "case_year": m.group("year"),
        "party1": parties[0].strip() if parties else None, "party2": parties[1].strip() if len(parties) > 1 else None,
    }


def is_state_party(name: Optional[str]) -> bool:
    return isinstance(name, str) and bool(_STATE_RE.search(name))


def is_criminal_appeal(ctype: str, party1: Optional[str], party2: Optional[str]) -> bool:
    if _APPEAL_TYPE_RE.match(ctype):
        return True
    return bool(_BOMBAY_TYPE_RE.match(ctype) and (is_state_party(party1) or is_state_party(party2)))


def appellant_side(party1: Optional[str], party2: Optional[str]) -> str:
    """accused_appeal | state_appeal | unclear, from the caption's party order (appellant is named first).

    A private complainant appealing an acquittal is indistinguishable from an accused in the title when the respondent is
    the State; that residual error is stated as a limitation, not hidden."""
    if is_state_party(party1) and not is_state_party(party2):
        return "state_appeal"
    if is_state_party(party2) and not is_state_party(party1):
        return "accused_appeal"
    return "unclear"
