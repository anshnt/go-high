import * as RPopover from "@radix-ui/react-popover";
import type { ReactNode } from "react";
import { cn } from "../lib/cn";

type Props = {
  trigger: ReactNode;
  children: ReactNode;
  align?: "start" | "center" | "end";
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Names the panel for screen readers. */
  label: string;
  className?: string;
};

/**
 * An anchored panel for forms and lists (a menu is for commands only). Does not block the page behind it,
 * so a filter can change a list you are looking at. trigger must be a single focusable element.
 */
export function Popover({ trigger, children, align = "start", open, onOpenChange, label, className }: Props) {
  return (
    <RPopover.Root open={open} onOpenChange={onOpenChange}>
      <RPopover.Trigger asChild>{trigger}</RPopover.Trigger>
      <RPopover.Portal>
        <RPopover.Content className={cn("ui-popover ui-popover-panel", className)} align={align} sideOffset={6} collisionPadding={8} aria-label={label}>
          {children}
        </RPopover.Content>
      </RPopover.Portal>
    </RPopover.Root>
  );
}
