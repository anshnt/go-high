// The logic behind the weekly hours editor, with no React: ranges of a day, checks, and the shape the API takes.

export const WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
export type Weekday = (typeof WEEKDAYS)[number];
/** ["09:00", "17:00"]; the end may be "24:00". */
export type Range = [string, string];
export type Weekly = Record<Weekday, Range[]>;

export const MAX_RANGES = 6;
export const STEP = 15;
export const DAY_NAMES: Record<Weekday, string> = { mon: "Monday", tue: "Tuesday", wed: "Wednesday", thu: "Thursday", fri: "Friday", sat: "Saturday", sun: "Sunday" };
export const WORKDAYS: Weekday[] = ["mon", "tue", "wed", "thu", "fri"];

const pad = (n: number) => String(n).padStart(2, "0");

/** "09:30" as minutes after midnight ("24:00" is 1440), or null when it is not a time of day. */
export function toMinutes(time: string): number | null {
  const m = /^(\d{2}):(\d{2})$/.exec(time);
  if (!m) return null;
  const mins = Number(m[1]) * 60 + Number(m[2]);
  return Number(m[2]) <= 59 && mins <= 1440 ? mins : null;
}

export const fromMinutes = (mins: number): string => `${pad(Math.floor(mins / 60))}:${pad(mins % 60)}`;

/** "9:30 AM"; the end of the day reads "Midnight". */
export function formatHM(time: string): string {
  const mins = toMinutes(time);
  if (mins === null) return time;
  if (mins === 1440) return "Midnight";
  const h = Math.floor(mins / 60);
  return `${h % 12 || 12}:${pad(mins % 60)} ${h < 12 ? "AM" : "PM"}`;
}

/** The times a start or an end can be picked from, every quarter hour; `keep` is a stored time off that grid, so it can still be shown. */
export function timeOptions(kind: "start" | "end", keep?: string): string[] {
  const from = kind === "start" ? 0 : STEP;
  const to = kind === "start" ? 1440 - STEP : 1440;
  const out: string[] = [];
  for (let m = from; m <= to; m += STEP) out.push(fromMinutes(m));
  if (keep && toMinutes(keep) !== null && !out.includes(keep)) out.push(keep);
  return out.sort();
}

export const overlaps = (a: Range, b: Range): boolean => (toMinutes(a[0]) ?? 0) < (toMinutes(b[1]) ?? 0) && (toMinutes(b[0]) ?? 0) < (toMinutes(a[1]) ?? 0);

export const sortRanges = (ranges: Range[]): Range[] => [...ranges].sort((a, b) => (toMinutes(a[0]) ?? 0) - (toMinutes(b[0]) ?? 0));

/** The first thing wrong with a day's ranges, in a sentence, or null. */
export function rangeError(ranges: Range[]): string | null {
  if (ranges.length > MAX_RANGES) return `Up to ${MAX_RANGES} ranges a day.`;
  for (const [start, end] of ranges) {
    const a = toMinutes(start);
    const b = toMinutes(end);
    if (a === null || b === null) return "Use times like 09:00.";
    if (a >= b) return `${formatHM(start)} to ${formatHM(end)} ends before it starts.`;
  }
  const sorted = sortRanges(ranges);
  for (let i = 1; i < sorted.length; i++) if (overlaps(sorted[i - 1]!, sorted[i]!)) return "Two ranges overlap. Merge them or move one.";
  return null;
}

/** A new range after the last one: an hour long (or what is left of the day), from the last end or 09:00. Null when there is no room. */
export function nextRange(ranges: Range[]): Range | null {
  if (ranges.length >= MAX_RANGES) return null;
  const last = sortRanges(ranges).at(-1);
  const from = last ? (toMinutes(last[1]) ?? 0) : 9 * 60;
  const to = Math.min(from + 60, 1440);
  return to - from >= STEP ? [fromMinutes(from), fromMinutes(to)] : null;
}

/** Every weekday's ranges, with the same problem list the editor shows per row. */
export function weekErrors(weekly: Weekly): Partial<Record<Weekday, string>> {
  const out: Partial<Record<Weekday, string>> = {};
  for (const d of WEEKDAYS) {
    const e = rangeError(weekly[d]);
    if (e) out[d] = e;
  }
  return out;
}

/** `from`'s ranges copied onto the other days (Monday to Friday by default). */
export function copyToWeekdays(weekly: Weekly, from: Weekday, to: Weekday[] = WORKDAYS): Weekly {
  const out = { ...weekly };
  for (const d of to) if (d !== from) out[d] = weekly[from].map(([a, b]): Range => [a, b]);
  return out;
}

/** The API's shape: every day present, ranges in order. */
export function serialize(weekly: Weekly): Weekly {
  return Object.fromEntries(WEEKDAYS.map((d) => [d, sortRanges(weekly[d] ?? []).map(([a, b]): Range => [a, b])])) as Weekly;
}

/** What the API sent, made safe to edit: unknown days are dropped and missing ones are empty. */
export function parseWeekly(raw: unknown): Weekly {
  const src = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const day = (v: unknown): Range[] =>
    Array.isArray(v) ? v.filter((r): r is Range => Array.isArray(r) && r.length === 2 && typeof r[0] === "string" && typeof r[1] === "string").map(([a, b]): Range => [a, b]) : [];
  return Object.fromEntries(WEEKDAYS.map((d) => [d, day(src[d])])) as Weekly;
}

export const sameWeek = (a: Weekly, b: Weekly): boolean => JSON.stringify(serialize(a)) === JSON.stringify(serialize(b));

/** "9:00 AM to 5:00 PM, 6:00 PM to Midnight", or "Unavailable" for no ranges. */
export const describeRanges = (ranges: Range[]): string => (ranges.length === 0 ? "Unavailable" : sortRanges(ranges).map(([a, b]) => `${formatHM(a)} to ${formatHM(b)}`).join(", "));

/** The usual week, the one the server proposes for someone with no saved hours. */
export const usualWeek = (): Weekly => Object.fromEntries(WEEKDAYS.map((d, i) => [d, i < 5 ? [["09:00", "17:00"]] : []])) as Weekly;
