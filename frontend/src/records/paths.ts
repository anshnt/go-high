import { Box, Briefcase, Building2, CalendarDays, FileText, Handshake, House, Package, Star, Users, type LucideIcon } from "lucide-react";
import type { ObjectDef } from "./types.ts";

/** Where an object's list lives: system objects at /contacts, /companies, /deals, custom ones under /objects. */
export const objectPath = (o: Pick<ObjectDef, "key" | "plural" | "is_system">) => (o.is_system ? `/${o.plural.toLowerCase()}` : `/objects/${o.key}`);
export const recordPath = (o: Pick<ObjectDef, "key" | "plural" | "is_system">, id: string) => `${objectPath(o)}/${id}`;

const ICONS: Record<string, LucideIcon> = {
  user: Users,
  users: Users,
  building: Building2,
  handshake: Handshake,
  home: House,
  briefcase: Briefcase,
  calendar: CalendarDays,
  file: FileText,
  package: Package,
  star: Star,
};
export const iconFor = (name: string): LucideIcon => ICONS[name] ?? Box;
