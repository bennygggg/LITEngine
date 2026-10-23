import type { components } from '@/api/schema'

type S = components['schemas']

export type CaseInputs = S['CaseInputs']
export type AppellantType = NonNullable<CaseInputs['appellant_type']>
export type ForcedTool = S['ForcedTool']
export type ToolName = ForcedTool['name']
export type Suggestion = S['Suggestion']
export type ExtractionQuality = S['ExtractionQuality']
export type CasePreview = S['CasePreview']

export type CaseProfileCard = S['CaseProfileCard']
export type PrecedentsCard = S['PrecedentsCard']
export type PrecedentHit = S['PrecedentHit']
export type ArgumentMapCard = S['ArgumentMapCard']
export type OutcomeCard = S['OutcomeCard']
export type ScenarioCard = S['ScenarioCard']
export type SourcesCard = S['SourcesCard']
export type NeedsInputCard = S['NeedsInputCard']
export type DocumentCard = S['DocumentCard']
export type ErrorCard = S['ErrorCard']

export type Card =
  | CaseProfileCard
  | PrecedentsCard
  | ArgumentMapCard
  | OutcomeCard
  | ScenarioCard
  | SourcesCard
  | NeedsInputCard
  | DocumentCard
  | ErrorCard
export type CardType = Card['type']

export type MessageStartEvent = S['MessageStartEvent']
export type TextDeltaEvent = S['TextDeltaEvent']
export type StepEvent = S['StepEvent']
export type CardEvent = S['CardEvent']
export type NeedsInputEvent = S['NeedsInputEvent']
export type ArtifactUpdateEvent = S['ArtifactUpdateEvent']
export type MetaEvent = S['MetaEvent']
export type PingEvent = S['PingEvent']
export type ErrorEvent = S['ErrorEvent']
export type DoneEvent = S['DoneEvent']

export type AgentEvent =
  | MessageStartEvent
  | TextDeltaEvent
  | StepEvent
  | CardEvent
  | NeedsInputEvent
  | ArtifactUpdateEvent
  | MetaEvent
  | PingEvent
  | ErrorEvent
  | DoneEvent

export type AgentChatRequest = S['AgentChatRequest-Input']

/** Which card a tool's step will produce — used to draw a skeleton in the card's final shape. */
export const TOOL_CARD: Partial<Record<ToolName, CardType>> = {
  extract_case_facts: 'case_profile',
  search_precedents: 'precedents',
  build_argument_map: 'argument_map',
  assess_outcome: 'outcome',
  run_scenario: 'scenario',
  ask_case: 'sources',
}
