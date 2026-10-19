// Days and times in the inbox, in the reader's own time zone. Pure: no DOM, no Vite, so node tests it.
import { addDays, DAY_NAMES, MONTH_NAMES, sameDay, startOfDay, timeLabel } from "../lib/dates.ts";

const pad = (n: number) => String(n).padStart(2, "0");
/** "2026-10-18": sorts as the days do. */
export const dayKey = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

/** "Today", "Yesterday", "Mon, Oct 12" this year, "Oct 12, 2025" before. */
export function dayLabel(d: Date, now: Date): string {
  const days = Math.round((startOfDay(d).getTime() - startOfDay(now).getTime()) / 86_400_000);
  if (days === 0) return "Today";
  if (days === -1) return "Yesterday";
  const month = MONTH_NAMES[d.getMonth()]!.slice(0, 3);
  return d.getFullYear() === now.getFullYear() ? `${DAY_NAMES[d.getDay()]!.slice(0, 3)}, ${month} ${d.getDate()}` : `${month} ${d.getDate()}, ${d.getFullYear()}`;
}

/** The time on a message bubble: "2:05 PM". */
export const clock = (iso: string) => timeLabel(new Date(iso));

/** The time on a list row: the clock today, "Yesterday", the weekday this week, else "Oct 3" (with the year before this one). */
export function listTime(iso: string, now: Date): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const days = Math.round((startOfDay(now).getTime() - startOfDay(d).getTime()) / 86_400_000);
  if (days <= 0) return timeLabel(d);
  if (days === 1) return "Yesterday";
  if (days < 7) return DAY_NAMES[d.getDay()]!.slice(0, 3);
  const month = MONTH_NAMES[d.getMonth()]!.slice(0, 3);
  return d.getFullYear() === now.getFullYear() ? `${month} ${d.getDate()}` : `${month} ${d.getDate()}, ${d.getFullYear()}`;
}

export type DayGroup<T> = { key: string; label: string; items: T[] };

/**
 * Messages in the order the server stored them (by `seq`), under the day they happened. A message never goes back a
 * day: a provider's clock that runs behind would otherwise print "Oct 3, Oct 4, Oct 3" down the page.
 */
export function groupByDay<T extends { occurred_at: string }>(messages: T[], now: Date): DayGroup<T>[] {
  const groups: DayGroup<T>[] = [];
  for (const m of messages) {
    const at = new Date(m.occurred_at);
    let key = Number.isNaN(at.getTime()) ? "" : dayKey(at);
    const last = groups[groups.length - 1];
    if (last && (key === "" || key < last.key)) key = last.key;
    if (last && last.key === key) {
      last.items.push(m);
    } else {
      groups.push({ key, label: key ? dayLabel(at, now) : "Earlier", items: [m] });
    }
  }
  return groups;
}

export type SnoozePreset = { id: "hour" | "tomorrow" | "week"; label: string; at: Date };

/** The quick choices for snoozing: in an hour, tomorrow at 9:00, next Monday at 9:00. */
export function snoozePresets(now: Date): SnoozePreset[] {
  const nineAt = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate(), 9, 0);
  const toMonday = ((8 - now.getDay()) % 7) || 7; // days until the next Monday, never today
  return [
    { id: "hour", label: "In 1 hour", at: new Date(Math.ceil((now.getTime() + 3_600_000) / 60_000) * 60_000) },
    { id: "tomorrow", label: "Tomorrow", at: nineAt(addDays(now, 1)) },
    { id: "week", label: "Next week", at: nineAt(addDays(now, toMonday)) },
  ];
}

/** "Mon, Oct 19, 9:00 AM" (the day named like a list does, with the clock). */
export function whenLabel(d: Date, now: Date): string {
  const day = sameDay(d, now) ? "Today" : dayLabel(d, now);
  return `${day}, ${timeLabel(d)}`;
}

/** A browser `datetime-local` value ("2026-10-19T09:00") for a Date, and back. */
export const toLocalInput = (d: Date) => `${dayKey(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
export const fromLocalInput = (s: string): Date | null => {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(s);
  if (!m) return null;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4]), Number(m[5]));
  return Number.isNaN(d.getTime()) ? null : d;
};
