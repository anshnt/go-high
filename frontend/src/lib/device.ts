// Plain-words summaries for the sessions list. No imports so node can test it directly.

// Order matters: Edge and Opera also say "Chrome", Chrome also says "Safari".
const BROWSERS: [RegExp, string][] = [
  [/Edg(e|A|iOS)?\//, "Edge"],
  [/OPR\/|Opera/, "Opera"],
  [/Firefox\/|FxiOS\//, "Firefox"],
  [/Chrome\/|CriOS\//, "Chrome"],
  [/Safari\//, "Safari"],
];
// iPhone and iPad UAs also say "like Mac OS X", Android also says "Linux".
const SYSTEMS: [RegExp, string][] = [
  [/iPhone/, "iPhone"],
  [/iPad/, "iPad"],
  [/Android/, "Android"],
  [/Windows/, "Windows"],
  [/Mac OS X|Macintosh/, "macOS"],
  [/CrOS/, "ChromeOS"],
  [/Linux|X11/, "Linux"],
];
const first = (list: [RegExp, string][], ua: string) => list.find(([re]) => re.test(ua))?.[1];

/** "Chrome on Windows", "Safari on iPhone", "Firefox", or a fallback for scripts and empty values. */
export function describeDevice(userAgent: string | null | undefined): string {
  const ua = (userAgent ?? "").trim();
  if (!ua) return "Unknown device";
  if (!ua.startsWith("Mozilla/")) return "Command line or script";
  const browser = first(BROWSERS, ua);
  const system = first(SYSTEMS, ua);
  if (browser && system) return `${browser} on ${system}`;
  return browser ?? (system ? `Browser on ${system}` : "Unknown device");
}

const RTF = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["day", 86_400],
  ["hour", 3_600],
  ["minute", 60],
];

/** "Just now", "5 minutes ago", "yesterday", then a date after a month. */
export function timeAgo(iso: string, now: number = Date.now()): string {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "Unknown";
  const secs = Math.max(0, Math.round((now - then) / 1000));
  if (secs < 60) return "Just now";
  if (secs >= 30 * 86_400) return new Date(then).toLocaleDateString("en", { year: "numeric", month: "short", day: "numeric" });
  const [unit, size] = UNITS.find(([, s]) => secs >= s)!;
  return RTF.format(-Math.floor(secs / size), unit);
}

/** "15 minutes", "1 hour", "45 seconds" for a Retry-After value in seconds. */
export function waitText(seconds: number): string {
  const s = Math.max(1, Math.round(seconds));
  if (s < 60) return `${s} second${s === 1 ? "" : "s"}`;
  if (s < 3600) {
    const m = Math.ceil(s / 60);
    return `${m} minute${m === 1 ? "" : "s"}`;
  }
  const h = Math.ceil(s / 3600);
  return `${h} hour${h === 1 ? "" : "s"}`;
}
