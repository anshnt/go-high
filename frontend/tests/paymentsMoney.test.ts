import assert from "node:assert/strict";
import { test } from "node:test";
import { invoiceName, paymentState, subActions } from "../src/payments/meta.ts";
import { every, money, percent, priceText, readAmount, readPercent, toInput, totalsText } from "../src/payments/money.ts";

test("amounts are shown with every minor digit, in the currency's own unit", () => {
  assert.equal(money(123456, "usd"), "$1,234.56");
  assert.equal(money(5, "USD"), "$0.05");
  assert.equal(money(1000, "jpy"), "¥1,000");
  assert.equal(money(-250, "eur"), "-€2.50");
});

test("amount fields read exactly, refuse what the currency cannot hold, and round trip", () => {
  assert.deepEqual(readAmount("12.5", "usd"), { amount: 1250 });
  assert.deepEqual(readAmount("1,234.56", "usd"), { amount: 123456 });
  assert.deepEqual(readAmount("0.1", "usd"), { amount: 10 }); // 0.1 + 0.2 style float drift never happens: strings only
  assert.ok("error" in readAmount("1.234", "usd"));
  assert.ok("error" in readAmount("12.5", "jpy"));
  assert.ok("error" in readAmount("-1", "usd"));
  assert.ok("error" in readAmount("", "usd"));
  assert.ok("error" in readAmount("abc", "usd"));
  assert.ok("error" in readAmount("100000000000", "usd"));
  for (const [amount, currency] of [[1250, "usd"], [5, "usd"], [1000, "jpy"], [0, "eur"]] as const) {
    assert.deepEqual(readAmount(toInput(amount, currency), currency), { amount });
  }
  assert.equal(toInput(-205, "usd"), "-2.05");
});

test("percentages are basis points", () => {
  assert.equal(readPercent("8.25"), 825);
  assert.equal(readPercent("20%"), 2000);
  assert.equal(readPercent("100"), 10000);
  assert.equal(readPercent("100.01"), null);
  assert.equal(readPercent("8.255"), null);
  assert.equal(percent(825), "8.25%");
  assert.equal(percent(2000), "20%");
});

test("prices and totals read as one line", () => {
  assert.equal(every(null), "one time");
  assert.equal(every("month"), "every month");
  assert.equal(every("week", 2), "every 2 weeks");
  const base = { currency: "usd", type: "recurring", interval: "month", interval_count: 1 };
  assert.equal(priceText({ ...base, scheme: "fixed", unit_amount: 2000 }), "$20.00 every month");
  assert.equal(priceText({ ...base, scheme: "tiered", unit_amount: null }), "Tiered every month");
  assert.equal(priceText({ ...base, type: "one_time", interval: null, scheme: "fixed", unit_amount: 999 }), "$9.99");
  assert.equal(totalsText([{ currency: "eur", amount: 100 }, { currency: "usd", amount: 5000 }]), "$50.00 + €1.00");
  assert.equal(totalsText([]), "$0.00");
});

test("states and actions", () => {
  assert.equal(paymentState({ status: "succeeded", amount: 100, amount_refunded: 100 }).label, "Refunded");
  assert.equal(paymentState({ status: "succeeded", amount: 100, amount_refunded: 1 }).label, "Partly refunded");
  assert.equal(paymentState({ status: "failed", amount: 100, amount_refunded: 0 }).label, "Failed");
  assert.deepEqual(subActions({ status: "active", cancel_at_period_end: false }), { cancelAtEnd: true, cancelNow: true, reactivate: false, change: true });
  assert.deepEqual(subActions({ status: "active", cancel_at_period_end: true }), { cancelAtEnd: false, cancelNow: true, reactivate: true, change: true });
  assert.deepEqual(subActions({ status: "canceled", cancel_at_period_end: false }), { cancelAtEnd: false, cancelNow: false, reactivate: false, change: false });
  assert.equal(subActions({ status: "unpaid", cancel_at_period_end: false }).reactivate, true);
  assert.equal(invoiceName({ number: null, status: "draft", billing_reason: "manual" }), "Draft");
  assert.equal(invoiceName({ number: "INV-0002", status: "paid", billing_reason: "manual" }), "INV-0002");
  assert.equal(invoiceName({ number: null, status: "void", billing_reason: "payment_link" }), "Checkout");
});
