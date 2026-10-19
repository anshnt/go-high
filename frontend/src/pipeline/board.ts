// What the board does with cards, in plain TypeScript: where a drop lands, the optimistic move with its counts and sums,
// the quick filters (applied here because the board API has none), and sums by currency in words. No React, so node
// can test it.
import { formatMoney, isMoney, parseDay, toDay } from "../records/format.ts";
import type { Money } from "../records/types.ts";
import type { BoardStage, Card, Sums } from "./types.ts";

// ---- sums ----

/** A stage's weighted amount: amount times probability, rounded half up, as the server does. */
export const weigh = (total: number, probability: number) => Math.floor((total * probability + 50) / 100);

/** The money of a card: its amount value, when it has one. */
export const moneyOf = (card: Pick<Card, "values" | "amount">): Money | null => (isMoney(card.values.amount) ? card.values.amount : isMoney(card.amount) ? card.amount : null);

/** `{USD: 123450, EUR: 80000}` as entries, the biggest first (ties by currency code). */
export const sumEntries = (sums: Sums): [string, number][] => Object.entries(sums).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));

/** Sums by currency in words, never added across currencies: "$1,235 · €800". More than `max` currencies end in "+2". */
export function formatSums(sums: Sums, max = 2): string {
  const all = sumEntries(sums);
  const shown = all.slice(0, max).map(([currency, amount]) => formatMoney({ amount, currency }));
  return all.length > max ? [...shown, `+${all.length - max}`].join(" · ") : shown.join(" · ");
}

/** Every currency, for a tooltip or a screen reader: "$1,235 (weighted $617) · €800 (weighted $320)". */
export function describeSums(amount: Sums, weighted: Sums): string {
  return sumEntries(amount)
    .map(([currency, total]) => `${formatMoney({ amount: total, currency })} (weighted ${formatMoney({ amount: weighted[currency] ?? 0, currency })})`)
    .join(" · ");
}

function addMoney(sums: Sums, money: Money | null, sign: 1 | -1): Sums {
  if (!money) return sums;
  return { ...sums, [money.currency]: (sums[money.currency] ?? 0) + sign * money.amount };
}

/** The column with one deal's money added or taken away, and its count changed by `count`. Weighted follows the amounts. */
function adjust(col: BoardStage, money: Money | null, sign: 1 | -1, count: number): BoardStage {
  const empty = col.count + count <= 0;
  const amount = empty ? {} : addMoney(col.amount, money, sign);
  const weighted = Object.fromEntries(Object.entries(amount).map(([currency, total]) => [currency, weigh(total, col.probability)]));
  return { ...col, count: Math.max(0, col.count + count), amount, weighted };
}

// ---- where a drop lands ----

/**
 * The neighbours to send with a drop. `slot` is the place among the target's cards without the dragged one (0 is the top,
 * `rest.length` the bottom of what is loaded). A card dropped at the end of a column with more pages has no `before_id`,
 * so the server puts it one step below the last card it knows of.
 */
export function neighbours(cards: Pick<Card, "id">[], dragId: string, slot: number): { after_id: string | null; before_id: string | null } {
  const rest = cards.filter((c) => c.id !== dragId);
  const at = Math.min(Math.max(slot, 0), rest.length);
  return { after_id: rest[at - 1]?.id ?? null, before_id: rest[at]?.id ?? null };
}

/**
 * A slot among the cards that are shown (the ones that pass the filters) as a slot among every loaded card: just above the
 * card it is dropped before, else just below the card it is dropped after, else the top.
 */
export function toFullSlot(all: Pick<Card, "id">[], shown: Pick<Card, "id">[], dragId: string, slot: number): number {
  const rest = shown.filter((c) => c.id !== dragId);
  const full = all.filter((c) => c.id !== dragId);
  const at = Math.min(Math.max(slot, 0), rest.length);
  const before = rest[at];
  if (before) return full.findIndex((c) => c.id === before.id);
  const after = rest[at - 1];
  return after ? full.findIndex((c) => c.id === after.id) + 1 : 0;
}

/** The slot a pointer at `y` means, given the vertical middles of the cards that are not being dragged, top to bottom. */
export const slotFromY = (middles: number[], y: number): number => middles.filter((m) => m < y).length;

// ---- the optimistic move ----

export type Moved = { columns: BoardStage[]; card: Card; fromStage: string; fromIndex: number; changedStage: boolean };

/**
 * The board after a card moves to `slot` of `toStage`: counts, sums and weighted follow, the card is "0 days in stage" and
 * not rotting there. Null when the card or the stage is not on the board.
 */
export function moveCard(columns: BoardStage[], cardId: string, toStage: string, slot: number, now = new Date()): Moved | null {
  const from = columns.find((c) => c.deals.some((d) => d.id === cardId));
  const to = columns.find((c) => c.id === toStage);
  if (!from || !to) return null;
  const fromIndex = from.deals.findIndex((d) => d.id === cardId);
  const old = from.deals[fromIndex]!;
  const changedStage = from.id !== to.id;
  const card: Card = changedStage ? { ...old, stage_id: to.id, days_in_stage: 0, rotting: false, stage_entered_at: now.toISOString() } : old;
  const money = moneyOf(old);
  const next = columns.map((col) => {
    let c = col;
    if (col.id === from.id) c = { ...c, deals: c.deals.filter((d) => d.id !== cardId) };
    if (changedStage && col.id === from.id) c = adjust(c, money, -1, -1);
    if (col.id === to.id) {
      const rest = c.deals.filter((d) => d.id !== cardId);
      const at = Math.min(Math.max(slot, 0), rest.length);
      c = { ...c, deals: [...rest.slice(0, at), card, ...rest.slice(at)] };
      if (changedStage) c = adjust(c, money, 1, 1);
    }
    return c;
  });
  return { columns: next, card, fromStage: from.id, fromIndex, changedStage };
}

/** The card the server answered with, in the place the local one had. */
export function replaceCard(columns: BoardStage[], card: Card): BoardStage[] {
  return columns.map((col) => (col.deals.some((d) => d.id === card.id) ? { ...col, deals: col.deals.map((d) => (d.id === card.id ? card : d)) } : col));
}

/** Another page of a column: new cards after the loaded ones, none twice. */
export function appendCards(columns: BoardStage[], stageId: string, deals: Card[], next: string | null): BoardStage[] {
  return columns.map((col) => {
    if (col.id !== stageId) return col;
    const have = new Set(col.deals.map((d) => d.id));
    return { ...col, deals: [...col.deals, ...deals.filter((d) => !have.has(d.id))], next_cursor: next };
  });
}

/** A card edited elsewhere (the record beside the board): its fields change in place, and the column's sums by the difference in amount. Same array back when nothing differs. */
export function patchCard(columns: BoardStage[], card: Pick<Card, "id" | "display_name" | "owner_id" | "values">): BoardStage[] {
  const col = columns.find((c) => c.deals.some((d) => d.id === card.id));
  const old = col?.deals.find((d) => d.id === card.id);
  if (!col || !old) return columns;
  const values = card.values;
  const money = isMoney(values.amount) ? values.amount : null;
  const close = typeof values.close_date === "string" ? values.close_date : null;
  const same = old.display_name === card.display_name && old.owner_id === card.owner_id && JSON.stringify(old.values) === JSON.stringify(values);
  if (same) return columns;
  const was = moneyOf(old);
  const update: Card = { ...old, display_name: card.display_name, owner_id: card.owner_id, values, amount: money, close_date: close };
  return columns.map((c) => {
    if (c.id !== col.id) return c;
    let next: BoardStage = { ...c, deals: c.deals.map((d) => (d.id === card.id ? update : d)) };
    if (JSON.stringify(was) !== JSON.stringify(money)) next = adjust(adjust(next, was, -1, 0), money, 1, 0);
    return next;
  });
}

/** Which stage a card is in, by the card's own stage id. */
export const stageOf = (columns: BoardStage[], cardId: string) => columns.find((c) => c.deals.some((d) => d.id === cardId));

// ---- keyboard ----

export type Dir = "up" | "down" | "left" | "right";

/**
 * Where focus goes from a card. `lists` has one list of card ids per column, left to right (a collapsed column has none).
 * Up and down stay in the column; left and right go to the nearest column that has cards, at the same height or the last card.
 */
export function focusTarget(lists: string[][], col: number, row: number, dir: Dir): string | null {
  if (dir === "up") return lists[col]?.[row - 1] ?? null;
  if (dir === "down") return lists[col]?.[row + 1] ?? null;
  const step = dir === "left" ? -1 : 1;
  for (let c = col + step; c >= 0 && c < lists.length; c += step) {
    const list = lists[c]!;
    if (list.length) return list[Math.min(row, list.length - 1)]!;
  }
  return null;
}

// ---- quick filters (client side: the board API has no filter) ----

export type Quick = { owner: "all" | "mine"; close: "any" | "month" | "quarter"; q: string };
export const NO_FILTER: Quick = { owner: "all", close: "any", q: "" };
export const isFiltered = (f: Quick) => f.owner !== "all" || f.close !== "any" || f.q.trim() !== "";

/** First and last day ("YYYY-MM-DD") of the month or quarter that `now` is in. */
export function closeRange(close: "month" | "quarter", now: Date): [string, string] {
  const first = close === "month" ? now.getMonth() : now.getMonth() - (now.getMonth() % 3);
  const span = close === "month" ? 1 : 3;
  return [toDay(new Date(now.getFullYear(), first, 1)), toDay(new Date(now.getFullYear(), first + span, 0))];
}

/** Does the card pass the filters? `me` is the signed-in user's id; deals with no close date never match a date range. */
export function passes(card: Card, f: Quick, me: string | undefined, now = new Date()): boolean {
  if (f.owner === "mine" && card.owner_id !== me) return false;
  if (f.close !== "any") {
    const [from, to] = closeRange(f.close, now);
    const day = card.close_date ?? (typeof card.values.close_date === "string" ? card.values.close_date : null);
    if (!day || day < from || day > to) return false;
  }
  const q = f.q.trim().toLowerCase();
  return !q || card.display_name.toLowerCase().includes(q);
}

// ---- time on a card ----

/** "now", "5m", "3h", "2d", "3mo": how long ago, in a few characters for a card's footer. */
export function compactAgo(iso: string | null, now: number): string {
  const then = iso ? Date.parse(iso) : NaN;
  if (Number.isNaN(then)) return "";
  const minutes = Math.max(0, Math.round((now - then) / 60_000));
  if (minutes < 1) return "now";
  if (minutes < 60) return `${minutes}m`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)}h`;
  const days = Math.floor(minutes / 1440);
  return days < 30 ? `${days}d` : `${Math.floor(days / 30)}mo`;
}

/** "Today", or "12d": the days a deal has been in its stage. */
export const daysText = (days: number) => (days <= 0 ? "Today" : `${days}d`);

const SHORT_DAY = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });
/** "Nov 12", with the year when it is not this year: a close date on a card. */
export function shortDay(day: string, now: Date): string {
  const d = parseDay(day);
  if (!d) return day;
  return d.getFullYear() === now.getFullYear() ? SHORT_DAY.format(d) : `${SHORT_DAY.format(d)}, ${d.getFullYear()}`;
}

/** Is the close date of an open deal already behind us? */
export const overdue = (day: string | null, now: Date) => !!day && day < toDay(now);

export type Shown = { deals: Card[]; count: number; amount: Sums; weighted: Sums; partial: boolean };

/** What a column shows: all of it, or what passes the filters. Counts and sums are the server's until a filter is on; then they are the matching loaded cards', and `partial` says more pages could hold more. */
export function summarize(col: BoardStage, keep: ((c: Card) => boolean) | null): Shown {
  if (!keep) return { deals: col.deals, count: col.count, amount: col.amount, weighted: col.weighted, partial: false };
  const deals = col.deals.filter(keep);
  let amount: Sums = {};
  for (const d of deals) amount = addMoney(amount, moneyOf(d), 1);
  const weighted = Object.fromEntries(Object.entries(amount).map(([currency, total]) => [currency, weigh(total, col.probability)]));
  return { deals, count: deals.length, amount, weighted, partial: col.next_cursor !== null };
}
