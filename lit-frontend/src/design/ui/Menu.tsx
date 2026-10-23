import * as RadixMenu from '@radix-ui/react-dropdown-menu'
import { forwardRef, type ComponentPropsWithoutRef, type ElementRef } from 'react'
import { cn } from '@/lib/cn'

export const Menu = RadixMenu.Root
export const MenuTrigger = RadixMenu.Trigger
export const MenuGroup = RadixMenu.Group

export const MenuContent = forwardRef<ElementRef<typeof RadixMenu.Content>, ComponentPropsWithoutRef<typeof RadixMenu.Content>>(
  function MenuContent({ className, sideOffset = 8, ...props }, ref) {
    return (
      <RadixMenu.Portal>
        <RadixMenu.Content
          ref={ref}
          sideOffset={sideOffset}
          className={cn(
            'z-50 min-w-64 overflow-hidden rounded-xl border border-border bg-surface p-1.5 text-ink shadow-float',
            'data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95',
            'data-[state=closed]:animate-out data-[state=closed]:fade-out-0',
            className,
          )}
          {...props}
        />
      </RadixMenu.Portal>
    )
  },
)

export const MenuItem = forwardRef<ElementRef<typeof RadixMenu.Item>, ComponentPropsWithoutRef<typeof RadixMenu.Item>>(
  function MenuItem({ className, ...props }, ref) {
    return (
      <RadixMenu.Item
        ref={ref}
        className={cn(
          'relative flex cursor-pointer select-none items-start gap-3 rounded-lg px-2.5 py-2 text-sm outline-none',
          'data-[highlighted]:bg-sunken data-[disabled]:cursor-not-allowed data-[disabled]:opacity-45',
          className,
        )}
        {...props}
      />
    )
  },
)

export function MenuLabel({ className, ...props }: ComponentPropsWithoutRef<typeof RadixMenu.Label>) {
  return <RadixMenu.Label className={cn('px-2.5 pb-1 pt-2 text-2xs font-medium uppercase tracking-[0.08em] text-ink-subtle', className)} {...props} />
}

export function MenuSeparator({ className, ...props }: ComponentPropsWithoutRef<typeof RadixMenu.Separator>) {
  return <RadixMenu.Separator className={cn('-mx-1.5 my-1.5 h-px bg-border', className)} {...props} />
}
