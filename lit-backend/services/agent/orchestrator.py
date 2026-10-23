"""
The orchestrator: one run = plan -> execute tools (with dependencies) -> narrate -> done.

Phase 1 is fully deterministic (forced tools, the Tier-1 router, templated narration). The LLM hooks (`_plan_llm`,
`_narrate_llm`) are the Phase 2 extension points; with no LLM configured everything below is the whole product.
"""

import asyncio
from typing import List, Optional

from config import get_settings
from models.agent_schemas import (
    AgentChatRequest, CaseInputs, DoneEvent, ErrorEvent, MessageStartEvent, MetaEvent, StepEvent, Suggestion, Timings, ForcedTool, Usage,
)
from services.agent import cards, llm_flow, narration, prompts
from services.agent.llm.factory import get_llm
from services.agent.events import RunLog
from services.agent.routing import PlannedTool, Route, parse_scenario_levers, route, scenario_specs
from services.agent.tools import AwaitingInput, RunContext, ToolError, Tools
from services.agent.workspace import CaseWorkspace
from utils.logger import get_logger

logger = get_logger(__name__)

NEEDS_CASE = {"extract_case_facts", "build_argument_map", "assess_outcome", "run_scenario", "ask_case", "full_review"}


def _merge_form_values(inputs: CaseInputs, values: dict) -> CaseInputs:
    update = {}
    if values.get("appellant_type") in ("accused_appeal", "state_appeal", "unclear"):
        update["appellant_type"] = values["appellant_type"]
    if values.get("filing_date"):
        try:
            from datetime import date
            update["filing_date"] = date.fromisoformat(values["filing_date"][:10])
        except ValueError:
            pass
    return inputs.model_copy(update=update)


class Orchestrator:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def run(self, request: AgentChatRequest, ws: Optional[CaseWorkspace], log: RunLog) -> None:
        user_turns = [m.content for m in request.messages if m.role == "user"][-3:]
        ctx = RunContext(
            request=request, log=log, ws=ws, message_id=cards.new_id("m"),
            inputs=(request.case.inputs if request.case else CaseInputs()),
            user_text=" ".join(user_turns + [request.user_message.text]),
            llm=get_llm() if request.options.mode == "auto" else None,
        )
        status = "complete"
        try:
            await asyncio.wait_for(self._run(ctx), self.settings.AGENT_RUN_TIMEOUT_S)
        except AwaitingInput:
            status = "awaiting_input"
        except asyncio.TimeoutError:
            status = "error"
            log.emit(ErrorEvent, code="run_timeout", message="This took longer than expected and was stopped. Please try again.", scope="run", retryable=True)
        except asyncio.CancelledError:
            log.emit(DoneEvent, status="cancelled", message_id=ctx.message_id, timings=self._timings(ctx))
            log.finish()
            raise
        except Exception as exc:  # noqa: BLE001 — never let a bug become a hung stream
            status = "error"
            logger.error(f"Agent run failed: {type(exc).__name__}: {exc}")
            log.emit(ErrorEvent, code="internal_error", message="Something went wrong on our side. Please try again.", scope="run", retryable=True)
        try:
            self._emit_meta(ctx)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"meta failed: {exc}")
        log.emit(DoneEvent, status=status, message_id=ctx.message_id, timings=self._timings(ctx),
                 usage=Usage(input_tokens=ctx.usage.input_tokens, output_tokens=ctx.usage.output_tokens, llm_calls=ctx.usage.llm_calls),
                 warnings=ctx.warnings)
        log.finish()

    def _timings(self, ctx: RunContext) -> Timings:
        return Timings(ttft_ms=ctx.first_text_ms, first_card_ms=ctx.first_card_ms, total_ms=ctx.log.emitter.elapsed_ms())

    def _emit_meta(self, ctx: RunContext) -> None:
        sugg = [Suggestion(label=s["label"], prompt=s["prompt"],
                           forced_tool=ForcedTool(**s["forced_tool"]) if s.get("forced_tool") else None)
                for s in narration.suggestions(ctx)]
        original = ctx.request.case.inputs if ctx.request.case else CaseInputs()
        changed = ctx.inputs != original
        ctx.log.emit(MetaEvent, suggestions=sugg, case_inputs=ctx.inputs if changed else None)

    # ------------------------------------------------------------------ the run
    async def _run(self, ctx: RunContext) -> None:
        req, log = ctx.request, ctx.log
        um = req.user_message
        tools = Tools(ctx)
        steered = bool(um.forced_tool or um.input_response)
        mode = "forced" if steered else ("llm" if ctx.llm is not None else "deterministic")
        log.emit(MessageStartEvent, run_id=req.run_id, message_id=ctx.message_id, conversation_id=req.conversation_id,
                 mode=mode, model=(self.settings.NARRATION_MODEL if ctx.llm is not None else None),
                 prompt_version=(prompts.PROMPT_VERSION if ctx.llm is not None else None), server_version=self.settings.APP_VERSION,
                 case_known=ctx.ws is not None or req.case is None)

        planned: List[PlannedTool]
        if um.input_response:
            ctx.inputs = _merge_form_values(ctx.inputs, um.input_response.values)
            pending = um.input_response.pending
            planned = [PlannedTool(pending.name, dict(pending.args), "forced")] if pending else []
        elif um.forced_tool:
            planned = [PlannedTool(um.forced_tool.name, dict(um.forced_tool.args), "forced")]
        else:
            r: Route = route(um.text, has_case=ctx.ws is not None)
            confident = r.kind == "tools" and r.confidence >= 0.9
            answered = False
            if r.kind == "help" and ctx.llm is None:
                tools.emit_text(narration.HELP)
                return
            if confident or r.kind == "help":
                planned = r.tools
            elif ctx.llm is not None:
                # The rules can't place this with confidence — let the planner model decide (or answer directly).
                llm_plan, answered = await llm_flow.plan(ctx, tools)
                if llm_plan is None:       # LLM unavailable: fall back to the rules' best guess
                    planned = r.tools or ([PlannedTool("ask_case", {"question": um.text[:500]}, "forced")] if ctx.ws else [])
                else:
                    planned = llm_plan
            else:
                # A document question with no keyword hit ("recovery of the weapon") is still a question about the document.
                planned = r.tools or [PlannedTool("ask_case", {"question": um.text[:500]}, "forced")]
            if answered:
                return
            # explicit statements in the user's own words count as stated inputs
            for t in planned:
                tools.accept_inputs(t.args, "forced" if t.origin == "forced" else t.origin)

        if not planned:
            tools.emit_text(narration.HELP)
            return
        if any(t.name in NEEDS_CASE for t in planned) and ctx.ws is None:
            tools.emit_text(narration.NO_CASE)
            return

        text = narration.intro(planned)
        if text and um.input_response is None:
            tools.emit_text(text)

        for t in planned:
            await self._exec(ctx, tools, t)

        if req.options.narrate == "none":
            return
        if ctx.llm is not None and req.options.narrate == "llm":
            if await llm_flow.narrate(ctx, tools):
                return
            llm_flow.correct_sources_label(ctx, tools)
        out = narration.outro(ctx)  # templated narration: the no-LLM voice, and the fallback if the LLM failed
        if out:
            tools.emit_text(out)

    async def _exec(self, ctx: RunContext, tools: Tools, t: PlannedTool) -> None:
        ctx.last_tool = t.name
        origin = t.origin
        try:
            if t.name == "extract_case_facts":
                await tools.profile(origin, show=True)
            elif t.name == "search_precedents":
                await tools.precedents(origin, query=t.args.get("query"), top_k=int(t.args.get("top_k") or 5), show=True)
            elif t.name == "build_argument_map":
                await tools.graph(origin, show=True)
            elif t.name == "assess_outcome":
                await tools.outcome(origin, t.args, show=True)
            elif t.name == "run_scenario":
                if not t.args.get("scenarios") and t.args.get("text"):   # the + menu passes free text; read the levers out of it
                    levers = parse_scenario_levers(str(t.args["text"]))
                    if levers:
                        t.args = {**t.args, "scenarios": scenario_specs(levers)}
                await tools.scenario(origin, t.args)
            elif t.name == "ask_case":
                await tools.ask(origin, str(t.args.get("question") or ctx.request.user_message.text)[:500])
            elif t.name == "full_review":
                resumed = ctx.request.user_message.input_response is not None
                await tools.profile(origin, show=not resumed)  # on resume the profile card is already on screen
                tools.accept_inputs(t.args, origin)
                tools._need_inputs("full_review", t.args)
                await tools.precedents("dependency", show=True)
                await tools.graph("dependency", show=True)
                if ctx.profile and ctx.profile.case_type == "criminal":
                    await tools.outcome("dependency", t.args, show=True)
                else:
                    ctx.notes.append("outcome skipped: not a criminal appeal")
            else:
                raise ToolError("unknown_tool", f"I don't have a tool called {t.name}.")
        except ToolError as exc:
            tools.emit_card(cards.error_card(
                exc.code, exc.message, retryable=exc.retryable,
                retry=ForcedTool(name=t.name, args=t.args) if exc.retryable else None,  # type: ignore[arg-type]
                title="Outcome analysis isn't available for this matter" if exc.code == "outcome_out_of_scope" else None,
            ))
            ctx.log.emit(ErrorEvent, code=exc.code, message=exc.message, scope="step", retryable=exc.retryable)


orchestrator = Orchestrator()
