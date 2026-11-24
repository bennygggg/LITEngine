"""
Wire contract for the LIT chat agent (schema version 1).

Three families, all pydantic v2:
  1. Requests     — POST /api/v1/agent/chat, PUT /api/v1/cases/{sha256}
  2. Cards        — the rich payloads rendered inline in the conversation (discriminated on `type`)
  3. Events       — the SSE stream (discriminated on `event`); every event carries {v, seq, t}

The TypeScript types in lit-frontend/src/api/schema.d.ts are generated from this file via OpenAPI
(scripts/export_openapi.py -> openapi-typescript), so changing anything here is a contract change:
bump SCHEMA_VERSION for breaking changes and keep unknown-event tolerance on the client.

Honesty rules baked into the shapes (see plan §4.5): precedents expose `cosine` + `band` (never a percent
"match"); the outcome card carries signed *centred* contributions, the model card facts and explicit caveats;
the scenario card carries an effect class so negligible effects are stated, not hidden.
"""

from datetime import date
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

from models.schemas import GraphBuildResponse, StructuredCaseProfile

SCHEMA_VERSION = 1

AppellantType = Literal["accused_appeal", "state_appeal", "unclear"]
ToolName = Literal[
    "extract_case_facts",
    "search_precedents",
    "build_argument_map",
    "assess_outcome",
    "run_scenario",
    "ask_case",
    "inspect_artifact",
    "full_review",  # macro: facts -> precedents -> map -> outcome (forced path only)
]
ArtifactKind = Literal["profile", "precedents", "graph", "outcome", "scenario", "excerpts"]


# ---------------------------------------------------------------------------
# 1. Requests
# ---------------------------------------------------------------------------

class ClientInfo(BaseModel):
    version: str = Field(..., description="Client app version, e.g. 1.0.0")
    schema_version: int = Field(SCHEMA_VERSION, description="Wire schema the client understands")


class ChatTurn(BaseModel):
    """Prior turns are text only — cards are re-described to the model by the server, never replayed."""
    role: Literal["user", "assistant"]  # validated: a client cannot inject `system` turns
    content: str = Field(..., max_length=8000)


class ForcedTool(BaseModel):
    name: ToolName
    args: Dict[str, Any] = Field(default_factory=dict)


class InputResponse(BaseModel):
    """The user's answer to a NeedsInputCard; starts a new run on the forced path."""
    card_id: str
    values: Dict[str, str] = Field(default_factory=dict)
    pending: Optional[ForcedTool] = None


class UserMessage(BaseModel):
    text: str = Field("", max_length=4000)
    forced_tool: Optional[ForcedTool] = Field(None, description="Set when the user picked a tool from the + menu or a slash command")
    input_response: Optional[InputResponse] = None


class CaseInputs(BaseModel):
    appellant_type: Optional[AppellantType] = Field(None, description="Direct user input, never inferred from case text")
    filing_date: Optional[date] = Field(None, description="Used as the precedent cutoff (decided strictly before)")


class CaseRef(BaseModel):
    ref: str = Field(..., min_length=64, max_length=64, description="sha256 of the case text (already PUT to /cases/{sha256})")
    title: str = Field("", max_length=300)
    inputs: CaseInputs = Field(default_factory=CaseInputs)
    profile_override: Optional[StructuredCaseProfile] = Field(None, description="Set only if the user edited the profile")


class AgentOptions(BaseModel):
    mode: Literal["auto", "deterministic"] = "auto"
    narrate: Literal["llm", "template", "none"] = "llm"


class AgentChatRequest(BaseModel):
    client: ClientInfo
    conversation_id: str
    run_id: str = Field(..., description="Client-generated id; re-POSTing the same run_id with Last-Event-ID resumes")
    retry_of: Optional[str] = None
    messages: List[ChatTurn] = Field(default_factory=list, max_length=12)
    user_message: UserMessage
    case: Optional[CaseRef] = None
    options: AgentOptions = Field(default_factory=AgentOptions)


class CasePutRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2_000_000)
    title: Optional[str] = Field(None, max_length=300)
    filename: Optional[str] = Field(None, max_length=255)


class DetectedCase(BaseModel):
    petitioner: Optional[str] = None
    respondent: Optional[str] = None
    court_level: Optional[str] = None
    sections: List[str] = Field(default_factory=list)


class ExtractionQuality(BaseModel):
    method: Literal["rules", "hybrid", "model", "llm_assisted"]
    quality: Literal["good", "partial", "poor"]
    completeness: float = Field(..., ge=0.0, le=1.0, description="Computed from which fields were found — replaces the constant metadata.confidence")
    missing: List[str] = Field(default_factory=list)


class CasePreview(BaseModel):
    ref: str
    known: bool = True
    word_count: int
    detected: DetectedCase
    extraction: ExtractionQuality


# ---------------------------------------------------------------------------
# 2. Cards
# ---------------------------------------------------------------------------

class Provenance(BaseModel):
    engine: str = Field(..., description="Which engine produced this (e.g. 'rules', 'faiss-minilm', 'juris')")
    engine_version: str
    index_version: Optional[str] = None
    computed_ms: int = 0
    inputs: Dict[str, Any] = Field(default_factory=dict)
    cached: bool = False


class Disclaimer(BaseModel):
    level: Literal["info", "caution"] = "info"
    text: str


class CardBase(BaseModel):
    card_id: str
    schema_ver: int = SCHEMA_VERSION
    title: str
    subtitle: Optional[str] = None
    artifact_key: Optional[str] = None
    provenance: Optional[Provenance] = None
    disclaimer: Optional[Disclaimer] = None


class CaseProfileCard(CardBase):
    type: Literal["case_profile"] = "case_profile"
    profile: StructuredCaseProfile
    extraction: ExtractionQuality
    inputs: CaseInputs = Field(default_factory=CaseInputs)


class PrecedentHit(BaseModel):
    ref: str = Field(..., description="Citation handle the model and UI share: P1, P2, ...")
    doc_id: str
    title: str
    court: Optional[str] = None
    court_tier: Literal["SC", "HC", "other"] = "other"
    date: Optional[str] = None
    url: str
    snippet: Optional[str] = Field(None, description="<= 300 chars; the full judgment stays at the source")
    cosine: float = Field(..., description="True cosine similarity. NOT a probability of relevance and never shown as a percent")
    band: Literal["close", "related", "loose", "unranked"] = "unranked"
    matched_statutes: List[str] = Field(default_factory=list)
    source: str = "faiss"


class PrecedentFilter(BaseModel):
    before_date: Optional[date] = None
    undated_excluded: int = 0


class IndexInfo(BaseModel):
    name: str
    version: str
    docs: int
    chunks: int


class PrecedentsCard(CardBase):
    type: Literal["precedents"] = "precedents"
    query: str
    query_source: Literal["user", "issues", "combined"] = "issues"
    filter: PrecedentFilter = Field(default_factory=PrecedentFilter)
    index: IndexInfo
    results: List[PrecedentHit]
    used_for_graph: List[str] = Field(default_factory=list, description="Refs of the precedents (max 3) placed on the map")


class GraphSummary(BaseModel):
    issues: int = 0
    claims: int = 0
    evidence: int = 0
    statutes: int = 0
    precedents: int = 0
    weak_claims: int = 0
    edge_types: List[str] = Field(default_factory=list, description="Only the edge types that actually occur")


class ArgumentMapCard(CardBase):
    type: Literal["argument_map"] = "argument_map"
    graph: GraphBuildResponse
    summary: GraphSummary
    notes: List[str] = Field(default_factory=list)


class OutcomeEstimate(BaseModel):
    p_succeeds: float = Field(..., ge=0.0, le=1.0)
    p_rounded: int = Field(..., ge=0, le=100, description="Rounded to the nearest 5; this is the figure shown and quoted")
    tier: Literal["favorable", "uncertain", "unfavorable"]
    tier_label: str = Field(..., description="Plain wording shown first, e.g. 'Below even odds'")
    definition: str = Field("Chance of any appellate relief, including partial relief")


class OutcomeInputs(BaseModel):
    appellant_type: AppellantType
    filing_date: Optional[date] = None
    appellant_source: Literal["user_input", "form"] = "user_input"


class ModelFacts(BaseModel):
    name: str
    version: Optional[str] = None
    loaded: bool = True
    n_train: Optional[int] = None
    eval_accuracy: Optional[float] = Field(None, description="Accuracy on held-out cases decided after the training period")
    eval_auc: Optional[float] = None
    n_eval: Optional[int] = None
    eval_period: Optional[str] = Field(None, description="Decision years of the held-out cases, e.g. '2023-2025'")
    baseline_accuracy: Optional[float] = Field(None, description="Accuracy of always guessing the more common outcome on the same cases")
    reads: Optional[str] = Field(None, description="What the model reads, in plain words")
    scope: str = "Criminal appeals"


class OutcomeContribution(BaseModel):
    feature: str
    display_name: str
    value: float
    contribution: float = Field(..., description="Signed log-odds contribution, centred on a typical training case")
    explanation: str


class LegacyHeuristic(BaseModel):
    p: float
    note: str = "Uncalibrated rule score; it predicted 'succeeds' for every training case"


class OutcomeCard(CardBase):
    type: Literal["outcome"] = "outcome"
    estimate: OutcomeEstimate
    inputs: OutcomeInputs
    model: ModelFacts
    contributions: List[OutcomeContribution] = Field(default_factory=list)
    drivers_summary: str = ""
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    legacy: Optional[LegacyHeuristic] = None
    caveats: List[str] = Field(default_factory=list)
    profile_method: Optional[str] = Field(None, description="Extraction method behind the inputs (rule-extracted profiles match training)")


class AppliedLever(BaseModel):
    lever: str
    value: Any = None
    status: Literal["applied", "clamped", "rejected"]
    note: Optional[str] = None


class FeatureDelta(BaseModel):
    feature: str
    display_name: str
    from_value: Any = None
    to_value: Any = None
    logit_delta: float
    share_of_change: float = Field(..., ge=0.0, le=1.0)


class ScenarioOutcome(BaseModel):
    id: str
    label: str
    applied: List[AppliedLever] = Field(default_factory=list)
    p_succeeds: float
    delta_pp: float
    feature_deltas: List[FeatureDelta] = Field(default_factory=list)
    dominant_feature: Optional[str] = None
    effect_class: Literal["large", "small", "negligible"]
    warnings: List[str] = Field(default_factory=list)


class SensitivityRow(BaseModel):
    feature: str
    display_name: str
    p_at_low: float
    p_at_high: float
    swing_pp: float
    kind: Literal["categorical", "continuous"]
    confounded: bool = False
    note: Optional[str] = None


class ScenarioBase(BaseModel):
    p_succeeds: float
    appellant_type: AppellantType
    features: Dict[str, float] = Field(default_factory=dict)


class ScenarioChanges(BaseModel):
    """Levers a user can pull. Each maps onto a real input of the outcome model (see services/scenario.py)."""
    appellant_type: Optional[AppellantType] = None
    resolved_weak_claim_ids: List[str] = Field(default_factory=list, description="Node ids to treat as now supported; only meaningful if the map has weak claims")
    extra_supporting_facts: int = Field(0, ge=0, le=5)
    add_sections: List[str] = Field(default_factory=list, max_length=6)
    remove_sections: List[str] = Field(default_factory=list, max_length=12)
    exclude_precedent_refs: List[str] = Field(default_factory=list, description="P1..Pn: drop these precedents from the support set")
    court_level: Optional[Literal["Supreme Court", "High Court", "District Court"]] = None


class ScenarioSpec(BaseModel):
    id: str = ""
    label: str = Field(..., max_length=120)
    changes: ScenarioChanges


class ScenarioRequest(BaseModel):
    case_profile: StructuredCaseProfile
    precedents: List[Dict[str, Any]] = Field(default_factory=list, max_length=10, description="SearchResult-shaped; P1..Pn refer to this order")
    graph_stats: Optional[Dict[str, Any]] = None
    appellant_type: AppellantType = "unclear"
    case_text: Optional[str] = Field(None, max_length=2_000_000, description="The case document Juris reads; if omitted, a thin summary of the profile is used")
    scenarios: List[ScenarioSpec] = Field(..., min_length=1, max_length=5)
    include_sensitivity: bool = True


class ScenarioResponse(BaseModel):
    model: ModelFacts
    base: ScenarioBase
    scenarios: List[ScenarioOutcome]
    sensitivity: List[SensitivityRow] = Field(default_factory=list)


class ScenarioCard(CardBase):
    type: Literal["scenario"] = "scenario"
    model: ModelFacts
    base: ScenarioBase
    scenarios: List[ScenarioOutcome]
    sensitivity: List[SensitivityRow] = Field(default_factory=list)


class Excerpt(BaseModel):
    ref: str = Field(..., description="S1, S2, ...")
    text: str
    cosine: float
    chunk_index: int
    char_start: Optional[int] = Field(None, description="Offsets into the case text, for the source viewer")
    char_end: Optional[int] = None


class SourcesCard(CardBase):
    type: Literal["sources"] = "sources"
    question: str
    excerpts: List[Excerpt]
    method: Literal["generated", "extractive"] = "generated"
    coverage: Optional[str] = None


class InputOption(BaseModel):
    value: str
    label: str


class InputField(BaseModel):
    name: Literal["appellant_type", "filing_date"]
    kind: Literal["select", "date"]
    label: str
    options: List[InputOption] = Field(default_factory=list)
    required: bool = True
    default: Optional[str] = None


class NeedsInputCard(CardBase):
    type: Literal["needs_input"] = "needs_input"
    reason: str
    pending: ForcedTool
    fields: List[InputField]
    hint: Optional[str] = None


class DocumentCard(CardBase):
    type: Literal["document"] = "document"
    case_id: str
    filename: Optional[str] = None
    word_count: int
    pages: Optional[int] = None
    source: Literal["sample", "upload", "paste"]
    preview: str = ""
    extraction: Optional[ExtractionQuality] = None


class ErrorCard(CardBase):
    type: Literal["error"] = "error"
    code: str
    message: str
    retryable: bool = False
    retry: Optional[ForcedTool] = None
    technical: Optional[str] = Field(None, description="Collapsible detail; never contains case content")


Card = Annotated[
    Union[
        CaseProfileCard, PrecedentsCard, ArgumentMapCard, OutcomeCard, ScenarioCard,
        SourcesCard, NeedsInputCard, DocumentCard, ErrorCard,
    ],
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# 3. Events (SSE). `event` is the SSE event name AND a field in the JSON, so a
#    recorded stream is self-describing and the client reducer needs one type.
# ---------------------------------------------------------------------------

class EventBase(BaseModel):
    v: int = 1
    seq: int = Field(..., description="Strictly increasing within a run; used for Last-Event-ID resume")
    t: int = Field(0, description="Milliseconds since the request was received")


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    llm_calls: int = 0


class Timings(BaseModel):
    ttft_ms: Optional[int] = None
    first_card_ms: Optional[int] = None
    total_ms: int = 0


class MessageStartEvent(EventBase):
    event: Literal["message_start"] = "message_start"
    run_id: str
    message_id: str
    conversation_id: str
    mode: Literal["llm", "forced", "deterministic"]
    model: Optional[str] = None
    prompt_version: Optional[str] = None
    schema_version: int = SCHEMA_VERSION
    server_version: str
    case_known: bool = True
    answer_first: bool = Field(False, description="The user asked for a short answer: the client shows the text before any cards")


class TextDeltaEvent(EventBase):
    event: Literal["text_delta"] = "text_delta"
    message_id: str
    part_id: str = Field(..., description="A new part_id starts a new text part; there is no explicit end")
    delta: str


class StepEvent(EventBase):
    event: Literal["step"] = "step"
    step_id: str
    phase: Literal["start", "progress", "end"]
    tool: ToolName
    label: str
    origin: Literal["llm", "forced", "dependency"] = "forced"
    depends_on: List[str] = Field(default_factory=list)
    args_preview: Dict[str, Any] = Field(default_factory=dict)
    produces_card: bool = Field(False, description="On `start`: a card event for this step will follow — lets the UI show a skeleton in the card's final shape")
    message: Optional[str] = None
    pct: Optional[float] = None
    status: Optional[Literal["ok", "cached", "skipped", "error"]] = None
    duration_ms: Optional[int] = None
    summary: Optional[str] = None


class CardEvent(EventBase):
    event: Literal["card"] = "card"
    card_id: str
    part_id: str
    step_id: Optional[str] = None
    schema_ver: int = SCHEMA_VERSION
    supersedes: Optional[str] = None
    payload: Card


class NeedsInputEvent(EventBase):
    event: Literal["needs_input"] = "needs_input"
    card_id: str
    part_id: str
    payload: NeedsInputCard


class ArtifactUpdateEvent(EventBase):
    event: Literal["artifact_update"] = "artifact_update"
    kind: ArtifactKind
    key: str
    card_id: Optional[str] = None
    implicit: bool = False


class Suggestion(BaseModel):
    label: str
    prompt: str
    forced_tool: Optional[ForcedTool] = None


class MetaEvent(EventBase):
    event: Literal["meta"] = "meta"
    conversation_title: Optional[str] = None
    suggestions: List[Suggestion] = Field(default_factory=list)
    case_inputs: Optional[CaseInputs] = Field(
        None, description="Effective appellant_type/filing_date after this run (from the form or an explicit user statement); the client persists them on the case")


class PingEvent(EventBase):
    event: Literal["ping"] = "ping"
    warm: bool = True


class ErrorEvent(EventBase):
    event: Literal["error"] = "error"
    code: str
    message: str
    scope: Literal["run", "step", "llm"] = "run"
    step_id: Optional[str] = None
    retryable: bool = False
    http_status: Optional[int] = None


class DoneEvent(EventBase):
    event: Literal["done"] = "done"
    status: Literal["complete", "awaiting_input", "cancelled", "error"]
    message_id: str
    usage: Usage = Field(default_factory=Usage)
    timings: Timings = Field(default_factory=Timings)
    warnings: List[str] = Field(default_factory=list, description="e.g. citation refs the model used that no tool issued")


AgentEvent = Annotated[
    Union[
        MessageStartEvent, TextDeltaEvent, StepEvent, CardEvent, NeedsInputEvent,
        ArtifactUpdateEvent, MetaEvent, PingEvent, ErrorEvent, DoneEvent,
    ],
    Field(discriminator="event"),
]


class AgentSchemaBundle(BaseModel):
    """Carrier model: registering this on a route puts every card and event variant into the OpenAPI
    components so openapi-typescript can generate the client types. Not used at runtime."""
    schema_version: int = SCHEMA_VERSION
    request: AgentChatRequest
    card: Card
    event: AgentEvent
    case_preview: CasePreview
