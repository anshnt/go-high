// Plain formatting helpers: money in minor units, dates, relative times, and text for any value.
// No React, so node can test them.
import type { FieldDef, Money, Tag, UserRef } from "./types.ts";
import { valueType } from "./schema.ts";

export const LOCALE = "en-US";

// ---- money ----

const digitsCache = new Map<string, number>();
/** Decimal places of a currency's minor unit: 2 for USD, 0 for JPY, 3 for KWD. */
export function minorDigits(currency: string): number {
  let d = digitsCache.get(currency);
  if (d === undefined) {
    try {
      d = new Intl.NumberFormat(LOCALE, { style: "currency", currency }).resolvedOptions().maximumFractionDigits ?? 2;
    } catch {
      d = 2;
    }
    digitsCache.set(currency, d);
  }
  return d;
}

const moneyFormats = new Map<string, Intl.NumberFormat>();
const moneyFormat = (currency: string) => {
  let f = moneyFormats.get(currency);
  if (!f) {
    try {
      f = new Intl.NumberFormat(LOCALE, { style: "currency", currency });
    } catch {
      f = new Intl.NumberFormat(LOCALE, { style: "currency", currency: "USD" });
    }
    moneyFormats.set(currency, f);
  }
  return f;
};

// From a thousand up the cents are noise ($71,000,000), below it they matter ($19.99). The editor still shows them.
const wholeFormats = new Map<string, Intl.NumberFormat>();
const wholeFormat = (currency: string) => {
  let f = wholeFormats.get(currency);
  if (!f) {
    const options = { style: "currency", currency, minimumFractionDigits: 0, maximumFractionDigits: 0 } as const;
    try {
      f = new Intl.NumberFormat(LOCALE, options);
    } catch {
      f = new Intl.NumberFormat(LOCALE, { ...options, currency: "USD" });
    }
    wholeFormats.set(currency, f);
  }
  return f;
};

export const isMoney = (v: unknown): v is Money =>
  typeof v === "object" && v !== null && typeof (v as Money).amount === "number" && typeof (v as Money).currency === "string";

/** {amount: 99950, currency: "USD"} -> "$999.50"; {amount: 123450, ...} -> "$1,235". Amounts are integers in minor units. */
export function formatMoney(m: Money): string {
  const major = m.amount / 10 ** minorDigits(m.currency);
  return (Math.abs(major) >= 1000 ? wholeFormat(m.currency) : moneyFormat(m.currency)).format(major);
}

/** What the amount field shows while editing: "1234.50", no grouping. */
export function moneyToInput(m: Money | null | undefined): string {
  if (!m) return "";
  const d = minorDigits(m.currency);
  return d === 0 ? String(m.amount) : (m.amount / 10 ** d).toFixed(d);
}

/** "1,234.5" -> 123450 (USD). null when the text is not an amount or has too many decimals. Works on strings, so no float drift. */
export function parseMoney(text: string, currency: string): number | null {
  const d = minorDigits(currency);
  const t = text.replace(/[\s,_]/g, "").replace(/^[^\d.-]+/, "");
  const m = /^(-?)(\d*)(?:\.(\d*))?$/.exec(t);
  if (!m || (!m[2] && !m[3])) return null;
  const frac = m[3] ?? "";
  if (frac.length > d) return null;
  const minor = Number((m[2] || "0") + frac.padEnd(d, "0"));
  return Number.isSafeInteger(minor) ? (m[1] ? -minor : minor) : null;
}

export const formatNumber = (n: number) => new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 4 }).format(n);

// ---- dates ----
// Day-only values are "YYYY-MM-DD" and are never shifted by a time zone. Instants are ISO strings.

const DAY = /^(\d{4})-(\d{2})-(\d{2})$/;
const MS_DAY = 86_400_000;

/** The viewer's time zone ("Europe/Lisbon"): what a day in a date filter on a datetime field means. */
export const zoneName = (): string => new Intl.DateTimeFormat(LOCALE).resolvedOptions().timeZone;

/** "2026-10-17" -> local midnight; null if it is not a real calendar day. */
export function parseDay(s: string): Date | null {
  const m = DAY.exec(s);
  if (!m) return null;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return d.getFullYear() === Number(m[1]) && d.getMonth() === Number(m[2]) - 1 && d.getDate() === Number(m[3]) ? d : null;
}

const pad = (n: number) => String(n).padStart(2, "0");
export const toDay = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const startOfDay = (ms: number) => {
  const d = new Date(ms);
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
};

/** An instant as the value of <input type="datetime-local"> (the viewer's zone), and back. */
export function toLocalInput(iso: unknown): string {
  const d = new Date(Date.parse(String(iso)));
  return Number.isNaN(d.getTime()) ? "" : `${toDay(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
export function fromLocalInput(s: string): string | undefined {
  const t = new Date(s).getTime();
  return s && !Number.isNaN(t) ? new Date(t).toISOString() : undefined;
}

const dayFmt = new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short", year: "numeric" });
/** "2026-10-17" -> "Oct 17, 2026" */
export function formatDay(s: string): string {
  const d = parseDay(s);
  return d ? dayFmt.format(d) : s;
}

/** "Oct 17, 2026, 9:00 AM" in the viewer's zone (pass timeZone: "UTC" in tests). */
export function formatDateTime(iso: string, timeZone?: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  return new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit", timeZone }).format(t);
}

const rtf = new Intl.RelativeTimeFormat(LOCALE, { numeric: "auto" });

function relativeDays(days: number): string {
  const a = Math.abs(days);
  if (a < 7) return rtf.format(days, "day");
  if (a < 30) return rtf.format(Math.round(days / 7), "week");
  if (a < 365) return rtf.format(Math.round(days / 30), "month");
  return rtf.format(Math.round(days / 365), "year");
}

/** "5 minutes ago", "in 3 days", "last week". Works both ways, unlike lib/device timeAgo. */
export function relativeTime(iso: string, now: number): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const s = Math.round((t - now) / 1000);
  const a = Math.abs(s);
  if (a < 45) return "just now";
  if (a < 3600) return rtf.format(Math.round(s / 60), "minute");
  if (a < 86_400) return rtf.format(Math.round(s / 3600), "hour");
  return relativeDays(Math.round(s / 86_400));
}

/** Calendar-day distance: "today", "tomorrow", "in 3 days", "2 weeks ago". */
export function relativeDay(day: string, now: number): string {
  const d = parseDay(day);
  if (!d) return day;
  return relativeDays(Math.round((d.getTime() - startOfDay(now)) / MS_DAY));
}

/** Heading for a group of timeline events: Today, Yesterday, "Mon, Oct 12", "Oct 12, 2025". */
export function dayHeading(iso: string, now: number): string {
  const t = Date.parse(iso);
  const diff = Math.round((startOfDay(now) - startOfDay(t)) / MS_DAY);
  if (diff === 0) return "Today";
  if (diff === 1) return "Yesterday";
  const sameYear = new Date(t).getFullYear() === new Date(now).getFullYear();
  return new Intl.DateTimeFormat(LOCALE, sameYear ? { weekday: "short", month: "short", day: "numeric" } : { month: "short", day: "numeric", year: "numeric" }).format(t);
}

/** Local day key for grouping ("2026-10-17"). */
export const dayKey = (iso: string) => toDay(new Date(Date.parse(iso)));

// ---- any value as plain text ----

export type Lookup = {
  users?: UserRef[];
  tags?: Tag[];
  /** record id -> display name */
  records?: Record<string, string>;
  /** the viewer's time zone: a day in a condition on a datetime field is a day there, and the summary says so */
  timeZone?: string;
};

/** The value in words, for summaries and the timeline. "" when empty. */
export function valueText(field: Pick<FieldDef, "type" | "options">, value: unknown, lookup: Lookup = {}): string {
  if (value === null || value === undefined || value === "") return "";
  const choice = (id: unknown) => field.options.choices?.find((c) => c.id === id)?.label ?? String(id);
  switch (valueType(field)) {
    case "number":
      return typeof value === "number" ? formatNumber(value) : String(value);
    case "money":
      return isMoney(value) ? formatMoney(value) : String(value);
    case "date":
      return formatDay(String(value));
    case "datetime":
      return formatDateTime(String(value));
    case "boolean":
      return value ? "Yes" : "No";
    case "select":
    case "stage":
      return choice(value);
    case "multi_select":
      return (Array.isArray(value) ? value : [value]).map(choice).join(", ");
    case "user":
      return lookup.users?.find((u) => u.id === value)?.name ?? String(value);
    case "record":
      return lookup.records?.[String(value)] ?? String(value);
    default:
      return String(value);
  }
}

const PLAIN: string[] = ["text", "email", "phone", "url", "number", "money", "select", "stage", "date"];

/** One short line to tell records apart: the first filled field (after the name) of a type that reads as plain text. */
export function subtitle(values: Record<string, unknown>, fields: Pick<FieldDef, "key" | "type" | "options">[], primary: string[]): string {
  for (const f of fields) {
    if (primary.includes(f.key) || !PLAIN.includes(f.type)) continue;
    const v = values[f.key];
    if (v !== undefined && v !== null && v !== "") return f.type === "url" ? String(v).replace(/^https?:\/\//i, "").replace(/\/$/, "") : valueText(f, v);
  }
  return "";
}
