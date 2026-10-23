import * as RadixDialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import type { ComponentPropsWithoutRef, ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { Button } from './Button'

export const Dialog = RadixDialog.Root
export const DialogTrigger = RadixDialog.Trigger
export const DialogClose = RadixDialog.Close

export function DialogContent({
  className, children, title, description, wide, ...props
}: ComponentPropsWithoutRef<typeof RadixDialog.Content> & { title: string; description?: string; wide?: boolean; children: ReactNode }) {
  return (
    <RadixDialog.Portal>
      <RadixDialog.Overlay className="fixed inset-0 z-50 bg-ink/30 backdrop-blur-[2px] data-[state=open]:animate-in data-[state=open]:fade-in-0" />
      <RadixDialog.Content
        className={cn(
          'fixed left-1/2 top-1/2 z-50 flex max-h-[min(86vh,720px)] w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden',
          'rounded-2xl border border-border bg-surface shadow-float outline-none',
          'data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95',
          wide ? 'max-w-3xl' : 'max-w-lg',
          className,
        )}
        {...props}
      >
        <header className="flex items-start justify-between gap-4 border-b border-border px-6 py-4">
          <div>
            <RadixDialog.Title className="font-display text-xl font-medium tracking-tight">{title}</RadixDialog.Title>
            {description ? <RadixDialog.Description className="mt-0.5 text-sm text-ink-muted">{description}</RadixDialog.Description> : <RadixDialog.Description className="sr-only">{title}</RadixDialog.Description>}
          </div>
          <RadixDialog.Close asChild>
            <Button variant="ghost" size="icon-sm" aria-label="Close"><X /></Button>
          </RadixDialog.Close>
        </header>
        {children}
      </RadixDialog.Content>
    </RadixDialog.Portal>
  )
}
