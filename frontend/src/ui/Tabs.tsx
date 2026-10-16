import * as RTabs from "@radix-ui/react-tabs";
import type { ComponentProps } from "react";
import { cn } from "../lib/cn";

export const Tabs = RTabs.Root;
export const TabsContent = (p: ComponentProps<typeof RTabs.Content>) => <RTabs.Content {...p} className={cn("ui-tab-panel", p.className)} />;
export const TabsList = (p: ComponentProps<typeof RTabs.List>) => <RTabs.List {...p} className={cn("ui-tabs", p.className)} />;
export const TabsTrigger = (p: ComponentProps<typeof RTabs.Trigger>) => <RTabs.Trigger {...p} className={cn("ui-tab", p.className)} />;
