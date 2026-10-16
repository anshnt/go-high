import { Box, Building2, Handshake, Users, type LucideIcon } from "lucide-react";
import type { ObjectDef } from "./types.ts";

/** Where an object's list lives: system objects at /contacts, /companies, /deals, custom ones under /objects. */
export const objectPath = (o: Pick<ObjectDef, "key" | "plural" | "is_system">) => (o.is_system ? `/${o.plural.toLowerCase()}` : `/objects/${o.key}`);
export const recordPath = (o: Pick<ObjectDef, "key" | "plural" | "is_system">, id: string) => `${objectPath(o)}/${id}`;

const ICONS: Record<string, LucideIcon> = { users: Users, building: Building2, handshake: Handshake };
export const iconFor = (name: string): LucideIcon => ICONS[name] ?? Box;
