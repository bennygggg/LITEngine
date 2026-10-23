"""
Tier-1 deterministic router and the never-infer parser.

Handles the requests whose intent is unambiguous by keyword — instantly, for free, and the same way every time — and is
also the fallback when the LLM is unavailable. Anything it cannot place with confidence is handed to the LLM planner
(Tier 2) when one is available. The phrasing the HF probe showed models getting wrong ("what if…", "compare outcomes…",
"who are the parties…") is exactly what these rules cover.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from models.agent_schemas import ToolName

_NUMBERS = {"one": 1, "a": 1, "an": 1, "two": 2, "three": 3, "four": 4, "five": 5}


@dataclass
class PlannedTool:
    name: ToolName
    args: Dict[str, Any] = field(default_factory=dict)
    origin: str = "forced"  # forced | llm | dependency


@dataclass
class Route:
    kind: str  # "tools" | "help" | "ambiguous"
    tools: List[PlannedTool] = field(default_factory=list)
    reason: str = ""
    confidence: float = 1.0


# --- never infer --------------------------------------------------------------

_ACCUSED = [
    r"\bi(?:'m| am)\s+the\s+(?:accused|convict(?:ed)?|appellant)\b",
    r"\bwe\s+(?:represent|act\s+for|appear\s+for)\s+the\s+(?:accused|convict(?:ed)?|appellant)\b",
    r"\b(?:main|mai|hum)\s+accused\s+(?:hoon|hu|hain)\b",
    r"\baccused(?:'s|s)?\s+(?:own\s+)?appeal\b",
    r"\bappeal\s+(?:by|of|filed\s+by)\s+the\s+(?:accused|convict(?:ed)?)\b",
    r"\bappeal(?:ing)?\s+(?:against|from)\s+(?:the\s+|his\s+|her\s+|their\s+)?conviction\b",
    r"\bI(?:'m| am)\s+(?:the\s+)?accused\b",
]
_STATE = [
    r"\bstate(?:'s|s)?\s+appeal\b",
    r"\bappeal\s+(?:by|of|filed\s+by)\s+the\s+(?:state|complainant|prosecution)\b",
    r"\b(?:state|complainant|prosecution)\s+(?:is|as|are)\s+(?:the\s+)?appellants?\b",
    r"\bappeal(?:ing)?\s+(?:against|from)\s+(?:the\s+|an\s+)?acquittal\b",
    r"\bwe\s+(?:represent|act\s+for|appear\s+for)\s+the\s+(?:state|complainant|prosecution)\b",
]


def parse_explicit_appellant(text: str) -> Optional[str]:
    """Return the appellant type ONLY if the user's own words state it. Conservative on purpose: when in doubt, None."""
    t = text.lower()
    accused = any(re.search(p, t, re.I) for p in _ACCUSED)
    state = any(re.search(p, t, re.I) for p in _STATE)
    if accused and not state:
        return "accused_appeal"
    if state and not accused:
        return "state_appeal"
    return None


_DATE = re.compile(r"\b(20\d{2}|19\d{2})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b")


def parse_explicit_date(text: str) -> Optional[str]:
    m = _DATE.search(text)
    return m.group(0) if m else None


# --- intent rules -------------------------------------------------------------

_RULES = [
    ("full_review", r"\b(?:full|complete|comprehensive)\s+(?:review|analysis)\b|\banaly[sz]e\s+(?:this|the)\s+(?:appeal|case|matter)\b|\breview\s+(?:this|the)\s+(?:appeal|case|matter)\b"),
    ("scenario", r"\bwhat\s+if\b|\bsuppose\b|\bscenarios?\b|\bcompare\s+(?:the\s+)?outcomes?\b|\bhypothetical"),
    ("outcome", r"\b(?:chances?|likel(?:y|ihood)|probab\w*|succe\w+|win|outcome|odds|prospects?)\b|\bappeal\s+ke\s+chances\b"),
    ("map", r"\bargument\s*(?:map|graph|structure)\b|\bmap\s+(?:out\s+)?(?:the\s+)?(?:arguments?|case)\b|\bweak\s+(?:points?|claims?|arguments?|spots?)\b"),
    ("precedents", r"\bwho\s+won\b|\bwhat\s+did\s+.{2,60}?\s+(?:hold|decide|rule|lay\s+down)\b|\b(?:holding|ratio|facts)\s+(?:of|in)\s+[A-Z]|\bprecedents?\b|\bcase\s*law\b|\bauthorit(?:y|ies)\b|\b(?:similar|closest|relevant|leading|landmark)\s+(?:cases?|judgments?|decisions?|authorit\w+)\b|\bjudgments?\s+(?:on|about|closest|similar)\b|\b(?:judgments?|decisions?|cases?)\b.{0,40}\b(?:closest|most\s+similar|most\s+relevant)\b|\b(?:supreme\s+court|high\s+court)\s+(?:judgments?|decisions?|rulings?)\b"),
    ("facts", r"\bsummar(?:y|ise|ize)\b|\bkey\s+facts?\b|\bparties\b|\bwho\s+(?:is|are)\s+the\b|\bwhich\s+court\b|\bwhat\s+court\b|\bwhat(?:'s|\s+is)\s+(?:this|the)\s+(?:case|matter|appeal)\s+about\b|\bextract\s+(?:the\s+)?facts?\b"),
]
_GREETING = re.compile(r"\b(?:hi|hello|hey|namaste|help|what\s+can\s+you\s+do|who\s+are\s+you|how\s+does\s+this\s+work)\b", re.I)
_QUESTION = re.compile(r"\?\s*$|^\s*(?:what|why|how|when|where|who|which|did|does|do|is|was|were|can|could|has|have|according)\b", re.I)


_BREVITY = re.compile(
    r"\bone[\s-]?(?:liner|line|sentence|lined)\b|\b(?:in|as)\s+(?:a|one|1|single)\s+(?:line|sentence)\b|\bsingle\s+(?:line|sentence)\b|\b1[\s-]?(?:line|sentence)\b"
    r"|\btl;?\s?dr\b|\b(?:short|quick|brief)\s+answer\b|\bbriefly\b|\bin\s+brief\b|\bin\s+short\b|\bkeep\s+it\s+(?:short|brief)\b|\bbe\s+(?:brief|short|concise)\b"
    r"|\bin\s+(?:a\s+)?(?:few|couple\s+of)\s+words\b|\bjust\s+(?:tell|give)\s+me\b", re.I)


def parse_brevity(text: str) -> bool:
    """True when the user asked for a short answer ("one liner please", "briefly", "tl;dr"). Read from this message only."""
    return bool(_BREVITY.search(text or ""))


_FILLER = re.compile(_BREVITY.pattern + r"|\bplease\b|\bexactly\b|\bkindly\b", re.I)
def retrieval_query(question: str) -> str:
    """The text used to search the document for a question. Request-style filler ("one liner please") says how to answer, not
    what to look for, and skews the ranking of passages. The model still sees the user's own words."""
    cleaned = re.sub(r"\s+", " ", _FILLER.sub(" ", question))
    cleaned = re.sub(r"\s+([?.!,;:])", r"\1", cleaned).strip(" ,;:-\u2014.")
    if not re.search(r"[A-Za-z]{3}", cleaned):
        cleaned = question.strip()
    return cleaned


def parse_scenario_levers(text: str) -> Dict[str, Any]:
    """Pull explicit levers out of a 'what if…' request. Only things the user actually said."""
    t = text.lower()
    changes: Dict[str, Any] = {}
    app = parse_explicit_appellant(text)
    if app is None and re.search(r"\b(?:what\s+if|suppose)\b.*\bstate\b.*\b(?:appellant|appeals?|appealing)\b", t):
        app = "state_appeal"
    if app is None and re.search(r"\b(?:what\s+if|suppose)\b.*\baccused\b.*\b(?:appellant|appeals?|appealing)\b", t):
        app = "accused_appeal"
    if app:
        changes["appellant_type"] = app
    m = re.search(r"\b(one|two|three|four|five|a|an|\d)\s+(?:more|additional|extra|further)\s+(?:supporting\s+)?(?:facts?|evidence|witness(?:es)?|corroboration)", t)
    if m:
        tok = m.group(1)
        changes["extra_supporting_facts"] = int(tok) if tok.isdigit() else _NUMBERS.get(tok, 1)
    elif re.search(r"\b(?:independent|corroborat\w+|additional|extra)\s+(?:witness|evidence|corroboration)", t):
        changes["extra_supporting_facts"] = 1
    for sec in re.findall(r"\b(?:add|adding|include|including)\s+(?:section\s+)?(\d{1,3}[a-z]?)\b", t):
        changes.setdefault("add_sections", []).append(sec.upper())
    for sec in re.findall(r"\b(?:drop|remove|without|dropping|removing)\s+(?:section\s+)?(\d{1,3}[a-z]?)\b", t):
        changes.setdefault("remove_sections", []).append(sec.upper())
    return changes


def scenario_specs(changes: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One scenario per lever, so each lever's own effect is visible (a combined scenario would hide which one mattered)."""
    specs: List[Dict[str, Any]] = []
    if "appellant_type" in changes:
        who = "the State were the appellant" if changes["appellant_type"] == "state_appeal" else "the accused were the appellant" if changes["appellant_type"] == "accused_appeal" else "the appeal type were not specified"
        specs.append({"label": f"If {who}", "changes": {"appellant_type": changes["appellant_type"]}})
    if "extra_supporting_facts" in changes:
        k = changes["extra_supporting_facts"]
        specs.append({"label": f"With {k} more supporting fact{'s' if k != 1 else ''}", "changes": {"extra_supporting_facts": k}})
    if "add_sections" in changes:
        specs.append({"label": "Adding section " + ", ".join(changes["add_sections"]), "changes": {"add_sections": changes["add_sections"]}})
    if "remove_sections" in changes:
        specs.append({"label": "Without section " + ", ".join(changes["remove_sections"]), "changes": {"remove_sections": changes["remove_sections"]}})
    return specs[:3]


def route(text: str, has_case: bool) -> Route:
    t = text.strip()
    if not t:
        return Route("help", reason="empty")
    hits = [name for name, pattern in _RULES if re.search(pattern, t, re.I)]
    if not hits and len(t) <= 60 and _GREETING.search(t):
        return Route("help", reason="greeting")
    # scenario phrasing wins over "outcome" words ("what if … chances"); full review wins over everything
    for name in ("full_review", "scenario"):
        if name in hits:
            hits = [name]
            break
    if "outcome" in hits and len(hits) > 1:
        hits = [h for h in hits if h != "outcome"] + ["outcome"]  # e.g. "map the arguments then estimate chances"
    if not hits:
        if has_case and _QUESTION.search(t):
            return Route("tools", [PlannedTool("ask_case", {"question": t[:500]})], reason="question about the document", confidence=0.7)
        return Route("ambiguous" if has_case else "help", reason="no rule matched", confidence=0.0)
    tools: List[PlannedTool] = []
    for h in hits[:3]:
        if h == "full_review":
            tools.append(PlannedTool("full_review"))
        elif h == "scenario":
            tools.append(PlannedTool("run_scenario", {"scenarios": scenario_specs(parse_scenario_levers(t))} if parse_scenario_levers(t) else {}))
        elif h == "outcome":
            args = {}
            app = parse_explicit_appellant(t)
            if app:
                args["appellant_type"] = app
            fd = parse_explicit_date(t)
            if fd:
                args["filing_date"] = fd
            tools.append(PlannedTool("assess_outcome", args))
        elif h == "map":
            tools.append(PlannedTool("build_argument_map"))
        elif h == "precedents":
            tools.append(PlannedTool("search_precedents", {"query": t[:400]} if not has_case or len(t.split()) >= 6 else {}))
        elif h == "facts":
            tools.append(PlannedTool("extract_case_facts"))
    return Route("tools", tools, reason=f"matched {hits}", confidence=0.9 if len(hits) == 1 else 0.6)
