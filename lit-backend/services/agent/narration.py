"""
Templated narration — the no-LLM voice of the product.

Used when the LLM is off, unavailable, or the user asked for `narrate: "template"`. It never invents anything: every
sentence is assembled from what the tools returned, with `[P#]` / `[S#]` handles that resolve to the cards on screen.
(When the LLM is on, it receives the same facts as compact summaries and writes this in its own words.)
"""

import re
from typing import Any, List, Optional

from models.agent_schemas import AgentChatRequest, CaseInputs
from services.agent.tools import RunContext

HELP = (
    "I can help you work through a criminal appeal. Attach a matter with **+**, then ask me to:\n\n"
    "- **Read the case** — parties, issues, statutes, key facts\n"
    "- **Find precedents** — the closest judgments in the library\n"
    "- **Map the arguments** — how claims, evidence and law connect, and where support is thin\n"
    "- **Assess the outcome** — an indicative estimate, with what drives it\n"
    "- **Explore scenarios** — how that estimate moves if an input changes\n"
    "- **Answer from the document** — with the passages that support each answer\n\n"
    "You can also pick any of these from the **+** menu."
)
NO_CASE = "I need a matter to work from — attach one with **+** (upload a judgment, or choose a sample matter), then ask again."
OFF_TOPIC = (
    "I couldn't find anything in this document that speaks to that, and it isn't something I do. "
    "I can read the case, find precedents, map the arguments, estimate the outcome, run scenarios, or answer questions from the document."
)


def intro(tools: List[Any]) -> Optional[str]:
    names = [t.name for t in tools]
    if "full_review" in names:
        return "I'll read the matter, search the precedent library, map the arguments and score the appeal — each step appears as it completes."
    return None


def _pct(p: float) -> str:
    return f"{round(p * 20) * 5}%"


def outro(ctx: RunContext) -> str:
    """What the cards can't say at a glance — never a restatement of them. Every figure comes from a tool result."""
    parts: List[str] = []
    cards = ctx.emitted_cards
    kinds = [c.type for c in cards]

    if "case_profile" in kinds and ctx.quality and ctx.quality.quality != "good":
        parts.append(f"Extraction was **{ctx.quality.quality}** (missing: {', '.join(ctx.quality.missing)}), so check the profile against the source before relying on later steps.")

    if "precedents" in kinds and ctx.search is not None:
        s = ctx.search
        if s.hits:
            lead = " and ".join(f"[P{i}]" for i in range(1, min(2, len(s.hits)) + 1))
            parts.append(f"Closest matches in the library are listed above — start with {lead}. They are the nearest judgments by meaning among {s.index['docs']} indexed, not a finding that any of them supports the appeal.")
        else:
            parts.append("Nothing in the library matched closely" + (f" among judgments decided before {s.before_date:%d %b %Y}" if s.before_date else "") + ".")

    if "argument_map" in kinds and ctx.graph is not None:
        weak = len(ctx.graph["weak_nodes"])
        parts.append(f"**{weak} claim{'s' if weak != 1 else ''}** lack an evidence link — worth checking against the record." if weak
                     else "No claim is flagged as lacking an evidence link — but that says nothing about how strong the evidence is.")

    if "outcome" in kinds:
        card = next(c for c in cards if c.type == "outcome")
        parts.append(f"Treat this as a base-rate indicator learned from {card.model.n_train or 'a small number of'} past appeals: it mostly reflects who is appealing, not the strength of this case.")

    if "scenario" in kinds:
        parts.append("Appeal type is the only input that moves this model materially; the others barely register, so treat small differences as noise.")

    if "sources" in kinds:
        card = next(c for c in cards if c.type == "sources")
        if card.excerpts and card.excerpts[0].cosine >= 0.25:
            quote = card.excerpts[0].text.replace("\n", " ")
            quote = quote if len(quote) <= 420 else quote[:420].rsplit(" ", 1)[0] + "…"
            parts.append(f"The most relevant passage [S1]: “{quote}”")
            if len(card.excerpts) > 1:
                n = len(card.excerpts) - 1
                parts.append(f"{n} more passage{'s are' if n > 1 else ' is'} listed under the sources.")
        else:
            parts.append(OFF_TOPIC)
    return "\n\n".join(parts)


def suggestions(ctx: RunContext) -> List[dict]:
    kinds = {c.type for c in ctx.emitted_cards}
    out: List[dict] = []
    if ctx.ws is None:
        return out
    crim = ctx.profile is None or ctx.profile.case_type == "criminal"
    if "case_profile" in kinds and "precedents" not in kinds:
        out.append({"label": "Find the closest precedents", "prompt": "Find the closest precedents", "forced_tool": {"name": "search_precedents", "args": {}}})
    if "argument_map" not in kinds:
        out.append({"label": "Map the arguments", "prompt": "Map the arguments", "forced_tool": {"name": "build_argument_map", "args": {}}})
    if crim and "outcome" not in kinds:
        out.append({"label": "Estimate the outcome", "prompt": "Estimate the outcome", "forced_tool": {"name": "assess_outcome", "args": {}}})
    if "outcome" in kinds and "scenario" not in kinds:
        out.append({"label": "Explore scenarios", "prompt": "Compare the appeal types", "forced_tool": {"name": "run_scenario", "args": {}}})
    if "sources" not in kinds:
        out.append({"label": "Ask about the document", "prompt": "What does the judgment say about the key issue?", "forced_tool": None})
    return out[:4]
