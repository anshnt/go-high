// Dates for tasks: typing "tomorrow" or "next mon" into the quick add, bucketing a task as overdue, today or upcoming,
// and short labels. No imports, so the node tests can load it. Everything here is the reader's local time, except
// that an all-day task is due on a date (the API keeps it as midnight UTC of that date).

export type Bucket = "overdue" | "today" | "upcoming" | "none";
export type Parsed = { title: string; due: Date | null; allDay: boolean; phrase: string | null };
export type Due = { due_at: string | null; all_day: boolean; status?: "open" | "done" };

export const DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
export const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const short = (name: string) => name.slice(0, 3).toLowerCase();

export const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
export const addDays = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n, d.getHours(), d.getMinutes());
export const sameDay = (a: Date, b: Date) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
const pad = (n: number) => String(n).padStart(2, "0");

/** "2026-10-19", for a date input. */
export const toInputDate = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
export const fromInputDate = (s: string) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : null;
};
/** "15:30", for a time input. */
export const toInputTime = (d: Date) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;

// --- typing a due date -------------------------------------------------------------------------------------------

type Clock = { h: number; m: number };

const TIME = [
  /(?:\s+at)?\s+(\d{1,2})(?::(\d{2}))?\s?(am|pm)$/i,
  /(?:\s+at)?\s+(\d{1,2}):(\d{2})$/,
  /(?:\s+at)?\s+(noon)$/i,
];

function takeTime(text: string): { rest: string; clock: Clock } | null {
  for (const re of TIME) {
    const m = re.exec(text);
    if (!m) continue;
    if (m[1] === "noon") return { rest: text.slice(0, m.index), clock: { h: 12, m: 0 } };
    let h = Number(m[1]);
    const min = Number(m[2] ?? 0);
    const meridiem = m[3]?.toLowerCase();
    if (meridiem && (h < 1 || h > 12)) return null;
    if (!meridiem && h > 23) return null;
    if (min > 59) return null;
    if (meridiem === "pm" && h < 12) h += 12;
    if (meridiem === "am" && h === 12) h = 0;
    return { rest: text.slice(0, m.index), clock: { h, m: min } };
  }
  return null;
}

const dayPattern = [...DAY_NAMES.map((n) => n.toLowerCase()), "tues", "weds", "thurs", ...DAY_NAMES.map((n) => short(n))].join("|");
const monthPattern = [...MONTH_NAMES.map((n) => n.toLowerCase()), "sept", ...MONTH_NAMES.map((n) => short(n))].join("|");
const monthIndex = (name: string) => MONTH_NAMES.findIndex((n) => n.toLowerCase().startsWith(name.slice(0, 3).toLowerCase()));
const dayIndex = (name: string) => DAY_NAMES.findIndex((n) => n.toLowerCase().startsWith(name.slice(0, 3).toLowerCase()));

/** The weekday after today; with `next`, in the following calendar week (weeks start on Monday). */
function weekday(today: Date, dow: number, next: boolean): Date {
  if (!next) return addDays(today, (dow - today.getDay() + 7) % 7 || 7);
  const monday = addDays(today, (8 - today.getDay()) % 7 || 7);
  return addDays(monday, (dow + 6) % 7);
}

const IN_UNITS: Record<string, number> = { minute: 1, min: 1, hour: 60, hr: 60, day: 1440, week: 10080, wk: 10080 };

type Match = { date: Date; relative?: boolean };
const PHRASES: { re: RegExp; at: (m: RegExpExecArray, now: Date, today: Date) => Match | null }[] = [
  { re: /(?:^|\s)(today)$/i, at: (_m, _n, today) => ({ date: today }) },
  { re: /(?:^|\s)(tomorrow|tmrw|tmr)$/i, at: (_m, _n, today) => ({ date: addDays(today, 1) }) },
  { re: /(?:^|\s)(next week)$/i, at: (_m, _n, today) => ({ date: addDays(today, (8 - today.getDay()) % 7 || 7) }) },
  { re: /(?:^|\s)(next month)$/i, at: (_m, _n, today) => ({ date: new Date(today.getFullYear(), today.getMonth() + 1, 1) }) },
  {
    re: new RegExp(`(?:^|\\s)(next )?(${dayPattern})$`, "i"),
    at: (m, _n, today) => ({ date: weekday(today, dayIndex(m[2]!), !!m[1]) }),
  },
  {
    re: /(?:^|\s)in (\d{1,3}) ?(minutes?|mins?|hours?|hrs?|days?|weeks?|wks?)$/i,
    at: (m, now, today) => {
      const unit = IN_UNITS[m[2]!.toLowerCase().replace(/s$/, "")]!;
      if (unit < 1440) return { date: new Date(now.getTime() + Number(m[1]) * unit * 60_000), relative: true };
      return { date: addDays(today, (Number(m[1]) * unit) / 1440) };
    },
  },
  {
    re: /(?:^|\s)(\d{4})-(\d{2})-(\d{2})$/,
    at: (m) => {
      const d = fromInputDate(`${m[1]}-${m[2]}-${m[3]}`);
      return d && d.getMonth() === Number(m[2]) - 1 ? { date: d } : null;
    },
  },
  {
    re: new RegExp(`(?:^|\\s)(${monthPattern})\\.? (\\d{1,2})(?:st|nd|rd|th)?$`, "i"),
    at: (m, _n, today) => onDate(today, monthIndex(m[1]!), Number(m[2])),
  },
  {
    re: new RegExp(`(?:^|\\s)(\\d{1,2})(?:st|nd|rd|th)? (${monthPattern})\\.?$`, "i"),
    at: (m, _n, today) => onDate(today, monthIndex(m[2]!), Number(m[1])),
  },
];

/** A month and day, this year or, when that has passed, next year. */
function onDate(today: Date, month: number, day: number): Match | null {
  let d = new Date(today.getFullYear(), month, day);
  if (d.getMonth() !== month) return null; // 31 Feb
  if (d < today) d = new Date(today.getFullYear() + 1, month, day);
  return { date: d };
}

const LEAD = /(?:^|\s+)(?:due|on|by|for|at)$/i;

/**
 * Splits "Call Ada tomorrow at 3pm" into the title and a due date. The phrase must end the text: today, tomorrow,
 * a weekday ("mon", "next mon"), "next week", "in 3 days", "in 2 hours", "oct 25", "25 oct", "2026-10-25", each with
 * an optional time ("at 3pm", "15:30", "noon"). A time alone means the next time it is that time. Without a time the
 * task is all day. Text that is nothing but a phrase stays a title.
 */
export function parseDue(input: string, now: Date): Parsed {
  const text = input.trim().replace(/\s+/g, " ");
  const plain: Parsed = { title: text, due: null, allDay: true, phrase: null };
  const today = startOfDay(now);
  const withTime = takeTime(text);
  const body = withTime ? withTime.rest : text;
  const timeText = withTime ? text.slice(body.length).trim() : "";
  let found: { match: Match; title: string; phrase: string } | null = null;
  for (const { re, at } of PHRASES) {
    const m = re.exec(body);
    if (!m) continue;
    const match = at(m, now, today);
    if (!match) continue;
    found = { match, title: body.slice(0, m.index), phrase: m[0].trim() };
    break;
  }
  const clean = (s: string) => s.replace(LEAD, "").trim();
  if (found) {
    const title = clean(found.title);
    if (!title) return plain;
    const { date, relative } = found.match;
    const phrase = [found.phrase, timeText].filter(Boolean).join(" ");
    if (relative) return { title, due: date, allDay: false, phrase };
    if (withTime) return { title, due: new Date(date.getFullYear(), date.getMonth(), date.getDate(), withTime.clock.h, withTime.clock.m), allDay: false, phrase };
    return { title, due: date, allDay: true, phrase };
  }
  if (withTime) {
    const title = clean(body);
    if (!title) return plain;
    let due = new Date(today.getFullYear(), today.getMonth(), today.getDate(), withTime.clock.h, withTime.clock.m);
    if (due <= now) due = addDays(due, 1);
    return { title, due, allDay: false, phrase: timeText };
  }
  return plain;
}

// --- a task's due date ---------------------------------------------------------------------------------------------

/** The due date as a local Date: an all-day task at local midnight of its date, a timed one at its time. */
export function dueDate(t: Due): Date | null {
  if (!t.due_at) return null;
  const d = new Date(t.due_at);
  return t.all_day ? new Date(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()) : d;
}

/** What the API takes for a due date: an all-day task is midnight UTC of its date, a timed one an instant. */
export const dueIso = (d: Date, allDay: boolean) =>
  (allDay ? new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate())) : d).toISOString();

/** Overdue (open, and its time or date has passed), due today, due later, or no date. */
export function bucketOf(t: Due, now: Date): Bucket {
  const due = dueDate(t);
  if (!due) return "none";
  const today = startOfDay(now);
  const day = startOfDay(due);
  const late = t.all_day ? day < today : due < now;
  if (late) return t.status === "done" ? "today" : "overdue";
  return day.getTime() === today.getTime() ? "today" : "upcoming";
}

export function timeLabel(d: Date): string {
  const h = d.getHours() % 12 || 12;
  return `${h}:${pad(d.getMinutes())} ${d.getHours() < 12 ? "AM" : "PM"}`;
}

/** "Today", "Tomorrow", "Yesterday", "Mon, Oct 19", "Oct 19, 2027", plus the time of a timed task. */
export function dueLabel(t: Due, now: Date): string {
  const due = dueDate(t);
  if (!due) return "No date";
  const today = startOfDay(now);
  const days = Math.round((startOfDay(due).getTime() - today.getTime()) / 86_400_000);
  const month = MONTH_NAMES[due.getMonth()]!.slice(0, 3);
  const date =
    days === 0 ? "Today" : days === 1 ? "Tomorrow" : days === -1 ? "Yesterday"
    : days > 1 && days < 7 ? DAY_NAMES[due.getDay()]!
    : due.getFullYear() === today.getFullYear() ? `${DAY_NAMES[due.getDay()]!.slice(0, 3)}, ${month} ${due.getDate()}`
    : `${month} ${due.getDate()}, ${due.getFullYear()}`;
  return t.all_day ? date : `${date}, ${timeLabel(due)}`;
}
