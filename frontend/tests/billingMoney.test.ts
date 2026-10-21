import assert from "node:assert/strict";
import { test } from "node:test";
import { formatMoney, minorStep, moneyInput, parseMoney, parsePercent, percent } from "../src/billing/money.ts";

test("micros read as money, with sub-cent digits only when the amount has them", () => {
  assert.equal(formatMoney(15_800, "USD"), "$0.0158");
  assert.equal(formatMoney(12_500_000, "USD"), "$12.50");
  assert.equal(formatMoney(-2_000_000, "EUR"), "-€2.00");
  assert.equal(formatMoney(1_234_567_000_000, "USD"), "$1,234,567.00");
  assert.equal(formatMoney(3_000_000, "JPY"), "¥3");
  assert.equal(formatMoney(1_000, "KWD"), "KWD 0.001");
  assert.equal(formatMoney(7_900, "CHF"), "CHF 0.0079");
  assert.equal(formatMoney(0, "USD"), "$0.00");
});

test("a headline balance rounds to the minor unit", () => {
  assert.equal(formatMoney(12_345_678, "USD", { minor: true }), "$12.35");
  assert.equal(formatMoney(-4_999, "USD", { minor: true }), "$0.00"); // never "-$0.00"
  assert.equal(formatMoney(-5_000, "USD", { minor: true }), "-$0.01");
});

test("typed amounts become exact micros, whole minor units unless a price per unit is asked for", () => {
  assert.deepEqual(parseMoney("25", "USD"), { ok: true, micros: 25_000_000 });
  assert.deepEqual(parseMoney(" $1,000.5 ", "USD"), { ok: true, micros: 1_000_500_000 });
  assert.deepEqual(parseMoney(".99", "USD"), { ok: true, micros: 990_000 });
  assert.deepEqual(parseMoney("0.10", "USD"), { ok: true, micros: 100_000 });
  assert.equal(parseMoney("0.105", "USD").ok, false);
  assert.equal(parseMoney("0.1050", "USD").ok, false);
  assert.deepEqual(parseMoney("0.100", "USD"), { ok: true, micros: 100_000 }); // trailing zeros are fine
  assert.deepEqual(parseMoney("0.0079", "USD", { whole: false }), { ok: true, micros: 7_900 });
  assert.equal(parseMoney("0.0000001", "USD", { whole: false }).ok, false);
  assert.equal(parseMoney("1.5", "JPY").ok, false);
  assert.deepEqual(parseMoney("3", "JPY"), { ok: true, micros: 3_000_000 });
  assert.equal(parseMoney("-5", "USD").ok, false);
  assert.deepEqual(parseMoney("-5", "USD", { negative: true }), { ok: true, micros: -5_000_000 });
  for (const bad of ["", "abc", ".", "1.2.3", "12e3", "9999999999"]) assert.equal(parseMoney(bad, "USD").ok, false, bad);
  // 0.1 + 0.2 in floats is 0.30000000000000004; here it is string arithmetic
  assert.deepEqual(parseMoney("0.3", "USD"), { ok: true, micros: 300_000 });
});

test("an input shows what was saved, round trip", () => {
  for (const micros of [0, 10_000, 25_000_000, 7_900, 1_000_500_000]) {
    const parsed = parseMoney(moneyInput(micros, "USD"), "USD", { whole: false });
    assert.deepEqual(parsed, { ok: true, micros });
  }
  assert.equal(moneyInput(null, "USD"), "");
  assert.equal(moneyInput(25_000_000, "USD"), "25.00");
  assert.equal(minorStep("USD"), 10_000);
  assert.equal(minorStep("JPY"), 1_000_000);
});

test("markups are basis points", () => {
  assert.equal(parsePercent("25"), 2_500);
  assert.equal(parsePercent("12.5 %"), 1_250);
  assert.equal(parsePercent("-100"), -10_000);
  assert.equal(parsePercent("-0.5"), -50);
  assert.equal(parsePercent("-101"), null);
  assert.equal(parsePercent("abc"), null);
  assert.equal(percent(2_500), "25 %");
  assert.equal(percent(1_250), "12.5 %");
});
