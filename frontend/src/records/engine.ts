// What the server does for a query, in plain TypeScript: evaluate the filter AST, order rows, keyset cursors, text search.
// The memory client runs on this; the real API replaces all of it. A day named in a filter on a date field is that
// calendar day; on a datetime field it is that day in the viewer's time zone, as the API client sends it.
import { RecordsError } from "./errors.ts";
import { isEmptyValue } from "./validate.ts";
import { isCondition, isGroup, isTagCondition, groupItems, groupKind, opsFor } from "./filter.ts";
import { isMoney } from "./format.ts";
import { valueType } from "./schema.ts";
import type { FieldDef, Filter, FilterCondition, Op, RecordRow, SortSpec } from "./types.ts";

export type Env = {
  now: number;
  field: (object: string, key: string) => FieldDef | undefined;
  /** raw value, computed fields included */
  value: (rec: RecordRow, key: string) => unknown;
  /** records one association hop away: through a record field ("company") or from a linking object ("deal") */
  linked: (rec: RecordRow, segment: string) => RecordRow[];
};

const DAY_MS = 86_400_000;
const PSEUDO: Record<string, FieldDef> = {
  display_name: { key: "display_name", label: "Name", type: "text", options: {}, rules: {}, is_system: true, position: 0, archived: false },
};

// ---- time ----

const day = (s: string) => /^\d{4}-\d{2}-\d{2}$/.test(s);
/** A point (an instant, or the start of a calendar day for date fields). */
const point = (v: unknown): number => Date.parse(day(String(v)) ? `${v}T00:00:00Z` : String(v));
/**
 * The half-open span a filter operand stands for: a whole day for "2026-10-17" (in the viewer's time zone when `local`,
 * for a datetime field), a single millisecond for an instant.
 */
function span(v: unknown, local = false): [number, number] {
  if (!day(String(v))) {
    const s = point(v);
    return [s, s + 1];
  }
  const [y, m, d] = String(v).split("-").map(Number) as [number, number, number];
  return local ? [new Date(y, m - 1, d).getTime(), new Date(y, m - 1, d + 1).getTime()] : [Date.UTC(y, m - 1, d), Date.UTC(y, m - 1, d) + DAY_MS];
}

// ---- evaluation ----

const NEGATED: Partial<Record<Op, Op>> = { is_not: "is", not_in: "in", is_empty: "is_not_empty" };

/** Does the record match? Empty groups match everything; unknown fields and operators that do not fit the type are 400s. */
export function evaluate(f: Filter | null | undefined, rec: RecordRow, env: Env): boolean {
  if (!f) return true;
  if (isGroup(f)) {
    const items = groupItems(f);
    return groupKind(f) === "and" ? items.every((c) => evaluate(c, rec, env)) : items.length === 0 || items.some((c) => evaluate(c, rec, env));
  }
  if (isTagCondition(f)) return rec.tags.some((t) => t.id === f.tag);
  if (!isCondition(f)) throw new RecordsError(400, "Unknown filter.");
  const dot = f.field.indexOf(".");
  if (dot <= 0) return test(rec, f, env);
  // Association path: EXISTS over the linked records. "is not", "is none of" and "is empty" mean NO linked record matches the positive form.
  const linked = env.linked(rec, f.field.slice(0, dot));
  const key = f.field.slice(dot + 1);
  const positive = NEGATED[f.op];
  return positive ? !linked.some((l) => test(l, { ...f, field: key, op: positive }, env)) : linked.some((l) => test(l, { ...f, field: key }, env));
}

function test(rec: RecordRow, c: FilterCondition, env: Env): boolean {
  // Looking records up by id ("in") is how the screens fetch the names behind record links in one call.
  if (c.field === "id") {
    if (c.op === "in") return Array.isArray(c.value) && c.value.includes(rec.id);
    if (c.op === "is") return rec.id === c.value;
    throw new RecordsError(400, `"${c.op}" does not apply to id.`);
  }
  const field = env.field(rec.object, c.field) ?? PSEUDO[c.field];
  if (!field) throw new RecordsError(400, `There is no field "${c.field}".`);
  if (!opsFor(field).includes(c.op)) throw new RecordsError(400, `"${c.op}" does not apply to ${field.label}.`);
  const type = valueType(field);
  const v = env.value(rec, c.field);
  const a = c.value;
  const textual = ["text", "long_text", "email", "phone", "url"].includes(type);
  const time = type === "date" || type === "datetime";

  switch (c.op) {
    case "is_empty":
      return isEmptyValue(v);
    case "is_not_empty":
      return !isEmptyValue(v);
    case "is":
      return same(type, v, a);
    case "is_not":
      return !same(type, v, a);
    case "contains":
      if (type === "multi_select") return Array.isArray(v) && v.includes(a);
      return textual && !isEmptyValue(v) && String(v).toLowerCase().includes(String(a).toLowerCase());
    case "starts_with":
      return textual && !isEmptyValue(v) && String(v).toLowerCase().startsWith(String(a).toLowerCase());
    case "gt":
    case "gte":
    case "lt":
    case "lte":
      return compare(type, v, a, c.op, time);
    case "between": {
      const [from, to] = Array.isArray(a) ? a : [];
      return time ? timeBetween(v, from, to, type === "datetime") : between(type, v, from, to);
    }
    case "within_last":
    case "older_than": {
      const days = (a as { days?: number } | null)?.days;
      if (typeof days !== "number" || isEmptyValue(v)) return false;
      const t = point(v);
      const now = type === "date" ? Math.floor(env.now / DAY_MS) * DAY_MS : env.now;
      return c.op === "within_last" ? t >= now - days * DAY_MS && t <= now : t < now - days * DAY_MS;
    }
    case "in":
      if (!Array.isArray(a)) return false;
      return Array.isArray(v) ? v.some((x) => a.includes(x)) : !isEmptyValue(v) && a.includes(v);
    case "not_in":
      if (!Array.isArray(a)) return false;
      return Array.isArray(v) ? !v.some((x) => a.includes(x)) : isEmptyValue(v) || !a.includes(v);
  }
}

function same(type: string, v: unknown, a: unknown): boolean {
  if (type === "boolean") return Boolean(v) === a;
  if (isEmptyValue(v)) return false;
  if (type === "money") return isMoney(v) && isMoney(a) && v.amount === a.amount && v.currency === a.currency;
  if (type === "date" || type === "datetime") {
    const [s, e] = span(a, type === "datetime");
    const p = point(v);
    return p >= s && p < e;
  }
  if (["text", "long_text", "email", "phone", "url"].includes(type)) return String(v).toLowerCase() === String(a).toLowerCase();
  return v === a;
}

/** Number and money compare by amount, and only inside one currency; null when they cannot be compared. */
function cmpScalar(type: string, v: unknown, a: unknown): number | null {
  if (isEmptyValue(v)) return null;
  if (type === "money") return isMoney(v) && isMoney(a) && v.currency === a.currency ? v.amount - a.amount : null;
  return typeof v === "number" && typeof a === "number" ? v - a : null;
}

function compare(type: string, v: unknown, a: unknown, op: "gt" | "gte" | "lt" | "lte", time: boolean): boolean {
  if (isEmptyValue(v)) return false;
  if (time) {
    const p = point(v);
    const [s, e] = span(a, type === "datetime");
    return op === "gt" ? p >= e : op === "gte" ? p >= s : op === "lt" ? p < s : p < e;
  }
  const d = cmpScalar(type, v, a);
  if (d === null) return false;
  return op === "gt" ? d > 0 : op === "gte" ? d >= 0 : op === "lt" ? d < 0 : d <= 0;
}

function between(type: string, v: unknown, lo: unknown, hi: unknown): boolean {
  const x = cmpScalar(type, v, lo);
  const y = cmpScalar(type, v, hi);
  return x !== null && y !== null && x >= 0 && y <= 0;
}

function timeBetween(v: unknown, from: unknown, to: unknown, local: boolean): boolean {
  if (isEmptyValue(v) || isEmptyValue(from) || isEmptyValue(to)) return false;
  const p = point(v);
  return p >= span(from, local)[0] && p < span(to, local)[1];
}

// ---- ordering and cursors ----

export type SortKey = number | string | null;
const collator = new Intl.Collator("en", { numeric: true, sensitivity: "base" });

/** Rows with no value go last whichever way the column is sorted. Ties break on id so the order is total. */
export function compareKeys(a: SortKey[], b: SortKey[], dirs: (1 | -1)[], idA: string, idB: string): number {
  for (let i = 0; i < dirs.length; i++) {
    const x = a[i] ?? null;
    const y = b[i] ?? null;
    if (x === y) continue;
    if (x === null) return 1;
    if (y === null) return -1;
    const c = typeof x === "number" && typeof y === "number" ? x - y : collator.compare(String(x), String(y));
    if (c !== 0) return c * dirs[i]!;
  }
  return idA < idB ? -1 : idA > idB ? 1 : 0;
}

export const dirsOf = (sort: SortSpec[]): (1 | -1)[] => sort.map((s) => (s.dir === "desc" ? -1 : 1));

export type Cursor = { k: SortKey[]; id: string };
const bytesToB64 = (s: string) => btoa(String.fromCharCode(...new TextEncoder().encode(s))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const b64ToString = (b: string) => new TextDecoder().decode(Uint8Array.from(atob(b.replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0)));

export const encodeCursor = (c: Cursor): string => bytesToB64(JSON.stringify(c));
export function decodeCursor(s: string): Cursor {
  try {
    const c = JSON.parse(b64ToString(s));
    if (Array.isArray(c.k) && typeof c.id === "string") return c;
  } catch {
    /* fall through */
  }
  throw new RecordsError(400, "That page link is not valid. Reload the list.");
}

// ---- search ----

/** Every word of the query must appear somewhere in the record's text. */
export function matchesQuery(blob: string, q: string): boolean {
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  return words.every((w) => blob.includes(w));
}
