// Time zone helpers for the calendar screens. No React and no DOM, so node can test them. A date is a "YYYY-MM-DD" key
// (a day on some wall clock), an instant is epoch milliseconds. The zone is always passed in, never read from the machine,
// except by `browserZone`.

export const LOCALE = "en-US";
const MINUTE = 60_000;
const DAY = 86_400_000;

const FALLBACK_ZONES = [
  "UTC",
  "America/Los_Angeles",
  "America/Denver",
  "America/Chicago",
  "America/New_York",
  "America/Sao_Paulo",
  "Europe/London",
  "Europe/Paris",
  "Europe/Berlin",
  "Africa/Johannesburg",
  "Asia/Dubai",
  "Asia/Kolkata",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Australia/Sydney",
  "Pacific/Auckland",
];

export function isZone(name: string): boolean {
  try {
    new Intl.DateTimeFormat(LOCALE, { timeZone: name });
    return true;
  } catch {
    return false;
  }
}

/** The zone this browser runs in; UTC when it cannot say. */
export function browserZone(): string {
  try {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return zone && isZone(zone) ? zone : "UTC";
  } catch {
    return "UTC";
  }
}

/** Every zone the browser knows (a short list where it cannot say), the browser's own and UTC first, then `include`. */
export function zoneList(include: string[] = []): string[] {
  let all = FALLBACK_ZONES;
  try {
    const found = (Intl as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf?.("timeZone");
    if (found && found.length > 0) all = found;
  } catch {
    /* the short list */
  }
  const first = [browserZone(), "UTC", ...include].filter(isZone);
  return [...new Set([...first, ...all])];
}

const formats = new Map<string, Intl.DateTimeFormat>();
function format(zone: string, key: string, options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const id = `${zone}|${key}`;
  let f = formats.get(id);
  if (!f) {
    f = new Intl.DateTimeFormat(LOCALE, { timeZone: zone, ...options });
    formats.set(id, f);
  }
  return f;
}

export type Wall = { year: number; month: number; day: number; hour: number; minute: number; second: number };

/** The wall clock of `zone` at an instant. */
export function wallOf(ms: number, zone: string): Wall {
  const f = format(zone, "wall", { hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const out: Record<string, number> = {};
  for (const p of f.formatToParts(ms)) if (p.type !== "literal") out[p.type] = Number(p.value);
  return { year: out.year!, month: out.month!, day: out.day!, hour: out.hour! % 24, minute: out.minute!, second: out.second! };
}

const wallMs = (w: Wall) => Date.UTC(w.year, w.month - 1, w.day, w.hour, w.minute, w.second);

/** Minutes the zone is ahead of UTC at an instant (-240 for New York in summer). */
export const offsetMinutes = (ms: number, zone: string): number => Math.round((wallMs(wallOf(ms, zone)) - Math.floor(ms / 1000) * 1000) / MINUTE);

const pad = (n: number) => String(n).padStart(2, "0");
const keyOf = (d: Date) => `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
const utcOfKey = (key: string) => {
  const [y, m, d] = key.split("-").map(Number);
  return Date.UTC(y!, m! - 1, d!);
};

export const isDateKey = (s: string) => /^\d{4}-\d{2}-\d{2}$/.test(s) && keyOf(new Date(utcOfKey(s))) === s;
export const isClock = (s: string) => /^([01]\d|2[0-3]):[0-5]\d$/.test(s);

/** The day an instant falls on, on the wall clock of `zone`. */
export function dateKey(ms: number, zone: string): string {
  const w = wallOf(ms, zone);
  return `${w.year}-${pad(w.month)}-${pad(w.day)}`;
}

/** Pure calendar arithmetic: no zone, so no daylight saving to trip over. */
export const addDays = (key: string, n: number): string => keyOf(new Date(utcOfKey(key) + n * DAY));

/** 0 for Monday to 6 for Sunday. */
export const weekdayOf = (key: string): number => (new Date(utcOfKey(key)).getUTCDay() + 6) % 7;

/** Minutes after local midnight on the wall clock of `zone`. */
export function wallMinutes(ms: number, zone: string): number {
  const w = wallOf(ms, zone);
  return w.hour * 60 + w.minute;
}

/**
 * The instant of `time` ("09:30"; "24:00" is the end of the day) on `key`'s wall clock in `zone`. A time the clock skips
 * (the hour that springs forward) lands after the gap, and one that happens twice (the hour that falls back) is the
 * first of them: the same rule the server uses for working hours.
 */
export function zonedToUtc(key: string, time: string, zone: string): number {
  const [h, m] = time.split(":").map(Number);
  const guess = utcOfKey(key) + h! * 60 * MINUTE + m! * MINUTE; // the wall time, read as if it were UTC
  const before = guess - offsetMinutes(guess - DAY, zone) * MINUTE;
  const after = guess - offsetMinutes(guess + DAY, zone) * MINUTE;
  const fits = [before, after].filter((t) => wallMs(wallOf(t, zone)) === guess);
  return fits.length > 0 ? Math.min(...fits) : before;
}

export const startOfDay = (key: string, zone: string): number => zonedToUtc(key, "00:00", zone);
export const endOfDay = (key: string, zone: string): number => startOfDay(addDays(key, 1), zone);

export type Week = { days: string[]; from: number; to: number };

/** The Monday to Sunday week around a day, and the instants it spans (a daylight saving week is 167 or 169 hours). */
export function weekRange(key: string, zone: string): Week {
  const monday = addDays(key, -weekdayOf(key));
  const days = Array.from({ length: 7 }, (_, i) => addDays(monday, i));
  return { days, from: startOfDay(days[0]!, zone), to: startOfDay(addDays(days[6]!, 1), zone) };
}

const tidy = (s: string) => s.replace(/ /g, " "); // newer engines put a narrow space before AM and PM

/** "9:30 AM" */
export const formatClock = (ms: number, zone: string): string => tidy(format(zone, "clock", { hour: "numeric", minute: "2-digit" }).format(ms));
/** "Mon, Oct 19" */
export const formatDay = (ms: number, zone: string): string => format(zone, "day", { weekday: "short", month: "short", day: "numeric" }).format(ms);
/** "Monday, October 19, 2026" */
export const formatDateLong = (ms: number, zone: string): string => format(zone, "long", { weekday: "long", month: "long", day: "numeric", year: "numeric" }).format(ms);
/** "Mon, Oct 19, 9:30 AM" */
export const formatWhen = (ms: number, zone: string): string => `${formatDay(ms, zone)}, ${formatClock(ms, zone)}`;

/** A date key as text ("Mon", "19", "Oct 19"), whatever zone the viewer is in: a key has no zone. */
export const formatKey = (key: string, options: Intl.DateTimeFormatOptions): string => format("UTC", JSON.stringify(options), options).format(utcOfKey(key));

/** "Oct 19 - 25, 2026", "Oct 26 - Nov 1, 2026", "Dec 28, 2026 - Jan 3, 2027" */
export function rangeLabel(first: string, last: string): string {
  const a = formatKey(first, { month: "short", day: "numeric" });
  const year = (k: string) => k.slice(0, 4);
  if (first === last) return `${a}, ${year(first)}`;
  if (year(first) !== year(last)) return `${a}, ${year(first)} - ${formatKey(last, { month: "short", day: "numeric" })}, ${year(last)}`;
  const sameMonth = first.slice(0, 7) === last.slice(0, 7);
  return `${a} - ${sameMonth ? formatKey(last, { day: "numeric" }) : formatKey(last, { month: "short", day: "numeric" })}, ${year(last)}`;
}

/** "America/New_York (GMT-4)" */
export function zoneNote(zone: string, ms: number): string {
  try {
    const part = format(zone, "offset", { timeZoneName: "shortOffset" }).formatToParts(ms).find((p) => p.type === "timeZoneName");
    return part ? `${zone} (${part.value})` : zone;
  } catch {
    return zone;
  }
}

export const toIso = (ms: number): string => new Date(ms).toISOString();
