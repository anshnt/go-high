// The filter AST (ADR 0002): which operators each field type offers, how to tidy a half-built filter,
// plain-language summaries, and the list of fields (own and through associations) a filter can use.
import type { FieldDef, FieldType, Filter, FilterCondition, FilterGroup, FilterTag, LinkType, ObjectDef, Op } from "./types.ts";
import { formatDay, formatMoney, isMoney, valueText, type Lookup } from "./format.ts";
import { valueType, isComputed, DISPLAY_NAME } from "./schema.ts";

export const isGroup = (f: Filter): f is FilterGroup => "and" in f || "or" in f;
export const isTagCondition = (f: Filter): f is FilterTag => "tag" in f;
export const isCondition = (f: Filter): f is FilterCondition => "field" in f;
export const groupKind = (g: FilterGroup): "and" | "or" => ("and" in g ? "and" : "or");
export const groupItems = (g: FilterGroup): Filter[] => ("and" in g ? g.and : g.or);
export const makeGroup = (kind: "and" | "or", items: Filter[]): FilterGroup => (kind === "and" ? { and: items } : { or: items });

/** The builder always edits a group: null is an empty AND, a lone condition is wrapped. */
export const toRoot = (f: Filter | null | undefined): FilterGroup => (!f ? { and: [] } : isGroup(f) ? f : { and: [f] });

// ---- operators ----

const TEXT: Op[] = ["contains", "is", "is_not", "starts_with", "is_empty", "is_not_empty"];
const NUMBER: Op[] = ["is", "is_not", "gt", "gte", "lt", "lte", "between", "is_empty", "is_not_empty"];
const TIME: Op[] = ["is", "gt", "gte", "lt", "lte", "between", "within_last", "older_than", "is_empty", "is_not_empty"];
const CHOICE: Op[] = ["is", "is_not", "in", "not_in", "is_empty", "is_not_empty"];

const OPS: Record<FieldType, Op[]> = {
  text: TEXT,
  long_text: TEXT,
  email: TEXT,
  phone: TEXT,
  url: TEXT,
  number: NUMBER,
  money: NUMBER,
  date: TIME,
  datetime: TIME,
  boolean: ["is"],
  select: CHOICE,
  stage: CHOICE,
  user: CHOICE,
  multi_select: ["contains", "in", "not_in", "is_empty", "is_not_empty"],
  record: ["is", "is_not", "is_empty", "is_not_empty"],
  // never read: valueType() resolves these to their result type
  formula: NUMBER,
  rollup: NUMBER,
};

export const opsFor = (field: Pick<FieldDef, "type" | "options">): Op[] => OPS[valueType(field)];

export function opLabel(op: Op, type: FieldType): string {
  const time = type === "date" || type === "datetime";
  switch (op) {
    case "is":
      return "is";
    case "is_not":
      return "is not";
    case "contains":
      return type === "multi_select" ? "includes" : "contains";
    case "starts_with":
      return "starts with";
    case "gt":
      return time ? "is after" : "is greater than";
    case "gte":
      return time ? "is on or after" : "is at least";
    case "lt":
      return time ? "is before" : "is less than";
    case "lte":
      return time ? "is on or before" : "is at most";
    case "between":
      return "is between";
    case "is_empty":
      return "is empty";
    case "is_not_empty":
      return "is not empty";
    case "within_last":
      return "is within the last";
    case "older_than":
      return "is older than";
    case "in":
      return "is any of";
    case "not_in":
      return "is none of";
  }
}

export type ValueKind = "none" | "single" | "range" | "list" | "days";
export function valueKind(op: Op): ValueKind {
  switch (op) {
    case "is_empty":
    case "is_not_empty":
      return "none";
    case "between":
      return "range";
    case "in":
    case "not_in":
      return "list";
    case "within_last":
    case "older_than":
      return "days";
    default:
      return "single";
  }
}

const filled = (v: unknown) =>
  v !== undefined && v !== null && v !== "" && !(typeof v === "number" && Number.isNaN(v)) && !(isMoney(v) && !Number.isFinite(v.amount));

/** Value a fresh condition starts with: nothing (incomplete) except where a default is obvious. */
export function defaultValue(field: Pick<FieldDef, "type" | "options">, op: Op): unknown {
  switch (valueKind(op)) {
    case "none":
      return undefined;
    case "days":
      return { days: 30 };
    case "range":
      return [null, null];
    case "list":
      return [];
    default:
      return valueType(field) === "boolean" ? true : undefined;
  }
}

/** Keeps what the user typed when the operator changes to one with a similar value shape. */
export function convertValue(field: Pick<FieldDef, "type" | "options">, from: Op, to: Op, value: unknown): unknown {
  const a = valueKind(from);
  const b = valueKind(to);
  if (a === b) return value;
  if (a === "single" && b === "range") return [value ?? null, null];
  if (a === "range" && b === "single") return Array.isArray(value) ? (value[0] ?? undefined) : undefined;
  if (a === "single" && b === "list") return filled(value) ? [value] : [];
  if (a === "list" && b === "single") return Array.isArray(value) ? value[0] : undefined;
  return defaultValue(field, to);
}

export function isComplete(c: FilterCondition): boolean {
  const v = c.value;
  switch (valueKind(c.op)) {
    case "none":
      return true;
    case "range":
      return Array.isArray(v) && v.length === 2 && v.every(filled);
    case "list":
      return Array.isArray(v) && v.length > 0;
    case "days": {
      const d = (v as { days?: unknown } | null)?.days;
      return typeof d === "number" && Number.isInteger(d) && d > 0;
    }
    default:
      return filled(v);
  }
}

/** Drops conditions that are not finished yet and groups that end up empty. null = no filter. */
export function cleanFilter(f: Filter | null | undefined): Filter | null {
  if (!f) return null;
  if (isGroup(f)) {
    const items = groupItems(f).map(cleanFilter).filter((x): x is Filter => x !== null);
    return items.length ? makeGroup(groupKind(f), items) : null;
  }
  if (isTagCondition(f)) return f.tag ? f : null;
  return isComplete(f) ? f : null;
}

export function countConditions(f: Filter | null | undefined): number {
  if (!f) return 0;
  return isGroup(f) ? groupItems(f).reduce((n, c) => n + countConditions(c), 0) : 1;
}

/** Same filter regardless of key order or an empty group: for "has this view changed". */
export function canonical(f: unknown): string {
  const norm = (v: unknown): unknown =>
    Array.isArray(v) ? v.map(norm) : v && typeof v === "object" ? Object.fromEntries(Object.entries(v).sort(([a], [b]) => (a < b ? -1 : 1)).map(([k, x]) => [k, norm(x)])) : v;
  return JSON.stringify(norm(f ?? null));
}

// ---- plain language ----

const humanize = (key: string) => {
  const s = key.replace(/[._]+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
};
const TEXTUAL: FieldType[] = ["text", "long_text", "email", "phone", "url"];
const DAY_OPS: Op[] = ["is", "gt", "gte", "lt", "lte", "between"];
const DAY = /^\d{4}-\d{2}-\d{2}$/;

type Labelled = Pick<FieldDef, "key" | "label" | "type" | "options">;

/**
 * "Lifecycle is Customer and (Tagged VIP or Deal amount is greater than $5,000.00)".
 * `fields` may include association paths (see filterFields); unknown keys are spelled out from the key.
 */
export function filterToText(ast: Filter | null | undefined, fields: Labelled[], ctx: Lookup = {}): string {
  const byKey = new Map(fields.map((f) => [f.key, f]));
  const tagName = (id: string) => ctx.tags?.find((t) => t.id === id)?.name ?? id;

  const condition = (c: FilterCondition): string => {
    const field = byKey.get(c.field);
    const label = field?.label ?? humanize(c.field);
    const type = field ? valueType(field) : "text";
    const opText = opLabel(c.op, type);
    const one = (v: unknown) => {
      if (!field) return String(v);
      if (type === "datetime" && typeof v === "string" && DAY.test(v)) return formatDay(v); // the filter names a day, not a moment
      const t = valueText(field, v, ctx);
      return TEXTUAL.includes(type) ? `"${t}"` : t;
    };
    // "on or after Oct 1" on a datetime field is Oct 1 where the viewer is; "within the last 30 days" is a span, the same everywhere
    const zone = ctx.timeZone && type === "datetime" && DAY_OPS.includes(c.op) ? ` (your time zone: ${ctx.timeZone})` : "";
    switch (valueKind(c.op)) {
      case "none":
        return `${label} ${opText}`;
      case "range": {
        const [a, b] = Array.isArray(c.value) ? c.value : [];
        return `${label} ${opText} ${one(a)} and ${one(b)}${zone}`;
      }
      case "list":
        return `${label} ${opText} ${(Array.isArray(c.value) ? c.value : []).map(one).join(", ")}`;
      case "days": {
        const d = (c.value as { days?: number } | null)?.days ?? 0;
        return `${label} ${opText} ${d} ${d === 1 ? "day" : "days"}`;
      }
      default:
        return `${label} ${opText} ${isMoney(c.value) ? formatMoney(c.value) : one(c.value)}${zone}`;
    }
  };

  const text = (f: Filter, nested: boolean): string => {
    if (isGroup(f)) {
      const parts = groupItems(f).map((c) => text(c, true)).filter(Boolean);
      const joined = parts.join(groupKind(f) === "and" ? " and " : " or ");
      return nested && parts.length > 1 ? `(${joined})` : joined;
    }
    return isTagCondition(f) ? `Tagged ${tagName(f.tag)}` : condition(f);
  };

  return ast ? text(ast, false) : "";
}

// ---- which fields a filter (or sort, or column) can use ----

export type FieldRef = {
  /** "lifecycle" or an association path like "company.name" */
  path: string;
  label: string;
  group: string;
  /** the field with key = path, so every helper above works on it unchanged */
  field: FieldDef;
};

const lowerFirst = (s: string) => (s.length > 1 && s[1] === s[1]!.toUpperCase() && s[1] !== s[1]!.toLowerCase() ? s : s.charAt(0).toLowerCase() + s.slice(1));

/**
 * Own fields, then one hop of associations: through each record field ("company.name") and, from the other
 * side, through objects that link here ("deal.amount"). Computed fields are not offered across a link.
 */
export function filterFields(object: string, objects: ObjectDef[], fields: Record<string, FieldDef[]>, links: LinkType[] = []): FieldRef[] {
  const self = objects.find((o) => o.key === object);
  const own = (fields[object] ?? []).filter((f) => !f.archived);
  const out: FieldRef[] = own.map((f) => ({ path: f.key, label: f.label, group: self?.singular ?? object, field: f }));
  const through = (prefix: string, groupLabel: string, nameLabel: string, target: string) => {
    for (const f of (fields[target] ?? []).filter((x) => !x.archived && x.type !== "record" && !isComputed(x) && x.key !== DISPLAY_NAME)) {
      const path = `${prefix}.${f.key}`;
      if (out.some((r) => r.path === path)) continue; // a record field and an association can reach the same object
      const label = `${nameLabel} ${lowerFirst(f.label)}`;
      out.push({ path, label: f.label, group: groupLabel, field: { ...f, key: path, label } });
    }
  };
  for (const f of own) if (f.type === "record" && f.options.object) through(f.key, f.label, f.label, f.options.object);
  for (const o of objects) {
    if (o.key === object) continue;
    const linked = links.some((t) => (t.from === object && t.to === o.key) || (t.to === object && t.from === o.key));
    if (linked || (fields[o.key] ?? []).some((f) => f.type === "record" && f.options.object === object && !f.archived)) through(o.key, o.plural, o.singular, o.key);
  }
  return out;
}
