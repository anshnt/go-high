// Where things go on the week grid: events as blocks of minutes in a day, side by side when they overlap, and working
// hours as windows. Minutes are wall clock minutes after local midnight in the viewer's zone, 0 to 1440, so the grid reads
// like the clock on a daylight saving day. No React, so node can test it.
import { WEEKDAYS, toMinutes, type Range, type Weekly } from "./hours.ts";
import { addDays, endOfDay, startOfDay, wallMinutes, weekdayOf, zonedToUtc } from "./time.ts";

/** The shortest a block is drawn, so a 5 minute booking can still be read and clicked. */
export const MIN_BLOCK = 15;
export const DAY_MINUTES = 1440;

export type Span<T> = { start: number; end: number; item: T };
export type Placed<T> = { item: T; top: number; height: number; col: number; cols: number };

/** Minutes of an instant inside the day that starts at `dayStart` and ends at `dayEnd`; the day's own edges are 0 and 1440. */
const minuteIn = (ms: number, dayStart: number, dayEnd: number, zone: string) => (ms <= dayStart ? 0 : ms >= dayEnd ? DAY_MINUTES : wallMinutes(ms, zone));

/**
 * The events that touch one local day, clipped to it (an event over midnight shows on both days), with a column each:
 * events that overlap share the width, side by side, and the rest take all of it. Input order breaks ties.
 */
export function layoutDay<T>(spans: Span<T>[], day: string, zone: string): Placed<T>[] {
  const lo = startOfDay(day, zone);
  const hi = endOfDay(day, zone);
  const blocks = spans
    .map((s, order) => ({ s, order }))
    .filter(({ s }) => s.end > lo && s.start < hi)
    .map(({ s, order }) => {
      const top = minuteIn(s.start, lo, hi, zone);
      const bottom = Math.max(minuteIn(s.end, lo, hi, zone), top + 1);
      return { item: s.item, order, top, height: Math.min(Math.max(bottom - top, MIN_BLOCK), DAY_MINUTES - top), col: 0, cols: 1 };
    })
    .sort((a, b) => a.top - b.top || b.height - a.height || a.order - b.order);

  let cluster: typeof blocks = [];
  let ends: number[] = []; // where each column of the cluster is free again
  let reach = 0;
  const close = () => {
    for (const b of cluster) b.cols = ends.length;
    cluster = [];
    ends = [];
  };
  for (const b of blocks) {
    if (cluster.length > 0 && b.top >= reach) close();
    let col = ends.findIndex((end) => end <= b.top);
    if (col < 0) col = ends.length;
    ends[col] = b.top + b.height;
    b.col = col;
    reach = cluster.length === 0 ? b.top + b.height : Math.max(reach, b.top + b.height);
    cluster.push(b);
  }
  close();
  return blocks.map(({ item, top, height, col, cols }) => ({ item, top, height, col, cols }));
}

/** `layoutDay` for each day of a week, by day key. */
export function layoutWeek<T>(spans: Span<T>[], days: string[], zone: string): Map<string, Placed<T>[]> {
  return new Map(days.map((d) => [d, layoutDay(spans, d, zone)]));
}

export type Hours = { time_zone: string; weekly: Weekly; overrides: Record<string, Range[]> };

const rangesOn = (h: Hours, day: string): Range[] => h.overrides[day] ?? h.weekly[WEEKDAYS[weekdayOf(day)]!] ?? [];

/**
 * The working windows of someone on one day of the viewer's clock, as minutes. Their hours are read in their own zone
 * (a person in London working 09:00 to 17:00 shows as 04:00 to 12:00 to a viewer in New York), so the days next to
 * this one in their zone are looked at too. Touching windows are merged.
 */
export function workWindows(hours: Hours, day: string, zone: string): [number, number][] {
  const lo = startOfDay(day, zone);
  const hi = endOfDay(day, zone);
  const out: [number, number][] = [];
  for (const k of [-1, 0, 1]) {
    const theirs = addDays(day, k);
    for (const [from, to] of rangesOn(hours, theirs)) {
      if (toMinutes(from) === null || toMinutes(to) === null) continue;
      const a = Math.max(zonedToUtc(theirs, from, hours.time_zone), lo);
      const b = Math.min(zonedToUtc(theirs, to, hours.time_zone), hi);
      if (a < b) out.push([minuteIn(a, lo, hi, zone), minuteIn(b, lo, hi, zone)]);
    }
  }
  out.sort((x, y) => x[0] - y[0]);
  const merged: [number, number][] = [];
  for (const w of out) {
    const last = merged.at(-1);
    if (last && w[0] <= last[1]) last[1] = Math.max(last[1], w[1]);
    else merged.push([w[0], w[1]]);
  }
  return merged;
}

/** The gaps between windows within the day: when nobody is working. */
export function offWindows(windows: [number, number][]): [number, number][] {
  const out: [number, number][] = [];
  let at = 0;
  for (const [a, b] of windows) {
    if (a > at) out.push([at, a]);
    at = Math.max(at, b);
  }
  if (at < DAY_MINUTES) out.push([at, DAY_MINUTES]);
  return out;
}

/** Where to scroll the grid to: the earliest working minute of the week, else 08:00. */
export function firstWorkMinute(hours: Hours | null, days: string[], zone: string): number {
  if (!hours) return 8 * 60;
  const starts = days.flatMap((d) => workWindows(hours, d, zone).map((w) => w[0]));
  return starts.length > 0 ? Math.min(...starts) : 8 * 60;
}
