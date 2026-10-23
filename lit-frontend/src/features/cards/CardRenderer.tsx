import { CardShell } from '@/design/ui/CardShell'
import type { Card } from '@/types/agent'
import { ArgumentMapCardView } from './ArgumentMapCard'
import { CaseProfileCardView } from './CaseProfileCard'
import { ErrorCardView } from './ErrorCard'
import { OutcomeCardView } from './OutcomeCard'
import { PrecedentsCardView } from './PrecedentsCard'
import { ScenarioCardView } from './ScenarioCard'
import { SourcesCardView } from './SourcesCard'
import { CardSkeleton } from './CardSkeleton'
import type { CardPart } from '@/features/chat/model'

/** Registry: card type -> view. Unknown types (a newer server) degrade to a plain card instead of crashing. */
export function CardRenderer({ part }: { part: CardPart }) {
  const card = part.payload
  if (!card) return <CardSkeleton type={part.type} />
  switch (card.type) {
    case 'case_profile': return <CaseProfileCardView card={card} />
    case 'precedents': return <PrecedentsCardView card={card} />
    case 'argument_map': return <ArgumentMapCardView card={card} />
    case 'outcome': return <OutcomeCardView card={card} />
    case 'scenario': return <ScenarioCardView card={card} />
    case 'sources': return <SourcesCardView card={card} />
    case 'error':
      return <ErrorCardView card={card} />
    default:
      return <GenericCard card={card} />
  }
}

function GenericCard({ card }: { card: Card }) {
  return (
    <CardShell eyebrow={card.type.replace('_', ' ')} title={card.title} subtitle={card.subtitle ?? undefined} disclaimer={card.disclaimer ?? undefined}>
      <p className="text-sm text-ink-muted">This card type is not available in this version of the app.</p>
    </CardShell>
  )
}
