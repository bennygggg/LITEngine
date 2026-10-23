import { ClipboardList, FileText, Gauge, GitBranch, MessageSquareText, Scale, SlidersHorizontal, type LucideIcon } from 'lucide-react'
import type { ToolName } from '@/types/agent'

export interface ToolSpec {
  name: ToolName
  label: string
  description: string
  icon: LucideIcon
  needsCase: boolean
  /** The tool is meaningless without the user typing something (a question). */
  needsText?: boolean
  /** What the text typed next to the chip means for this tool. */
  hint?: string
}

/** The `+` menu and `/` command list. Order is the order a matter is usually worked in. */
export const TOOLS: ToolSpec[] = [
  { name: 'extract_case_facts', label: 'Read the case', description: 'Parties, court, issues, statutes and key facts', icon: FileText, needsCase: true },
  { name: 'search_precedents', label: 'Find precedents', description: 'Closest judgments in the library', icon: Scale, needsCase: false, hint: 'Type what to search for, or leave blank to use the case’s issues' },
  { name: 'build_argument_map', label: 'Map the argument', description: 'How claims, evidence and law connect', icon: GitBranch, needsCase: true },
  { name: 'assess_outcome', label: 'Assess the outcome', description: 'An indicative estimate and what drives it', icon: Gauge, needsCase: true },
  { name: 'run_scenario', label: 'Explore scenarios', description: 'How the estimate moves if an input changes', icon: SlidersHorizontal, needsCase: true, hint: 'Optional: describe a change, e.g. “if the State were the appellant”' },
  { name: 'ask_case', label: 'Ask about the case', description: 'Answers with the passages that support them', icon: MessageSquareText, needsCase: true, needsText: true, hint: 'Type your question about the document' },
  { name: 'full_review', label: 'Full case review', description: 'Facts, precedents, map and estimate in one go', icon: ClipboardList, needsCase: true },
]

export const toolByName = (n: ToolName) => TOOLS.find((t) => t.name === n)
