import * as RMenu from "@radix-ui/react-dropdown-menu";
import type { ComponentProps, ReactNode } from "react";
import { cn } from "../lib/cn";

type Props = { trigger: ReactNode; children: ReactNode; align?: "start" | "end"; label?: string; onOpenChange?: (open: boolean) => void; className?: string };

/** trigger must be a single focusable element (e.g. a Button). */
export function DropdownMenu({ trigger, children, align = "end", label, onOpenChange, className }: Props) {
  return (
    <RMenu.Root onOpenChange={onOpenChange}>
      <RMenu.Trigger asChild>{trigger}</RMenu.Trigger>
      <RMenu.Portal>
        <RMenu.Content className={cn("ui-popover ui-menu", className)} align={align} sideOffset={6} aria-label={label}>
          {children}
        </RMenu.Content>
      </RMenu.Portal>
    </RMenu.Root>
  );
}

export function MenuItem({ icon, children, className, ...rest }: ComponentProps<typeof RMenu.Item> & { icon?: ReactNode }) {
  return (
    <RMenu.Item className={cn("ui-item", className)} {...rest}>
      {icon}
      {children}
    </RMenu.Item>
  );
}

export const MenuLabel = (p: ComponentProps<typeof RMenu.Label>) => <RMenu.Label className="ui-menu-label" {...p} />;
export const MenuSeparator = () => <RMenu.Separator className="ui-separator" />;
