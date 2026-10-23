"""
Tool executors and the dependency resolver.

Each artifact (profile, precedents, graph, outcome) is computed at most once per case + inputs (singleflight, cached in
the case workspace). A tool asks for what it needs; missing prerequisites run first as `dependency` steps. Dependency-only
results get a step row but no card (the exception: the first Case-profile card in a conversation, so the user always
sees what the system understood before trusting anything downstream).

Never-infer: `appellant_type` and `filing_date` are accepted only from the user's form, an explicit statement in their
own words, or a UI-forced tool call — never from the model's guess or from the case text. Otherwise the run pauses with a
needs-input card.
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from config import get_settings
from models.agent_schemas import (
    AgentChatRequest, ArtifactUpdateEvent, CardEvent, CaseInputs, ExtractionQuality, ForcedTool, NeedsInputEvent,
    ScenarioChanges, ScenarioSpec, StepEvent, TextDeltaEvent,
)
from models.schemas import SearchResult, StructuredCaseProfile
from services.agent import cards
from services.agent.events import RunLog
from services.agent.llm.base import UsageTotals
from services.embedder import embedder_service
from services.agent.extraction import assess_quality, extract_profile, profile_key
from services.agent.library import LibrarySearch, search_library
from services.agent.routing import parse_explicit_appellant
from services.agent.workspace import CaseWorkspace, artifact_key
from services.graph_builder import build_argument_graph
from services.outcome_model import is_model_loaded
from services.outcome_pipeline import ScoredCase, score_case
from services.scenario import run_scenarios
from utils.logger import get_logger

logger = get_logger(__name__)

TOOL_LABELS = {
    "extract_case_facts": "Reading the case",
    "search_precedents": "Searching the precedent library",
    "build_argument_map": "Mapping the arguments",
    "assess_outcome": "Scoring the appeal",
    "run_scenario": "Re-scoring under the scenarios",
    "ask_case": "Searching the document",
}


class ToolError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code, self.message, self.retryable = code, message, retryable


class AwaitingInput(Exception):
    """Raised after a needs-input card has been emitted; the run ends with status awaiting_input."""


@dataclass
class RunContext:
    request: AgentChatRequest
    log: RunLog
    ws: Optional[CaseWorkspace]
    message_id: str
    inputs: CaseInputs
    user_text: str
    emitted_cards: List[Any] = field(default_factory=list)
    first_card_ms: Optional[int] = None
    first_text_ms: Optional[int] = None
    part_counter: int = 0
    # run-local handles to artifacts so narration can describe them and tools can reuse them
    profile: Optional[StructuredCaseProfile] = None
    quality: Optional[ExtractionQuality] = None
    search: Optional[LibrarySearch] = None
    graph: Optional[Dict[str, Any]] = None
    scored: Optional[ScoredCase] = None
    appellant_source: str = "user_input"
    last_tool: Optional[str] = None
    notes: List[str] = field(default_factory=list)
    llm: Any = None                      # an LLMClient, or None for deterministic mode
    usage: UsageTotals = field(default_factory=UsageTotals)
    text_part: Optional[str] = None      # the open streaming text part, if any
    warnings: List[str] = field(default_factory=list)
    narration_failed: bool = False

    def next_part(self) -> str:
        self.part_counter += 1
        return f"p{self.part_counter}"


def _filing_date(value: Any) -> Optional[date]:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


class Tools:
    def __init__(self, ctx: RunContext) -> None:
        self.ctx = ctx
        self.settings = get_settings()

    # ------------------------------------------------------------------ plumbing
    def _require_case(self) -> CaseWorkspace:
        if self.ctx.ws is None:
            raise ToolError("no_case", "Attach a case first — this needs the text of a matter to work from.")
        return self.ctx.ws

    async def _step(self, tool: str, origin: str, fn: Callable[[], Awaitable[Tuple[Any, bool]]],
                    args_preview: Optional[Dict[str, Any]] = None, summarize: Optional[Callable[[Any], str]] = None,
                    label: Optional[str] = None, card: bool = False) -> Tuple[Any, str]:
        ctx, log = self.ctx, self.ctx.log
        step_id = cards.new_id("s")
        log.emit(StepEvent, step_id=step_id, phase="start", tool=tool, label=label or TOOL_LABELS.get(tool, tool),
                 origin=origin, args_preview=args_preview or {}, produces_card=card)
        started = time.perf_counter()
        try:
            value, cached = await asyncio.wait_for(fn(), self.settings.AGENT_TOOL_TIMEOUT_S)
        except asyncio.TimeoutError:
            log.emit(StepEvent, step_id=step_id, phase="end", tool=tool, label=TOOL_LABELS.get(tool, tool), origin=origin,
                     status="error", duration_ms=int((time.perf_counter() - started) * 1000), summary="timed out")
            raise ToolError("tool_timeout", "That step took too long. Please try again.", retryable=True)
        except ToolError as exc:
            log.emit(StepEvent, step_id=step_id, phase="end", tool=tool, label=TOOL_LABELS.get(tool, tool), origin=origin,
                     status="error", duration_ms=int((time.perf_counter() - started) * 1000), summary=exc.message[:120])
            raise
        ms = int((time.perf_counter() - started) * 1000)
        log.emit(StepEvent, step_id=step_id, phase="end", tool=tool, label=TOOL_LABELS.get(tool, tool), origin=origin,
                 status="cached" if cached else "ok", duration_ms=ms, summary=summarize(value) if summarize else None)
        return value, step_id

    def emit_card(self, card: Any, step_id: Optional[str] = None) -> None:
        ctx = self.ctx
        part_id = ctx.next_part()
        ctx.log.emit(CardEvent, card_id=card.card_id, part_id=part_id, step_id=step_id, payload=card)
        ctx.emitted_cards.append(card)
        if ctx.first_card_ms is None:
            ctx.first_card_ms = ctx.log.emitter.elapsed_ms()

    def stream_text(self, delta: str) -> None:
        """Append to the open text part (opening one if needed) — used for token streaming."""
        ctx = self.ctx
        if not delta:
            return
        if ctx.first_text_ms is None:
            ctx.first_text_ms = ctx.log.emitter.elapsed_ms()
        if ctx.text_part is None:
            ctx.text_part = ctx.next_part()
        ctx.log.emit(TextDeltaEvent, message_id=ctx.message_id, part_id=ctx.text_part, delta=delta)

    def end_text(self) -> None:
        self.ctx.text_part = None

    def emit_text(self, text: str) -> None:
        """A complete paragraph as its own text part."""
        self.end_text()
        self.stream_text(text)
        self.end_text()

    def _artifact(self, kind: str, key: str, card_id: Optional[str], implicit: bool) -> None:
        self.ctx.log.emit(ArtifactUpdateEvent, kind=kind, key=key, card_id=card_id, implicit=implicit)

    # ------------------------------------------------------------------ inputs (never-infer)
    def accept_inputs(self, args: Dict[str, Any], origin: str) -> None:
        """Merge appellant_type / filing_date from tool args — but only when the user could have stated them."""
        ctx = self.ctx
        app = args.get("appellant_type")
        if app in ("accused_appeal", "state_appeal", "unclear"):
            trusted = origin == "forced" or parse_explicit_appellant(ctx.user_text) == app
            if trusted and ctx.inputs.appellant_type != app:
                ctx.inputs = ctx.inputs.model_copy(update={"appellant_type": app})
                ctx.appellant_source = "user_input"
            elif not trusted:
                logger.info("Dropped an appellant_type the user never stated (never-infer rule)")
        fd = _filing_date(args.get("filing_date"))
        if fd and (origin == "forced" or str(fd) in ctx.user_text):
            ctx.inputs = ctx.inputs.model_copy(update={"filing_date": fd})

    def _need_inputs(self, tool: str, args: Dict[str, Any]) -> None:
        ctx = self.ctx
        need_app, need_date = ctx.inputs.appellant_type is None, ctx.inputs.filing_date is None
        if not (need_app or need_date):
            return
        reason = {
            "assess_outcome": "To estimate the outcome I need two facts only you can supply.",
            "run_scenario": "Scenarios compare against a base estimate, which needs two facts only you can supply.",
            "full_review": "To finish the review I need two facts only you can supply.",
        }.get(tool, "I need two facts only you can supply.")
        card = cards.needs_input_card(ForcedTool(name=tool, args=args), need_app, need_date, reason)  # type: ignore[arg-type]
        part_id = ctx.next_part()
        ctx.log.emit(NeedsInputEvent, card_id=card.card_id, part_id=part_id, payload=card)
        ctx.emitted_cards.append(card)
        raise AwaitingInput()

    # ------------------------------------------------------------------ artifacts
    async def profile(self, origin: str, show: bool = False) -> StructuredCaseProfile:
        ctx = self.ctx
        if ctx.profile is not None and not show:
            return ctx.profile
        ws = self._require_case()
        override = ctx.request.case.profile_override if ctx.request.case else None
        key = profile_key(ws.sha, override)
        started = time.perf_counter()

        async def compute() -> Tuple[Any, bool]:
            value, cached = await ws.get_or_compute(key, lambda: _profile_value(ws.text, override))
            return value, cached

        first_in_conversation = (ctx.request.conversation_id, "profile_card") not in ws_shown(ws)
        value, step_id = await self._step("extract_case_facts", origin, compute,
                                          args_preview={"case": ws.title or ws.filename or ""},
                                          summarize=lambda v: f"{len(v[0].legal_issues)} issues, {len(v[0].ipc_sections)} sections",
                                          card=show or first_in_conversation)
        profile, quality = value
        ctx.profile, ctx.quality = profile, quality
        if show or first_in_conversation:
            card = cards.profile_card(cards.new_id("card"), profile, quality, ctx.inputs, int((time.perf_counter() - started) * 1000))
            self.emit_card(card, step_id)
            ws_shown(ws).add((ctx.request.conversation_id, "profile_card"))
            self._artifact("profile", key, card.card_id, implicit=not show)
        else:
            self._artifact("profile", key, None, implicit=True)
        return profile

    async def precedents(self, origin: str, query: Optional[str] = None, top_k: int = 5, show: bool = False) -> LibrarySearch:
        ctx = self.ctx
        profile = await self.profile("dependency") if ctx.ws else None
        ws = ctx.ws
        sections = list(profile.ipc_sections) if profile else []
        query_source = "user" if query else "issues"
        q = (query or "").strip()
        if not q and profile:
            q = " ".join(profile.legal_issues)[:400] or (ws.text[:400] if ws else "")
        if not q:
            raise ToolError("no_query", "Tell me what to search for, or attach a case so I can use its issues.")
        cutoff = ctx.inputs.filing_date
        key = artifact_key("precedents", ws.sha if ws else "none", q, str(cutoff), top_k, embedder_service.index_version)
        started = time.perf_counter()

        async def compute() -> Tuple[Any, bool]:
            if ws:
                return await ws.get_or_compute(key, lambda: search_library(q, top_k, cutoff, sections=sections))
            return await search_library(q, top_k, cutoff, sections=sections), False

        search, step_id = await self._step(
            "search_precedents", origin, compute, args_preview={"query": q[:120], "before": str(cutoff) if cutoff else None},
            summarize=lambda s: f"{len(s.hits)} judgments" + (f", {s.undated_excluded} undated excluded" if s.undated_excluded else ""),
            card=show)
        if ctx.search is None or [h.doc_id for h in ctx.search.hits[:3]] != [h.doc_id for h in search.hits[:3]]:
            ctx.graph = ctx.scored = None  # the map and estimate depend on the top precedents; they are stale now
        ctx.search = search
        if show:
            card = cards.precedents_card(cards.new_id("card"), search, query_source, [f"P{i}" for i in range(1, min(3, len(search.hits)) + 1)],
                                         int((time.perf_counter() - started) * 1000))
            self.emit_card(card, step_id)
            self._artifact("precedents", key, card.card_id, implicit=False)
        else:
            self._artifact("precedents", key, None, implicit=True)
        return search

    async def graph(self, origin: str, show: bool = False) -> Dict[str, Any]:
        ctx = self.ctx
        profile = await self.profile("dependency")
        search = ctx.search or await self.precedents("dependency")
        ws = self._require_case()
        top3 = [h.as_search_result() for h in search.hits[:3]]
        key = artifact_key("graph", ws.sha, profile.model_dump_json(), [h.doc_id for h in search.hits[:3]])
        started = time.perf_counter()

        async def compute() -> Tuple[Any, bool]:
            return await ws.get_or_compute(key, lambda: asyncio.to_thread(build_argument_graph, profile, top3))

        graph, step_id = await self._step("build_argument_map", origin, compute,
                                          summarize=lambda g: f"{g['node_count']} elements, {g['edge_count']} links", card=show)
        ctx.graph = graph
        if show:
            card = cards.argument_map_card(cards.new_id("card"), graph, int((time.perf_counter() - started) * 1000))
            self.emit_card(card, step_id)
            self._artifact("graph", key, card.card_id, implicit=False)
        else:
            self._artifact("graph", key, None, implicit=True)
        return graph

    def _guard_outcome(self, profile: StructuredCaseProfile, tool: str) -> None:
        if profile.case_type != "criminal":
            raise ToolError("outcome_out_of_scope",
                            "Outcome analysis is only available for criminal appeals — that is what the model was trained on. "
                            "I can still extract the facts, find closest precedents and map the arguments for this matter.")
        if not is_model_loaded():
            raise ToolError("model_unavailable", "The trained outcome model isn't loaded right now, so I can't produce an estimate.", retryable=True)

    async def outcome(self, origin: str, args: Dict[str, Any], show: bool = False) -> ScoredCase:
        ctx = self.ctx
        self.accept_inputs(args, origin)
        profile = await self.profile("dependency")
        self._guard_outcome(profile, "assess_outcome")
        self._need_inputs(ctx.last_tool or "assess_outcome", args)
        search = ctx.search if (ctx.search and ctx.search.before_date == ctx.inputs.filing_date) else await self.precedents("dependency")
        graph = ctx.graph or await self.graph("dependency")
        ws = self._require_case()
        appellant = ctx.inputs.appellant_type or "unclear"
        key = artifact_key("outcome", ws.sha, profile.model_dump_json(), [h.doc_id for h in search.hits[:5]], graph["node_count"],
                           graph["weak_nodes"], appellant, str(ctx.inputs.filing_date))
        started = time.perf_counter()
        graph_stats = {"node_count": graph["node_count"], "weak_nodes": graph["weak_nodes"]}
        precs = [h.as_search_result() for h in search.hits[:5]]

        async def compute() -> Tuple[Any, bool]:
            return await ws.get_or_compute(key, lambda: asyncio.to_thread(score_case, profile, precs, graph_stats, appellant, True))

        scored, step_id = await self._step("assess_outcome", origin, compute,
                                           summarize=lambda s: f"{round(s.ml.probabilities.get('succeeds', 0) * 100)}% (indicative)", card=show)
        ctx.scored = scored
        if not scored.ml.model_loaded:
            raise ToolError("model_unavailable", "The trained outcome model isn't loaded right now, so I can't produce an estimate.", retryable=True)
        if show:
            card = cards.outcome_card(cards.new_id("card"), scored, appellant, ctx.inputs.filing_date,  # type: ignore[arg-type]
                                      profile.metadata.extraction_method if profile.metadata else None,
                                      int((time.perf_counter() - started) * 1000), appellant_source=ctx.appellant_source)
            self.emit_card(card, step_id)
            self._artifact("outcome", key, card.card_id, implicit=False)
        else:
            self._artifact("outcome", key, None, implicit=True)
        return scored

    async def scenario(self, origin: str, args: Dict[str, Any]) -> None:
        ctx = self.ctx
        self.accept_inputs(args, origin)
        profile = await self.profile("dependency")
        self._guard_outcome(profile, "run_scenario")
        self._need_inputs(ctx.last_tool or "run_scenario", args)
        await self.outcome("dependency", {}, show=False)
        search, graph = ctx.search, ctx.graph
        assert search is not None and graph is not None
        appellant = ctx.inputs.appellant_type or "unclear"
        specs = self._scenario_specs(args, appellant, search)
        precs = [h.as_search_result() for h in search.hits[:5]]
        graph_stats = {"node_count": graph["node_count"], "weak_nodes": graph["weak_nodes"]}
        started = time.perf_counter()

        async def compute() -> Tuple[Any, bool]:
            return await asyncio.to_thread(run_scenarios, profile, precs, graph_stats, appellant, specs, True), False

        (base, outcomes, sensitivity, _), step_id = await self._step(
            "run_scenario", origin, compute, args_preview={"scenarios": [s.label for s in specs]},
            summarize=lambda r: ", ".join(f"{o.label}: {o.delta_pp:+.1f} pts" for o in r[1]), card=True)
        card = cards.scenario_card(cards.new_id("card"), base, outcomes, sensitivity, int((time.perf_counter() - started) * 1000))
        self.emit_card(card, step_id)
        self._artifact("scenario", artifact_key("scenario", [s.label for s in specs]), card.card_id, implicit=False)

    def _scenario_specs(self, args: Dict[str, Any], appellant: str, search: LibrarySearch) -> List[ScenarioSpec]:
        raw = args.get("scenarios") or []
        specs: List[ScenarioSpec] = []
        for i, item in enumerate(raw[:3]):
            try:
                specs.append(ScenarioSpec(id=f"s{i + 1}", label=str(item.get("label") or f"Scenario {i + 1}")[:120],
                                          changes=ScenarioChanges(**(item.get("changes") or {}))))
            except Exception as exc:  # noqa: BLE001 — a malformed lever must not crash the run
                self.ctx.notes.append(f"Ignored a malformed scenario: {exc}")
        specs = [s for s in specs if s.changes.model_dump(exclude_defaults=True)]
        if specs:
            return specs
        # No explicit levers ("compare outcomes", "what if things were different"): show the appeal-type comparison,
        # which is the one lever that genuinely moves this model.
        others = [("state_appeal", "If the State were the appellant"), ("accused_appeal", "If the accused were the appellant")]
        return [ScenarioSpec(id=f"s{i + 1}", label=label, changes=ScenarioChanges(appellant_type=a))  # type: ignore[arg-type]
                for i, (a, label) in enumerate(o for o in others if o[0] != appellant)] or [
            ScenarioSpec(id="s1", label="If the appeal type were not specified", changes=ScenarioChanges(appellant_type="unclear"))]

    async def ask(self, origin: str, question: str) -> List[Dict[str, Any]]:
        ctx = self.ctx
        ws = self._require_case()
        started = time.perf_counter()

        async def compute() -> Tuple[Any, bool]:
            from services.agent import doc_index
            index = await ws.ensure_doc_index()
            return await doc_index.retrieve(index, question, top_k=5), False

        excerpts, step_id = await self._step("ask_case", origin, compute, args_preview={"question": question[:120]},
                                             summarize=lambda e: f"{len(e)} passages", card=True)
        will_generate = ctx.llm is not None and ctx.request.options.narrate == "llm"
        card = cards.sources_card(cards.new_id("card"), question, excerpts, method="generated" if will_generate else "extractive")
        self.emit_card(card, step_id)
        self._artifact("excerpts", artifact_key("excerpts", ws.sha, question), card.card_id, implicit=False)
        ctx.notes.append("ask")
        return excerpts


# ---------------------------------------------------------------------------

def ws_shown(ws: CaseWorkspace) -> set:
    shown = getattr(ws, "_shown", None)
    if shown is None:
        shown = set()
        ws._shown = shown  # type: ignore[attr-defined]
    return shown


async def _profile_value(text: str, override: Optional[StructuredCaseProfile]) -> Tuple[StructuredCaseProfile, ExtractionQuality]:
    profile = override or await extract_profile(text)
    return profile, assess_quality(profile)
