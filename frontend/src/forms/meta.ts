// What the builder knows about each kind of question: its name, icon, which contact fields it can fill, and which
// tests a rule may use on it. The server has the same tables (backend/app/forms/definition.py and logic.py).
import { AlignLeft, CalendarDays, EyeOff, Hash, Heading, ListChecks, Mail, Phone, Pilcrow, SquareCheck, Star, ToggleLeft, Type, ShieldCheck, ChevronsUpDown, type LucideIcon } from "lucide-react";
import type { FieldType, Op } from "../forms-runtime/types";

export const FIELD_TYPES: { type: FieldType; label: string; icon: LucideIcon; group: string }[] = [
  { type: "short_text", label: "Short answer", icon: Type, group: "Text" },
  { type: "long_text", label: "Long answer", icon: AlignLeft, group: "Text" },
  { type: "email", label: "Email", icon: Mail, group: "Contact details" },
  { type: "phone", label: "Phone", icon: Phone, group: "Contact details" },
  { type: "number", label: "Number", icon: Hash, group: "Choices and numbers" },
  { type: "select", label: "Dropdown", icon: ChevronsUpDown, group: "Choices and numbers" },
  { type: "multi_select", label: "Multiple choice", icon: ListChecks, group: "Choices and numbers" },
  { type: "yes_no", label: "Yes or no", icon: ToggleLeft, group: "Choices and numbers" },
  { type: "rating", label: "Rating (1 to 5)", icon: Star, group: "Choices and numbers" },
  { type: "date", label: "Date", icon: CalendarDays, group: "Choices and numbers" },
  { type: "checkbox", label: "Checkbox", icon: SquareCheck, group: "Other" },
  { type: "consent", label: "Consent", icon: ShieldCheck, group: "Other" },
  { type: "hidden", label: "Hidden (from the link)", icon: EyeOff, group: "Other" },
  { type: "heading", label: "Heading", icon: Heading, group: "Text blocks" },
  { type: "paragraph", label: "Paragraph", icon: Pilcrow, group: "Text blocks" },
];
export const TYPE_META = Object.fromEntries(FIELD_TYPES.map((t) => [t.type, t])) as Record<FieldType, (typeof FIELD_TYPES)[number]>;
export const GROUPS = [...new Set(FIELD_TYPES.map((t) => t.group))];

export const isContent = (t: FieldType) => t === "heading" || t === "paragraph";
export const isAnswer = (t: FieldType) => !isContent(t);
export const QUIZ_TYPES: FieldType[] = ["select", "multi_select", "yes_no", "rating", "number", "short_text"];

// The contact field types a question can fill.
export const COMPATIBLE: Partial<Record<FieldType, string[]>> = {
  short_text: ["text", "url"], long_text: ["text", "long_text"], hidden: ["text", "url"], email: ["email"], phone: ["phone"],
  number: ["number"], rating: ["number"], date: ["date"], select: ["select", "text"], multi_select: ["multi_select"],
  checkbox: ["boolean"], consent: ["boolean"], yes_no: ["boolean"],
};

const TEXT_OPS: Op[] = ["is", "is_not", "contains", "in", "not_in", "is_empty", "is_not_empty"];
const NUM_OPS: Op[] = ["is", "is_not", "gt", "gte", "lt", "lte", "in", "not_in", "is_empty", "is_not_empty"];
export const OPS_BY_TYPE: Partial<Record<FieldType, Op[]>> = {
  short_text: TEXT_OPS, long_text: TEXT_OPS, email: TEXT_OPS, phone: TEXT_OPS, hidden: TEXT_OPS, number: NUM_OPS, rating: NUM_OPS,
  date: ["is", "is_not", "gt", "gte", "lt", "lte", "is_empty", "is_not_empty"],
  select: ["is", "is_not", "in", "not_in", "is_empty", "is_not_empty"],
  multi_select: ["is", "is_not", "contains", "in", "not_in", "is_empty", "is_not_empty"],
  checkbox: ["is", "is_not", "is_empty", "is_not_empty"], consent: ["is", "is_not", "is_empty", "is_not_empty"], yes_no: ["is", "is_not", "is_empty", "is_not_empty"],
};
export const OP_LABEL: Record<Op, string> = {
  is: "is", is_not: "is not", contains: "contains", in: "is one of", not_in: "is none of", gt: "is above", gte: "is at least", lt: "is below",
  lte: "is at most", is_empty: "is empty", is_not_empty: "is filled in",
};
