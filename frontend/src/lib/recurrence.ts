// How a task repeats, in the plain words people use, and back to the rule the API stores (the same subset of RRULE as
// the backend: FREQ, INTERVAL, BYDAY for weeks, BYMONTHDAY for months, and COUNT or UNTIL). No imports, so the node
// tests can load it.

export type Freq = "DAILY" | "WEEKLY" | "MONTHLY";
export type Rule = { freq: Freq; interval: number; byday: string[]; bymonthday: number | null; count: number | null; until: string | null };
export type Preset = "none" | "daily" | "weekdays" | "weekly" | "biweekly" | "monthly" | "custom";

export const WEEKDAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"];
const WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WORKDAYS = WEEKDAYS.slice(0, 5);

export const ordinal = (n: number) => {
  const tens = n % 100;
  const suffix = tens >= 11 && tens <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th";
  return `${n}${suffix}`;
};

const num = (s: string | undefined) => (s !== undefined && /^-?\d+$/.test(s) ? Number(s) : null);

/** The rule in the API's text form, or null when there is none or it is not one this page understands. */
export function parseRule(text: string | null | undefined): Rule | null {
  if (!text) return null;
  const parts = new Map<string, string>();
  for (const item of text.replace(/^RRULE:/i, "").split(";")) {
    const [key, value] = item.split("=");
    if (!key || !value) return null;
    parts.set(key.toUpperCase(), value.toUpperCase());
  }
  const freq = parts.get("FREQ");
  if (freq !== "DAILY" && freq !== "WEEKLY" && freq !== "MONTHLY") return null;
  const byday = parts.has("BYDAY") ? parts.get("BYDAY")!.split(",") : [];
  if (byday.some((d) => !WEEKDAYS.includes(d))) return null;
  const until = parts.get("UNTIL");
  return {
    freq,
    interval: num(parts.get("INTERVAL")) ?? 1,
    byday: [...new Set(byday)].sort((a, b) => WEEKDAYS.indexOf(a) - WEEKDAYS.indexOf(b)),
    bymonthday: num(parts.get("BYMONTHDAY")),
    count: num(parts.get("COUNT")),
    until: until && /^\d{8}/.test(until) ? until.slice(0, 8) : null,
  };
}

/** The API's text form of a rule. */
export function ruleText(r: Rule): string {
  const items: [string, string | number | null][] = [
    ["FREQ", r.freq],
    ["INTERVAL", r.interval !== 1 ? r.interval : null],
    ["BYDAY", r.freq === "WEEKLY" && r.byday.length ? r.byday.join(",") : null],
    ["BYMONTHDAY", r.freq === "MONTHLY" ? r.bymonthday : null],
    ["COUNT", r.count],
    ["UNTIL", r.count === null ? r.until : null],
  ];
  return items.filter(([, v]) => v !== null).map(([k, v]) => `${k}=${v}`).join(";");
}

const every = (n: number, unit: string) => (n === 1 ? `Every ${unit}` : `Every ${n} ${unit}s`);

/** "Every day", "Every weekday", "Every 2 weeks on Mon", "Monthly on the 1st", "Does not repeat". */
export function summarize(text: string | null | undefined): string {
  if (!text) return "Does not repeat";
  const r = parseRule(text);
  if (!r) return "Repeats";
  let base: string;
  if (r.freq === "DAILY") {
    base = every(r.interval, "day");
  } else if (r.freq === "WEEKLY") {
    if (r.interval === 1 && r.byday.join() === WORKDAYS.join()) base = "Every weekday";
    else if (r.interval === 1 && r.byday.join() === "SA,SU") base = "Every weekend";
    else base = `${every(r.interval, "week")}${r.byday.length ? ` on ${r.byday.map((d) => WEEKDAY_NAMES[WEEKDAYS.indexOf(d)]).join(", ")}` : ""}`;
  } else {
    const day = r.bymonthday === null ? "" : r.bymonthday === -1 ? " on the last day" : ` on the ${ordinal(r.bymonthday)}`;
    base = r.interval === 1 ? `Monthly${day}` : `${every(r.interval, "month")}${day}`;
  }
  if (r.count !== null) return `${base}, ${r.count} times`;
  if (r.until) {
    const y = Number(r.until.slice(0, 4));
    const m = Number(r.until.slice(4, 6));
    const d = Number(r.until.slice(6, 8));
    return `${base}, until ${MONTHS[m - 1]} ${d}, ${y}`;
  }
  return base;
}

const dayOf = (due: Date | null) => (due ? WEEKDAYS[(due.getDay() + 6) % 7]! : "MO");

/** The rule a preset means for a task due on `due` (weekly repeats on its weekday, monthly on its day of the month). */
export function ruleFor(preset: Preset, due: Date | null): string | null {
  const base: Rule = { freq: "DAILY", interval: 1, byday: [], bymonthday: null, count: null, until: null };
  switch (preset) {
    case "daily": return ruleText(base);
    case "weekdays": return ruleText({ ...base, freq: "WEEKLY", byday: WORKDAYS });
    case "weekly": return ruleText({ ...base, freq: "WEEKLY", byday: [dayOf(due)] });
    case "biweekly": return ruleText({ ...base, freq: "WEEKLY", interval: 2, byday: [dayOf(due)] });
    case "monthly": return ruleText({ ...base, freq: "MONTHLY", bymonthday: due ? due.getDate() : 1 });
    default: return null;
  }
}

/** The preset that says the same as a stored rule; anything else, or a rule with an end, is custom. */
export function presetOf(text: string | null | undefined, due: Date | null): Preset {
  if (!text) return "none";
  const r = parseRule(text);
  if (!r) return "custom";
  // a weekly rule without days repeats on the due date's weekday, a monthly one without a day on its day
  const implied: Rule = {
    ...r,
    byday: r.freq === "WEEKLY" && !r.byday.length ? [dayOf(due)] : r.byday,
    bymonthday: r.freq === "MONTHLY" && r.bymonthday === null && due ? due.getDate() : r.bymonthday,
  };
  const same = (p: Preset) => ruleText(parseRule(ruleFor(p, due))!) === ruleText(implied);
  return (["daily", "weekdays", "weekly", "biweekly", "monthly"] as const).find(same) ?? "custom";
}

export const PRESETS: { id: Preset; label: string }[] = [
  { id: "none", label: "Does not repeat" },
  { id: "daily", label: "Every day" },
  { id: "weekdays", label: "Every weekday" },
  { id: "weekly", label: "Every week" },
  { id: "biweekly", label: "Every 2 weeks" },
  { id: "monthly", label: "Every month" },
  { id: "custom", label: "Custom" },
];
