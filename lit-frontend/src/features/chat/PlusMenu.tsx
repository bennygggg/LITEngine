import { FolderOpen, Paperclip, Plus } from 'lucide-react'
import { Button } from '@/design/ui/Button'
import { Menu, MenuContent, MenuGroup, MenuItem, MenuLabel, MenuSeparator, MenuTrigger } from '@/design/ui/Menu'
import { Tooltip } from '@/design/ui/Tooltip'
import type { ToolName } from '@/types/agent'
import { TOOLS } from './tools'

export interface PlusMenuProps {
  hasCase: boolean
  disabled?: boolean
  onAddCase: () => void
  onChooseCase: () => void
  onPickTool: (tool: ToolName) => void
  open?: boolean
  onOpenChange?: (open: boolean) => void
}

export function PlusMenu({ hasCase, disabled, onAddCase, onChooseCase, onPickTool, open, onOpenChange }: PlusMenuProps) {
  return (
    <Menu open={open} onOpenChange={onOpenChange}>
      <Tooltip label="Add a matter or pick a tool">
        <MenuTrigger asChild>
          <Button variant="ghost" size="icon" aria-label="Add a matter or pick a tool" disabled={disabled} className="rounded-full border border-border-strong"><Plus /></Button>
        </MenuTrigger>
      </Tooltip>
      <MenuContent align="start" side="top" className="w-80">
        <MenuLabel>Matter</MenuLabel>
        <MenuItem onSelect={onAddCase}>
          <Paperclip className="mt-0.5 size-4 text-ink-muted" />
          <span><span className="block font-medium">Add a case…</span><span className="block text-xs text-ink-muted">Upload a judgment, paste text, or pick a sample</span></span>
        </MenuItem>
        <MenuItem onSelect={onChooseCase}>
          <FolderOpen className="mt-0.5 size-4 text-ink-muted" />
          <span><span className="block font-medium">Choose from my matters</span><span className="block text-xs text-ink-muted">Reopen something you added before</span></span>
        </MenuItem>
        <MenuSeparator />
        <MenuGroup>
          <MenuLabel>Tools</MenuLabel>
          {TOOLS.map((t) => {
            const blocked = t.needsCase && !hasCase
            return (
              <MenuItem key={t.name} disabled={blocked} onSelect={() => onPickTool(t.name)}>
                <t.icon className="mt-0.5 size-4 text-ink-muted" />
                <span>
                  <span className="block font-medium">{t.label}</span>
                  <span className="block text-xs text-ink-muted">{blocked ? 'Add a case first' : t.description}</span>
                </span>
              </MenuItem>
            )
          })}
        </MenuGroup>
      </MenuContent>
    </Menu>
  )
}
