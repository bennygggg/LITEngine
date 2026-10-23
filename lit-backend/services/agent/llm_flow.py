"""LLM-driven parts of a run: the planner (what to do with a request the rules can't place) and the narrator."""

from typing import Any, List, Optional

from config import get_settings
from models.agent_schemas import CardEvent, ErrorEvent
from services.agent import narration, prompts
from services.agent.llm.base import Finish, LLMUnavailable, Message, TextDelta, ToolCall
from services.agent.llm_runtime import stream_with_fallback
from services.agent.sanitize import StreamSanitizer, one_sentence
from services.agent.routing import PlannedTool
from services.agent.tools import RunContext, Tools
from utils.logger import get_logger

logger = get_logger(__name__)

MAX_TOOLS = 3
HISTORY_TURNS = 6
HISTORY_CLIP = 1500


def models_for(kind: str) -> List[str]:
    s = get_settings()
    return [s.PLANNER_MODEL if kind == "plan" else s.NARRATION_MODEL, s.FALLBACK_MODEL]


def history_messages(ctx: RunContext) -> List[Message]:
    turns = ctx.request.messages[-HISTORY_TURNS:]
    return [Message(m.role, m.content[:HISTORY_CLIP]) for m in turns]


def user_intent(ctx: RunContext) -> str:
    um = ctx.request.user_message
    if um.text.strip():
        return um.text.strip()
    if um.input_response:
        return "[The user submitted the form with the details you asked for.]"
    if um.forced_tool:
        extra = f" (query: {um.forced_tool.args['query']})" if um.forced_tool.args.get("query") else ""
        return f"[The user picked the “{um.forced_tool.name}” tool from the menu{extra}.]"
    return "[no message]"


def _sanitise_args(name: str, args: dict) -> dict:
    out = dict(args or {})
    if name == "search_precedents":
        if out.get("query"):
            out["query"] = str(out["query"])[:400]
        if out.get("top_k") is not None:
            try:
                out["top_k"] = max(1, min(8, int(out["top_k"])))
            except (TypeError, ValueError):
                out.pop("top_k", None)
    if name == "ask_case":
        out["question"] = str(out.get("question") or "")[:500]
    return out


async def plan(ctx: RunContext, tools: Tools) -> tuple:
    """Ask the planner model what to do. Returns (planned_tools, answered_directly).

    Text the model streams before/instead of a tool call is shown as it arrives (a direct answer or a short preamble)."""
    usage = ctx.usage
    messages = [Message("system", prompts.SYSTEM_PROMPT), *history_messages(ctx),
                Message("user", f"{user_intent(ctx)}\n\n{prompts.case_state(ctx)}")]
    planned: List[PlannedTool] = []
    streamed = False
    held: List[str] = []   # one-liner mode: hold text back; a preamble is dropped, a direct answer is cut to one sentence
    clean = StreamSanitizer(prompts.issued_refs(ctx))
    try:
        async for ev in stream_with_fallback(ctx.llm, models_for("plan"), messages, usage, tools=prompts.TOOLS, max_tokens=800, temperature=0.1):
            if isinstance(ev, TextDelta):
                out = clean.feed(ev.text)
                if out and ctx.brief:
                    held.append(out)
                elif out:
                    tools.stream_text(out)
                    streamed = True
            elif isinstance(ev, ToolCall) and ev.name in prompts.TOOL_NAMES and len(planned) < MAX_TOOLS:
                planned.append(PlannedTool(ev.name, _sanitise_args(ev.name, ev.arguments), "llm"))  # type: ignore[arg-type]
    except LLMUnavailable as exc:
        tools.end_text()
        ctx.log.emit(ErrorEvent, code="llm_unavailable", message="The AI assistant is unavailable right now, so I'm working without it.",
                     scope="llm", retryable=True)
        logger.warning(f"planner unavailable: {exc}")
        return None, False
    tail = clean.flush()
    if tail and ctx.brief:
        held.append(tail)
    elif tail:
        tools.stream_text(tail)
        streamed = True
    if ctx.brief and held and not planned:
        line = one_sentence("".join(held))
        if line:
            tools.stream_text(line)
            streamed = True
    tools.end_text()
    return planned, (streamed and not planned)


async def narrate(ctx: RunContext, tools: Tools) -> bool:
    """Stream the closing narration. Returns False (after telling the client) if the LLM could not produce it."""
    summary = prompts.summarize_run(ctx)
    messages = [
        Message("system", prompts.SYSTEM_PROMPT), *history_messages(ctx),
        Message("user", f"{user_intent(ctx)}\n\n{prompts.case_state(ctx)}\n\n<tool_results>\n{summary}\n</tool_results>\n\n"
                        + (prompts.ONE_LINE_INSTRUCTION if ctx.brief else
                           prompts.NARRATION_INSTRUCTION + (f"\nPer-result guidance:\n{prompts.narration_hints(ctx)}" if ctx.emitted_cards else ""))),
    ]
    text_parts: List[str] = []
    clean = StreamSanitizer(prompts.issued_refs(ctx))
    try:
        max_tokens = min(get_settings().AGENT_MAX_TOKENS, 600) if ctx.brief else get_settings().AGENT_MAX_TOKENS
        async for ev in stream_with_fallback(ctx.llm, models_for("narrate"), messages, ctx.usage, max_tokens=max_tokens, temperature=0.3):
            if isinstance(ev, TextDelta):
                out = clean.feed(ev.text)
                if out:
                    if not ctx.brief:        # a one-liner is held back so it can be cut to one sentence before the user sees it
                        tools.stream_text(out)
                    text_parts.append(out)
    except LLMUnavailable as exc:
        tools.end_text()
        ctx.narration_failed = True
        ctx.log.emit(ErrorEvent, code="llm_unavailable", message="The AI narration is unavailable, so this summary is templated.",
                     scope="llm", retryable=True)
        logger.warning(f"narration unavailable: {exc}")
        return False
    tail = clean.flush()
    if tail:
        if not ctx.brief:
            tools.stream_text(tail)
        text_parts.append(tail)
    if ctx.brief:
        line = one_sentence("".join(text_parts))
        text_parts = [line] if line else []
        if line:
            tools.stream_text(line)
    tools.end_text()
    full = "".join(text_parts)
    if clean.dropped:  # already removed from the stream; recorded so a regression in the prompt shows up in evals
        ctx.warnings.append(f"dropped citation handles no tool issued: {', '.join(sorted(set(clean.dropped)))}")
    if not full.strip():
        return False
    return True


def correct_sources_label(ctx: RunContext, tools: Tools) -> None:
    """If the LLM was supposed to answer from the passages but could not, relabel the Sources card as extractive."""
    for card in ctx.emitted_cards:
        if card.type == "sources" and card.method == "generated":
            fixed = card.model_copy(update={"method": "extractive"})
            ctx.log.emit(CardEvent, card_id=fixed.card_id, part_id=ctx.next_part(), supersedes=card.card_id, payload=fixed)
