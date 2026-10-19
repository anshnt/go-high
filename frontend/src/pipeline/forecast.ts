// The forecast as the screen draws it: one row per month or quarter in one currency, split into the four layers of a
// stacked bar, plus the weighted figure and the per owner breakdown. No React, so node can test it.
//
// The server's metrics nest: `commit` is inside `best_case`, which is inside `pipeline`. A stack needs layers that do not
// overlap, so each layer here is what the next one up does not already hold: Won, Commit, Best case beyond commit, and
// Pipeline beyond best case. Their sum is won plus the whole open pipeline.
import { minorDigits, parseDay, toDay } from "../records/format.ts";
import type { Forecast, ForecastPeriod, Metrics, Period, Sums } from "./types.ts";

export type Layer = "won" | "commit" | "best" | "pipeline";
export const LAYERS: { key: Layer; label: string; note: string }[] = [
  { key: "won", label: "Won", note: "Deals in won stages" },
  { key: "commit", label: "Commit", note: "Open deals in stages of 80% or more" },
  { key: "best", label: "Best case", note: "Open deals in stages of 50% to 79%" },
  { key: "pipeline", label: "Pipeline", note: "Every other open deal" },
];

export type Row = { label: string; name: string; start: string; won: number; commit: number; best: number; pipeline: number; total: number; weighted: number };

const at = (sums: Sums, currency: string) => sums[currency] ?? 0;
const positive = (n: number) => Math.max(0, n);

/** One period's layers in one currency, in minor units. */
export function layers(m: Metrics, currency: string): Omit<Row, "label" | "name" | "start"> {
  const won = at(m.won, currency);
  const commit = at(m.commit, currency);
  const best = positive(at(m.best_case, currency) - commit);
  const pipeline = positive(at(m.pipeline, currency) - at(m.best_case, currency));
  return { won, commit, best, pipeline, total: won + commit + best + pipeline, weighted: at(m.weighted, currency) };
}

/** Every currency in the forecast, the one with the most money first. Money is never added across currencies. */
export function currencies(f: Forecast): string[] {
  const totals = new Map<string, number>();
  for (const p of f.periods)
    for (const sums of [p.won, p.pipeline, p.best_case, p.commit, p.weighted])
      for (const code of Object.keys(sums)) totals.set(code, totals.get(code) ?? 0);
  for (const code of totals.keys()) totals.set(code, f.periods.reduce((n, p) => n + at(p.won, code) + at(p.pipeline, code), 0));
  return [...totals.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([code]) => code);
}

const MONTHS = new Intl.DateTimeFormat("en-US", { month: "short", year: "numeric" });
/** "2026-10" and "2026-Q4" for a period that starts on `start`, as the server labels them. */
export const labelOf = (start: string, period: Period): string => {
  const d = parseDay(start)!;
  return period === "month" ? start.slice(0, 7) : `${d.getFullYear()}-Q${Math.floor(d.getMonth() / 3) + 1}`;
};
/** "Oct 2026" and "Q4 2026". */
export function nameOf(start: string, period: Period): string {
  const d = parseDay(start);
  if (!d) return start;
  return period === "month" ? MONTHS.format(d) : `Q${Math.floor(d.getMonth() / 3) + 1} ${d.getFullYear()}`;
}

/** Period starts from the first to the last one the server sent, so a quiet month shows as an empty bar instead of vanishing. */
export function span(starts: string[], period: Period): string[] {
  if (!starts.length) return [];
  const sorted = [...starts].sort();
  const step = period === "month" ? 1 : 3;
  const first = parseDay(sorted[0]!)!;
  const last = sorted[sorted.length - 1]!;
  const out: string[] = [];
  for (let i = 0; i < 400; i++) {
    const day = toDay(new Date(first.getFullYear(), first.getMonth() + i * step, 1));
    out.push(day);
    if (day >= last) break;
  }
  return out;
}

/** The rows of the chart and table: one per period, empty ones included, in one currency. */
export function rows(f: Forecast, currency: string): Row[] {
  const byStart = new Map(f.periods.map((p) => [p.start, p]));
  return span(f.periods.map((p) => p.start), f.period).map((start) => {
    const p = byStart.get(start);
    const base = { label: labelOf(start, f.period), name: nameOf(start, f.period), start };
    return p ? { ...base, ...layers(p, currency) } : { ...base, won: 0, commit: 0, best: 0, pipeline: 0, total: 0, weighted: 0 };
  });
}

export function sumRows(list: Row[]): Omit<Row, "label" | "name" | "start"> {
  const out = { won: 0, commit: 0, best: 0, pipeline: 0, total: 0, weighted: 0 };
  for (const r of list) for (const k of Object.keys(out) as (keyof typeof out)[]) out[k] += r[k];
  return out;
}

export type OwnerRow = Omit<Row, "label" | "name" | "start"> & { owner_id: string | null };

/**
 * The breakdown by owner, for one period (`label`) or all of them, the biggest first. Each owner's layers are worked out
 * per period and then added, so they match the rows above. Owners with nothing in this currency are left out.
 */
export function ownerRows(f: Forecast, currency: string, label: string | null): OwnerRow[] {
  const total = new Map<string | null, ReturnType<typeof sumRows>>();
  const periods: ForecastPeriod[] = label ? f.periods.filter((p) => p.label === label) : f.periods;
  for (const p of periods)
    for (const o of p.owners) {
      const row = layers(o, currency);
      const have = total.get(o.owner_id) ?? sumRows([]);
      total.set(o.owner_id, { won: have.won + row.won, commit: have.commit + row.commit, best: have.best + row.best, pipeline: have.pipeline + row.pipeline, total: have.total + row.total, weighted: have.weighted + row.weighted });
    }
  return [...total.entries()]
    .filter(([, r]) => r.total > 0 || r.weighted > 0)
    .map(([owner_id, r]) => ({ owner_id, ...r }))
    .sort((a, b) => b.total - a.total || String(a.owner_id).localeCompare(String(b.owner_id)));
}

// ---- the axis ----

/** Clean tick values from 0 up to at least `max`: 1, 2 or 5 times a power of ten, about four steps. */
export function niceTicks(max: number, steps = 4): number[] {
  if (!(max > 0)) return [0, 1];
  const raw = max / steps;
  const power = 10 ** Math.floor(Math.log10(raw));
  const unit = [1, 2, 5, 10].find((u) => u * power >= raw)! * power;
  const count = Math.ceil(max / unit);
  return Array.from({ length: count + 1 }, (_, i) => i * unit);
}

const compactFormats = new Map<string, Intl.NumberFormat>();
/** "$1.2M", "$450K", "$0": an axis label or a tight cell. Whole amounts from a thousand up, like formatMoney. */
export function compactMoney(minor: number, currency: string): string {
  let f = compactFormats.get(currency);
  if (!f) {
    try {
      f = new Intl.NumberFormat("en-US", { style: "currency", currency, notation: "compact", maximumFractionDigits: 1 });
    } catch {
      f = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 1 });
    }
    compactFormats.set(currency, f);
  }
  return f.format(minor / 10 ** minorDigits(currency));
}
