// Time zone and clock helpers for the booking page. Pure: no DOM, only Intl, so node can test them.

// Used when the browser cannot list its zones (Intl.supportedValuesOf is missing or throws).
export const FALLBACK_ZONES = [
  "UTC", "Europe/London", "Europe/Dublin", "Europe/Lisbon", "Europe/Paris", "Europe/Berlin", "Europe/Madrid",
  "Europe/Rome", "Europe/Amsterdam", "Europe/Athens", "Europe/Helsinki", "Europe/Istanbul", "Europe/Moscow",
  "Africa/Cairo", "Africa/Lagos", "Africa/Nairobi", "Africa/Johannesburg", "Asia/Dubai", "Asia/Karachi",
  "Asia/Kolkata", "Asia/Dhaka", "Asia/Bangkok", "Asia/Singapore", "Asia/Hong_Kong", "Asia/Shanghai", "Asia/Tokyo",
  "Asia/Seoul", "Australia/Perth", "Australia/Sydney", "Pacific/Auckland", "Pacific/Honolulu", "America/Anchorage",
  "America/Los_Angeles", "America/Denver", "America/Chicago", "America/New_York", "America/Toronto",
  "America/Halifax", "America/Mexico_City", "America/Bogota", "America/Sao_Paulo", "America/Argentina/Buenos_Aires",
];

const formats = new Map<string, Intl.DateTimeFormat>();

function format(locale: string | undefined, zone: string, options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const key = `${locale ?? ""}|${zone}|${JSON.stringify(options)}`;
  let f = formats.get(key);
  if (!f) {
    f = new Intl.DateTimeFormat(locale, { ...options, timeZone: zone });
    formats.set(key, f);
  }
  return f;
}

export function isZone(name: string): boolean {
  try {
    new Intl.DateTimeFormat("en", { timeZone: name });
    return true;
  } catch {
    return false;
  }
}

export function detectZone(): string {
  try {
    const name = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return name && isZone(name) ? name : "UTC";
  } catch {
    return "UTC";
  }
}

/** Every zone the browser knows (or the fallback list), plus UTC and any extra names, sorted, no duplicates. */
export function listZones(extra: string[] = []): string[] {
  let known: string[];
  try {
    known = Intl.supportedValuesOf("timeZone");
    if (!known.length) known = FALLBACK_ZONES;
  } catch {
    known = FALLBACK_ZONES;
  }
  return [...new Set([...known, "UTC", ...extra.filter(isZone)])].sort();
}

/** "America/New_York" -> { region: "America", city: "New York" }; "UTC" has no region. */
export function splitZone(zone: string): { region: string; city: string } {
  const i = zone.indexOf("/");
  const city = (i < 0 ? zone : zone.slice(i + 1)).replaceAll("_", " ");
  return { region: i < 0 ? "" : zone.slice(0, i), city };
}

/** The calendar day an instant falls on in a zone, as YYYY-MM-DD. */
export function dayKey(instant: string | Date, zone: string): string {
  const d = typeof instant === "string" ? new Date(instant) : instant;
  const parts = format("en-US", zone, { year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(d);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

export function todayKey(zone: string, now: Date = new Date()): string {
  return dayKey(now, zone);
}

export function isToday(key: string, zone: string, now: Date = new Date()): boolean {
  return key === todayKey(zone, now);
}

/** "2:00 PM" or "14:00", by the visitor's locale. */
export function formatTime(instant: string | Date, zone: string, locale?: string): string {
  const d = typeof instant === "string" ? new Date(instant) : instant;
  const cycle = format(locale, zone, { hour: "numeric" }).resolvedOptions().hourCycle;
  const hour = cycle === "h23" || cycle === "h24" ? "2-digit" : "numeric"; // 09:00 in 24 hour locales, 9:00 AM in 12 hour ones
  return format(locale, zone, { hour, minute: "2-digit" }).format(d);
}

/** "Tuesday, 3 November 2026" for an instant in a zone. */
export function formatDate(instant: string | Date, zone: string, locale?: string): string {
  const d = typeof instant === "string" ? new Date(instant) : instant;
  return format(locale, zone, { weekday: "long", day: "numeric", month: "long", year: "numeric" }).format(d);
}

/** A YYYY-MM-DD day (no zone: it is a day on a wall calendar) as "Tuesday 3 November" or with the options given. */
export function formatKey(key: string, options: Intl.DateTimeFormatOptions, locale?: string): string {
  return format(locale, "UTC", options).format(new Date(`${key}T00:00:00Z`));
}

export function formatDay(key: string, locale?: string): string {
  return formatKey(key, { weekday: "long", day: "numeric", month: "long" }, locale);
}

/** "November 2026" for a month (1 to 12). */
export function monthLabel(year: number, month: number, locale?: string): string {
  return format(locale, "UTC", { month: "long", year: "numeric" }).format(new Date(Date.UTC(year, month - 1, 1)));
}

/** "Mon" ... "Sun", Monday first, for the column headings. */
export function weekdayLabels(style: "short" | "narrow" | "long" = "short", locale?: string): string[] {
  const monday = Date.UTC(2024, 0, 1); // a Monday
  return Array.from({ length: 7 }, (_, i) => format(locale, "UTC", { weekday: style }).format(new Date(monday + i * 864e5)));
}

/** A short offset such as "GMT+1" (or "GMT" at zero) for a zone at a moment; the moment matters across daylight saving. */
export function offsetLabel(zone: string, at: Date = new Date(), locale: string = "en"): string {
  try {
    const parts = format(locale, zone, { timeZoneName: "shortOffset" }).formatToParts(at);
    const name = parts.find((p) => p.type === "timeZoneName")?.value ?? "GMT";
    return name.replace(/[+-]0(:00)?$/, ""); // some engines say "GMT+0" at zero
  } catch {
    return "GMT";
  }
}

/** The wall clock in a zone right now, "Tue 14:05". */
export function clockLabel(zone: string, now: Date = new Date(), locale?: string): string {
  return format(locale, zone, { weekday: "short", hour: "numeric", minute: "2-digit" }).format(now);
}

export const zoneName = (zone: string) => zone.replaceAll("_", " ");
