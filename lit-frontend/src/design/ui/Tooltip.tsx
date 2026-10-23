import * as RadixTooltip from '@radix-ui/react-tooltip'
import type { ReactNode } from 'react'

export const TooltipProvider = RadixTooltip.Provider

export function Tooltip({ label, children, side = 'top' }: { label: ReactNode; children: ReactNode; side?: 'top' | 'right' | 'bottom' | 'left' }) {
  return (
    <RadixTooltip.Provider delayDuration={350} skipDelayDuration={200}>
      <RadixTooltip.Root>
      <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
      <RadixTooltip.Portal>
        <RadixTooltip.Content side={side} sideOffset={6} className="z-50 max-w-xs rounded-md bg-ink px-2.5 py-1.5 text-xs text-bg shadow-float animate-in fade-in-0">
          {label}
        </RadixTooltip.Content>
      </RadixTooltip.Portal>
      </RadixTooltip.Root>
    </RadixTooltip.Provider>
  )
}
