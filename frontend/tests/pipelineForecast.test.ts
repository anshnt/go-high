import assert from "node:assert/strict";
import { test } from "node:test";
import { compactMoney, currencies, labelOf, layers, nameOf, niceTicks, ownerRows, rows, span, sumRows } from "../src/pipeline/forecast.ts";
import { buildForecast } from "../src/pipeline/memoryClient.ts";
import type { Forecast, ForecastPeriod, Metrics, Stage } from "../src/pipeline/types.ts";
import type { RecordRow } from "../src/records/types.ts";

const m = (over: Partial<Metrics> = {}): Metrics => ({ pipeline: {}, best_case: {}, commit: {}, weighted: {}, won: {}, ...over });
const period = (start: string, label: string, over: Partial<Metrics>, owners: ForecastPeriod["owners"] = []): ForecastPeriod => ({ label, start, end: start, ...m(over), owners });

// October: 1,000 won; open 3,000 of which 2,000 is best case and 1,200 of that is commit. December: only EUR.
const forecast = (): Forecast => ({
  period: "month",
  periods: [
    period("2026-10-01", "2026-10", { won: { USD: 100_000 }, pipeline: { USD: 300_000 }, best_case: { USD: 200_000 }, commit: { USD: 120_000 }, weighted: { USD: 150_000 } }, [
      { owner_id: "u1", ...m({ won: { USD: 100_000 }, pipeline: { USD: 200_000 }, best_case: { USD: 200_000 }, commit: { USD: 120_000 }, weighted: { USD: 130_000 } }) },
      { owner_id: null, ...m({ pipeline: { USD: 100_000 }, weighted: { USD: 20_000 } }) },
    ]),
    period("2026-12-01", "2026-12", { pipeline: { EUR: 50_000, USD: 10_000 }, weighted: { EUR: 25_000, USD: 1_000 } }, [{ owner_id: "u1", ...m({ pipeline: { EUR: 50_000 }, weighted: { EUR: 25_000 } }) }]),
  ],
});

test("the layers of a stack do not overlap: each is what the next one up does not hold", () => {
  const oct = layers(forecast().periods[0]!, "USD");
  assert.deepEqual(oct, { won: 100_000, commit: 120_000, best: 80_000, pipeline: 100_000, total: 400_000, weighted: 150_000 });
  assert.equal(oct.won + oct.commit + oct.best + oct.pipeline, 100_000 + 300_000, "won plus the whole open pipeline");
  assert.deepEqual(layers(m(), "USD"), { won: 0, commit: 0, best: 0, pipeline: 0, total: 0, weighted: 0 });
  // a currency that only has some metrics never goes negative
  assert.equal(layers(m({ best_case: { USD: 5 } }), "USD").pipeline, 0);
});

test("currencies are listed by money, never added together", () => {
  assert.deepEqual(currencies(forecast()), ["USD", "EUR"]);
  assert.deepEqual(currencies({ period: "month", periods: [] }), []);
  const eur = rows(forecast(), "EUR");
  assert.deepEqual(eur.map((r) => r.total), [0, 0, 50_000]);
  assert.deepEqual(rows(forecast(), "USD").map((r) => r.total), [400_000, 0, 10_000]);
});

test("a quiet month between two busy ones is an empty row, and quarters count in threes", () => {
  const f = forecast();
  assert.deepEqual(rows(f, "USD").map((r) => [r.label, r.name]), [["2026-10", "Oct 2026"], ["2026-11", "Nov 2026"], ["2026-12", "Dec 2026"]]);
  assert.deepEqual(span(["2026-10-01", "2027-04-01"], "quarter"), ["2026-10-01", "2027-01-01", "2027-04-01"]);
  assert.deepEqual(span(["2026-12-01", "2027-02-01"], "month"), ["2026-12-01", "2027-01-01", "2027-02-01"]);
  assert.deepEqual(span([], "month"), []);
  assert.equal(labelOf("2026-10-01", "quarter"), "2026-Q4");
  assert.equal(labelOf("2026-01-01", "quarter"), "2026-Q1");
  assert.equal(nameOf("2026-10-01", "quarter"), "Q4 2026");
  const q = rows({ period: "quarter", periods: [period("2026-07-01", "2026-Q3", { won: { USD: 5 } }), period("2026-10-01", "2026-Q4", { won: { USD: 7 } })] }, "USD");
  assert.deepEqual(q.map((r) => [r.label, r.won]), [["2026-Q3", 5], ["2026-Q4", 7]]);
  assert.deepEqual(sumRows(rows(f, "USD")), { won: 100_000, commit: 120_000, best: 80_000, pipeline: 110_000, total: 410_000, weighted: 151_000 });
});

test("the owner breakdown is per period or all of them, biggest first, and leaves out owners with nothing in the currency", () => {
  const f = forecast();
  const all = ownerRows(f, "USD", null);
  assert.deepEqual(all.map((o) => [o.owner_id, o.total, o.weighted]), [["u1", 300_000, 130_000], [null, 100_000, 20_000]]);
  assert.deepEqual(ownerRows(f, "USD", "2026-12").map((o) => o.owner_id), [], "u1 has no dollars in December");
  assert.deepEqual(ownerRows(f, "EUR", "2026-12").map((o) => [o.owner_id, o.pipeline]), [["u1", 50_000]]);
  assert.deepEqual(ownerRows(f, "EUR", null).map((o) => o.owner_id), ["u1"]);
  assert.deepEqual(ownerRows(f, "USD", "2030-01"), []);
});

test("axis ticks are clean numbers that reach the biggest bar", () => {
  assert.deepEqual(niceTicks(0), [0, 1]);
  assert.deepEqual(niceTicks(95), [0, 25, 50, 75, 100]);
  const t = niceTicks(1_234_000);
  assert.ok(t[t.length - 1]! >= 1_234_000);
  assert.ok(t.length <= 7);
  assert.deepEqual(niceTicks(400_000), [0, 100_000, 200_000, 300_000, 400_000]);
  assert.deepEqual(niceTicks(9), [0, 5, 10], "whole units only");
  assert.equal(compactMoney(0, "USD"), "$0");
  assert.equal(compactMoney(45_000_00, "USD"), "$45K");
  assert.equal(compactMoney(1_250_000_00, "USD"), "$1.3M");
  assert.equal(compactMoney(80_000_00, "EUR"), "€80K");
  assert.equal(compactMoney(5_000, "JPY"), "¥5K");
});

// ---- the demo works the same figures out from its deals ----

const stage = (id: string, kind: Stage["kind"], probability: number): Stage => ({ id, pipeline_id: "p", name: id, position: 0, kind, probability, rotting_days: null, exit_rules: {}, color: null });
const deal = (id: string, stageId: string, amount: number | null, close: string | null, owner: string | null, currency = "USD"): RecordRow => ({
  id,
  object: "deal",
  display_name: id,
  values: { stage: stageId, ...(amount === null ? {} : { amount: { amount, currency } }), ...(close ? { close_date: close } : {}) },
  owner_id: owner,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  tags: [],
});

test("the demo's forecast follows the server's rules: open by probability, won apart, lost and undated left out", () => {
  const stages = [stage("lead", "open", 10), stage("prop", "open", 50), stage("nego", "open", 80), stage("won", "won", 100), stage("lost", "lost", 0)];
  const deals = [
    deal("a", "lead", 1000, "2026-10-05", "u1"),
    deal("b", "prop", 2000, "2026-10-20", "u1"),
    deal("c", "nego", 3000, "2026-10-31", "u2"),
    deal("d", "won", 4000, "2026-10-02", "u2"),
    deal("e", "lost", 9999, "2026-10-02", "u2"),
    deal("f", "prop", 7777, null, "u1"),
    deal("g", "prop", null, "2026-10-09", "u1"),
    deal("h", "nego", 500, "2026-11-01", null, "EUR"),
  ];
  const month = buildForecast(deals, stages, "month");
  assert.deepEqual(month.periods.map((p) => p.label), ["2026-10", "2026-11"]);
  const oct = month.periods[0]!;
  assert.deepEqual([oct.start, oct.end], ["2026-10-01", "2026-10-31"]);
  assert.deepEqual(oct.pipeline, { USD: 6000 });
  assert.deepEqual(oct.best_case, { USD: 5000 });
  assert.deepEqual(oct.commit, { USD: 3000 });
  assert.deepEqual(oct.won, { USD: 4000 });
  assert.deepEqual(oct.weighted, { USD: 100 + 1000 + 2400 }, "10% of 1,000, 50% of 2,000, 80% of 3,000");
  assert.deepEqual(oct.owners.map((o) => [o.owner_id, o.pipeline.USD ?? 0, o.won.USD ?? 0]), [["u1", 3000, 0], ["u2", 3000, 4000]]);
  assert.deepEqual(month.periods[1]!.owners.map((o) => o.owner_id), [null], "unowned deals are their own row, last");
  assert.deepEqual(month.periods[1]!.commit, { EUR: 500 });
  const quarter = buildForecast(deals, stages, "quarter");
  assert.deepEqual(quarter.periods.map((p) => [p.label, p.start, p.end]), [["2026-Q4", "2026-10-01", "2026-12-31"]]);
  assert.deepEqual(quarter.periods[0]!.pipeline, { USD: 6000, EUR: 500 });
  assert.deepEqual(buildForecast([], stages, "month").periods, []);
});
