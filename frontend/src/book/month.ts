// Month and day arithmetic for the date grid, and grouping open times by day. Pure, no DOM, no clock of its own.
import { dayKey } from "./zones.ts";

export interface YM {
  year: number;
  month: number; // 1 to 12
}

/** A grid cell: a day of the month, or a blank before the 1st and after the last. */
export type Cell = { key: string; day: number } | null;

const pad = (n: number, width = 2) => String(n).padStart(width, "0");
const DAY_MS = 864e5;

export function keyOf(ym: YM, day: number): string {
  return `${pad(ym.year, 4)}-${pad(ym.month)}-${pad(day)}`;
}

export function ymOfKey(key: string): YM {
  return { year: Number(key.slice(0, 4)), month: Number(key.slice(5, 7)) };
}

export function daysIn(ym: YM): number {
  return new Date(Date.UTC(ym.year, ym.month, 0)).getUTCDate();
}

/** First and last day of a month: what the slots call asks for (at most 31 days, well under the 62 allowed). */
export function monthRange(ym: YM): { from: string; to: string } {
  return { from: keyOf(ym, 1), to: keyOf(ym, daysIn(ym)) };
}

export function stepMonth(ym: YM, by: number): YM {
  const index = ym.year * 12 + (ym.month - 1) + by;
  return { year: Math.floor(index / 12), month: (index % 12) + 1 };
}

export const sameMonth = (a: YM, b: YM) => a.year === b.year && a.month === b.month;

/** Months from a to b (positive when b is later). */
export const monthsBetween = (a: YM, b: YM) => (b.year - a.year) * 12 + (b.month - a.month);

/** 0 for Monday to 6 for Sunday. */
export function weekday(key: string): number {
  return (new Date(`${key}T00:00:00Z`).getUTCDay() + 6) % 7;
}

export function addDays(key: string, days: number): string {
  return new Date(new Date(`${key}T00:00:00Z`).getTime() + days * DAY_MS).toISOString().slice(0, 10);
}

/** The weeks of a month, Monday first, each seven cells, blanks (null) before the 1st and after the last day. */
export function monthGrid(ym: YM): Cell[][] {
  const cells: Cell[] = Array.from({ length: weekday(keyOf(ym, 1)) }, () => null);
  for (let day = 1; day <= daysIn(ym); day++) cells.push({ key: keyOf(ym, day), day });
  while (cells.length % 7) cells.push(null);
  return Array.from({ length: cells.length / 7 }, (_, w) => cells.slice(w * 7, w * 7 + 7));
}

/** Instants grouped by the day they fall on in a zone, each day's times sorted and without repeats, empty days absent. */
export function groupByDay(instants: string[], zone: string): Record<string, string[]> {
  const days: Record<string, string[]> = {};
  const stamp = (s: string) => new Date(s).getTime();
  for (const s of [...new Set(instants)].filter((s) => Number.isFinite(stamp(s))).sort((a, b) => stamp(a) - stamp(b))) {
    (days[dayKey(s, zone)] ??= []).push(s);
  }
  return days;
}

/** The slots response as the grid wants it: regrouped on this browser's clock so a day and its times always agree. */
export function normaliseDays(days: Record<string, string[]> | undefined, zone: string): Record<string, string[]> {
  return groupByDay(Object.values(days ?? {}).flat(), zone);
}
