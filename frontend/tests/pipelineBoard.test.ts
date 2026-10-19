import assert from "node:assert/strict";
import { test } from "node:test";
import { appendCards, closeRange, compactAgo, daysText, describeSums, focusTarget, formatSums, isFiltered, moneyOf, moveCard, neighbours, NO_FILTER, overdue, passes, patchCard, replaceCard, shortDay, slotFromY, summarize, sumEntries, toFullSlot, weigh } from "../src/pipeline/board.ts";
import type { BoardStage, Card } from "../src/pipeline/types.ts";

const usd = (amount: number) => ({ amount, currency: "USD" });
const card = (id: string, stage: string, money: { amount: number; currency: string } | null, extra: Partial<Card> = {}): Card => ({
  id,
  display_name: `Deal ${id}`,
  amount: money,
  close_date: null,
  owner_id: null,
  board_position: "0",
  stage_id: stage,
  stage_entered_at: "2026-10-01T00:00:00Z",
  days_in_stage: 9,
  rotting: true,
  last_activity_at: null,
  values: money ? { amount: money } : {},
  ...extra,
});
const stage = (id: string, probability: number, deals: Card[], extra: Partial<BoardStage> = {}): BoardStage => {
  const amount: Record<string, number> = {};
  for (const d of deals) if (d.amount) amount[d.amount.currency] = (amount[d.amount.currency] ?? 0) + d.amount.amount;
  return { id, pipeline_id: "p", name: id.toUpperCase(), position: 0, kind: probability === 100 ? "won" : "open", probability, rotting_days: 7, exit_rules: {}, color: null, count: deals.length, amount, weighted: Object.fromEntries(Object.entries(amount).map(([c, n]) => [c, weigh(n, probability)])), deals, next_cursor: null, ...extra };
};
const board = () => [
  stage("a", 50, [card("1", "a", usd(100_000)), card("2", "a", usd(50_000)), card("3", "a", { amount: 20_000, currency: "EUR" })]),
  stage("b", 80, [card("4", "b", usd(10_000))]),
  stage("w", 100, []),
];

test("sums are written per currency, the biggest first, and never added across currencies", () => {
  assert.deepEqual(sumEntries({ EUR: 500, USD: 900, GBP: 900 }), [["GBP", 900], ["USD", 900], ["EUR", 500]]);
  assert.equal(formatSums({ USD: 123_450, EUR: 80_000 }), "$1,235 · €800.00");
  assert.equal(formatSums({ USD: 99_950 }), "$999.50");
  assert.equal(formatSums({}), "");
  assert.equal(formatSums({ USD: 300, EUR: 200, GBP: 100, CAD: 50 }), "$3.00 · €2.00 · +2");
  assert.equal(describeSums({ USD: 100_000 }, { USD: 50_000 }), "$1,000 (weighted $500.00)");
  assert.equal(weigh(1005, 50), 503, "rounds half up like the server");
  assert.deepEqual(moneyOf({ values: { amount: usd(5) }, amount: null }), usd(5));
  assert.equal(moneyOf({ values: {}, amount: null }), null);
});

test("a drop names the cards above and below it, never the dragged card itself", () => {
  const cards = [{ id: "a" }, { id: "b" }, { id: "c" }];
  assert.deepEqual(neighbours(cards, "z", 0), { after_id: null, before_id: "a" });
  assert.deepEqual(neighbours(cards, "z", 2), { after_id: "b", before_id: "c" });
  assert.deepEqual(neighbours(cards, "z", 3), { after_id: "c", before_id: null });
  assert.deepEqual(neighbours(cards, "z", 99), { after_id: "c", before_id: null }, "past the end is the end");
  assert.deepEqual(neighbours(cards, "b", 1), { after_id: "a", before_id: "c" }, "dropping b where it is: between a and c");
  assert.deepEqual(neighbours(cards, "a", 2), { after_id: "c", before_id: null }, "slots count the column without the dragged card");
  assert.deepEqual(neighbours([], "z", 0), { after_id: null, before_id: null });
  assert.equal(slotFromY([10, 30, 50], 0), 0);
  assert.equal(slotFromY([10, 30, 50], 31), 2);
  assert.equal(slotFromY([10, 30, 50], 500), 3);
});

test("moving a card to another stage moves its count and sums, and reweighs them at the new probability", () => {
  const moved = moveCard(board(), "1", "b", 0, new Date("2026-10-18T10:00:00Z"))!;
  const [a, b] = moved.columns as [BoardStage, BoardStage];
  assert.deepEqual(a.deals.map((d) => d.id), ["2", "3"]);
  assert.deepEqual(b.deals.map((d) => d.id), ["1", "4"]);
  assert.deepEqual([a.count, b.count], [2, 2]);
  assert.deepEqual(a.amount, { USD: 50_000, EUR: 20_000 });
  assert.deepEqual(a.weighted, { USD: 25_000, EUR: 10_000 });
  assert.deepEqual(b.amount, { USD: 110_000 });
  assert.deepEqual(b.weighted, { USD: 88_000 }, "80% of 110,000");
  assert.equal(moved.card.stage_id, "b");
  assert.equal(moved.card.days_in_stage, 0);
  assert.equal(moved.card.rotting, false);
  assert.equal(moved.card.stage_entered_at, "2026-10-18T10:00:00.000Z");
  assert.deepEqual([moved.fromStage, moved.fromIndex, moved.changedStage], ["a", 0, true]);
});

test("the last card leaving a stage empties its sums, and a stage may hold none", () => {
  const moved = moveCard(board(), "4", "w", 0)!;
  const [, b, w] = moved.columns as [BoardStage, BoardStage, BoardStage];
  assert.deepEqual([b.count, b.amount, b.weighted], [0, {}, {}]);
  assert.deepEqual([w.count, w.amount, w.weighted], [1, { USD: 10_000 }, { USD: 10_000 }]);
});

test("a move inside a stage reorders it and leaves counts and sums alone", () => {
  const start = board();
  const moved = moveCard(start, "1", "a", 2)!;
  const a = moved.columns[0]!;
  assert.deepEqual(a.deals.map((d) => d.id), ["2", "3", "1"]);
  assert.equal(moved.changedStage, false);
  assert.equal(moved.card.days_in_stage, 9, "same stage, same time in it");
  assert.deepEqual([a.count, a.amount, a.weighted], [start[0]!.count, start[0]!.amount, start[0]!.weighted]);
  assert.equal(moveCard(start, "nope", "a", 0), null);
  assert.equal(moveCard(start, "1", "nope", 0), null);
});

test("the original columns are never changed", () => {
  const start = board();
  const before = JSON.stringify(start);
  moveCard(start, "1", "b", 0);
  patchCard(start, { id: "1", display_name: "x", owner_id: null, values: { amount: usd(1) } });
  assert.equal(JSON.stringify(start), before);
});

test("an edit beside the board changes the card and the column's sums by the difference", () => {
  const start = board();
  const edited = patchCard(start, { id: "2", display_name: "Renamed", owner_id: "u1", values: { amount: usd(90_000), close_date: "2026-11-02" } });
  const a = edited[0]!;
  const two = a.deals.find((d) => d.id === "2")!;
  assert.deepEqual([two.display_name, two.owner_id, two.close_date, two.amount], ["Renamed", "u1", "2026-11-02", usd(90_000)]);
  assert.deepEqual(a.amount, { USD: 190_000, EUR: 20_000 });
  assert.deepEqual(a.weighted, { USD: 95_000, EUR: 10_000 });
  assert.equal(a.count, 3);
  assert.equal(edited[1], start[1], "other columns are the same objects");
  const same = patchCard(start, { id: "2", display_name: "Deal 2", owner_id: null, values: { amount: usd(50_000) } });
  assert.equal(same, start, "nothing to change gives the same board back");
  assert.equal(patchCard(start, { id: "gone", display_name: "x", owner_id: null, values: {} }), start);
  const cleared = patchCard(start, { id: "2", display_name: "Deal 2", owner_id: null, values: {} });
  assert.deepEqual(cleared[0]!.amount, { USD: 100_000, EUR: 20_000 }, "a cleared amount leaves the sum");
});

test("the card from the server replaces the local one in place, and a page adds cards once", () => {
  const start = board();
  const swapped = replaceCard(start, card("2", "a", usd(50_000), { board_position: "-4", days_in_stage: 0 }));
  assert.deepEqual(swapped[0]!.deals.map((d) => [d.id, d.board_position]), [["1", "0"], ["2", "-4"], ["3", "0"]]);
  const more = appendCards(start, "a", [card("3", "a", null), card("9", "a", null)], "next");
  assert.deepEqual(more[0]!.deals.map((d) => d.id), ["1", "2", "3", "9"]);
  assert.equal(more[0]!.next_cursor, "next");
  assert.equal(more[1], start[1]);
});

test("arrow keys stay in a column, and left and right find the next column that has cards", () => {
  const lists = [["a1", "a2", "a3"], [], ["c1", "c2"]];
  assert.equal(focusTarget(lists, 0, 0, "down"), "a2");
  assert.equal(focusTarget(lists, 0, 2, "down"), null);
  assert.equal(focusTarget(lists, 0, 0, "up"), null);
  assert.equal(focusTarget(lists, 0, 1, "right"), "c2", "skips the empty column, same height");
  assert.equal(focusTarget(lists, 0, 2, "right"), "c2", "or the last card when the column is shorter");
  assert.equal(focusTarget(lists, 2, 0, "left"), "a1");
  assert.equal(focusTarget(lists, 2, 0, "right"), null);
  assert.equal(focusTarget(lists, 0, 0, "left"), null);
});

test("quick filters: mine, a close date this month or quarter, and a name search", () => {
  const now = new Date(2026, 9, 18); // 18 Oct 2026
  assert.deepEqual(closeRange("month", now), ["2026-10-01", "2026-10-31"]);
  assert.deepEqual(closeRange("quarter", now), ["2026-10-01", "2026-12-31"]);
  assert.deepEqual(closeRange("quarter", new Date(2026, 4, 2)), ["2026-04-01", "2026-06-30"]);
  const mine = card("1", "a", null, { owner_id: "me", close_date: "2026-10-30", display_name: "Alder Labs Growth plan" });
  const theirs = card("2", "a", null, { owner_id: "u2", close_date: "2026-12-02" });
  const undated = card("3", "a", null, { owner_id: "me" });
  assert.equal(isFiltered(NO_FILTER), false);
  assert.equal(isFiltered({ ...NO_FILTER, q: "  " }), false);
  assert.equal(passes(mine, NO_FILTER, "me", now), true);
  assert.equal(passes(theirs, { ...NO_FILTER, owner: "mine" }, "me", now), false);
  assert.equal(passes(mine, { ...NO_FILTER, owner: "mine" }, "me", now), true);
  assert.equal(passes(mine, { ...NO_FILTER, close: "month" }, "me", now), true);
  assert.equal(passes(theirs, { ...NO_FILTER, close: "month" }, "me", now), false);
  assert.equal(passes(theirs, { ...NO_FILTER, close: "quarter" }, "me", now), true);
  assert.equal(passes(undated, { ...NO_FILTER, close: "quarter" }, "me", now), false, "no close date is in no range");
  assert.equal(passes(mine, { ...NO_FILTER, q: "GROWTH" }, "me", now), true);
  assert.equal(passes(mine, { ...NO_FILTER, q: "nothing like it" }, "me", now), false);
});

test("a filtered column counts and sums what matches, and says when more pages could hold more", () => {
  const col = stage("a", 50, [card("1", "a", usd(100_000), { owner_id: "me" }), card("2", "a", usd(50_000)), card("3", "a", { amount: 20_000, currency: "EUR" }, { owner_id: "me" })], { count: 40, next_cursor: "more" });
  const everything = summarize(col, null);
  assert.deepEqual([everything.count, everything.partial, everything.deals.length], [40, false, 3], "no filter: the server's count");
  const mine = summarize(col, (c) => c.owner_id === "me");
  assert.deepEqual([mine.count, mine.partial], [2, true]);
  assert.deepEqual(mine.amount, { USD: 100_000, EUR: 20_000 });
  assert.deepEqual(mine.weighted, { USD: 50_000, EUR: 10_000 });
  const whole = summarize({ ...col, next_cursor: null, count: 3 }, (c) => c.owner_id === "me");
  assert.equal(whole.partial, false);
});

test("a slot among the shown cards is a slot among all the loaded ones when a filter hides some", () => {
  const all = [{ id: "a" }, { id: "b" }, { id: "c" }, { id: "d" }, { id: "e" }];
  const shown = [{ id: "b" }, { id: "d" }]; // a, c and e are filtered out
  assert.equal(toFullSlot(all, shown, "z", 0), 1, "above b: after a");
  assert.equal(toFullSlot(all, shown, "z", 1), 3, "above d: after c");
  assert.equal(toFullSlot(all, shown, "z", 2), 4, "below d: right after d, above the hidden e");
  assert.equal(toFullSlot(all, shown, "z", 99), 4);
  assert.equal(toFullSlot(all, [], "z", 0), 0, "nothing shown: the top");
  assert.equal(toFullSlot(all, all, "c", 1), 1, "the dragged card is not counted");
  // the neighbours that go to the server are the ones around the card it is dropped between
  assert.deepEqual(neighbours(all, "z", toFullSlot(all, shown, "z", 1)), { after_id: "c", before_id: "d" });
});

test("a card says how long ago and how long in the stage, in a few characters", () => {
  const now = Date.parse("2026-10-18T12:00:00Z");
  assert.equal(compactAgo("2026-10-18T11:59:40Z", now), "now");
  assert.equal(compactAgo("2026-10-18T11:55:00Z", now), "5m");
  assert.equal(compactAgo("2026-10-18T09:00:00Z", now), "3h");
  assert.equal(compactAgo("2026-10-16T12:00:00Z", now), "2d");
  assert.equal(compactAgo("2026-07-18T12:00:00Z", now), "3mo");
  assert.equal(compactAgo("2026-10-19T12:00:00Z", now), "now", "a clock a little ahead is not the future");
  assert.equal(compactAgo(null, now), "");
  assert.equal(compactAgo("not a date", now), "");
  assert.equal(daysText(0), "Today");
  assert.equal(daysText(12), "12d");
});

test("a close date reads short, with the year only when it is not this year, and an open deal can be overdue", () => {
  const now = new Date(2026, 9, 18);
  assert.equal(shortDay("2026-11-12", now), "Nov 12");
  assert.equal(shortDay("2027-01-17", now), "Jan 17, 2027");
  assert.equal(shortDay("nope", now), "nope");
  assert.equal(overdue("2026-10-17", now), true);
  assert.equal(overdue("2026-10-18", now), false, "today is not late yet");
  assert.equal(overdue(null, now), false);
});

