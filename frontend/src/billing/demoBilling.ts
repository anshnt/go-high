// Billing and usage in the public demo (VITE_DEMO=1): a wallet with a month of fictional usage, answered from memory in
// the shapes of the real API. Top-ups go through a pretend card (a token starting with pm_fake_decline is declined, as
// with the server's fake provider), settings and rate cards save, and the preview prices what you ask. Nothing leaves
// the browser. ponytail: state lives for the page load; the usage summary is computed from the in-memory ledger.
import { DemoMiss } from "../lib/demoTasks";
import type { Entry, EntryKind, Meter, RateCard, Topup, Wallet } from "./api";

type Json = Record<string, unknown>;
const USD = 1_000_000;
const DAY = 86_400_000;
const METERS: [string, string, string, string, number][] = [
  ["sms.segment", "SMS", "segment", "segments", 7_900],
  ["email.message", "Email", "email", "emails", 400],
  ["whatsapp.message", "WhatsApp", "message", "messages", 5_000],
  ["call.minute", "Calls", "minute", "minutes", 14_000],
  ["ai.credit", "AI", "credit", "credits", 10_000],
  ["workflow.premium_action", "Premium workflow actions", "action", "actions", 10_000],
];
const meta = (m: string) => METERS.find((x) => x[0] === m)!;

let seeded = false;
let wallet: Wallet;
const ledger: Entry[] = []; // oldest first
const topups: Topup[] = [];
let cards: RateCard[] = [];
let counter = 0;
const id = (p: string) => `demo-${p}-${++counter}`;

function priceOf(meter: string): { unit_cost: number; unit_price: number; basis: string; rate_card_id: string | null } {
  const cost = meta(meter)[4];
  const card = cards.find((c) => c.meter === meter && c.currency === wallet.currency && c.scope === "workspace") ?? cards.find((c) => c.meter === meter && c.currency === wallet.currency && c.scope === "organization");
  if (!card) return { unit_cost: cost, unit_price: cost, basis: "cost", rate_card_id: null };
  if (card.price !== null) return { unit_cost: cost, unit_price: card.price, basis: "price", rate_card_id: card.id };
  return { unit_cost: cost, unit_price: Math.round((cost * (10_000 + (card.markup_bp ?? 0))) / 10_000), basis: "markup", rate_card_id: card.id };
}

function push(e: Omit<Entry, "id" | "balance_after" | "currency" | "reverses_id" | "actor_type" | "actor_id" | "subject_type" | "subject_id">, at: number) {
  wallet.balance += e.amount;
  ledger.push({ ...e, id: id("entry"), balance_after: wallet.balance, currency: wallet.currency, reverses_id: null, actor_type: "user", actor_id: "demo-user", subject_type: null, subject_id: null, created_at: new Date(at).toISOString() });
}

function use(meter: string, quantity: number, at: number) {
  const p = priceOf(meter);
  const [, label, one, many] = meta(meter);
  push({ kind: "usage", meter, quantity, unit_price: p.unit_price, price: p.unit_price * quantity, amount: -p.unit_price * quantity, unit_cost: p.unit_cost, cost: p.unit_cost * quantity, source: "inbox", description: `${label}: ${quantity} ${quantity === 1 ? one : many}`, created_at: "" }, at);
}

function seed() {
  if (seeded) return;
  seeded = true;
  const now = Date.now();
  const first = new Date(Date.UTC(new Date().getUTCFullYear(), new Date().getUTCMonth(), 1)).getTime();
  wallet = {
    workspace_id: "demo-ws-1", currency: "USD", balance: 0, mode: "prepaid", credit_limit: null, available: 0, low_balance_at: 10 * USD, auto_recharge: true, recharge_below: 5 * USD, recharge_amount: 50 * USD,
    payment_method: "…4242", monthly_cap: 150 * USD, cap_alert_pct: 80, month_spent: 0, month_start: new Date(first).toISOString(), status: "ok", minor_unit: 10_000, provider: "fake", updated_at: new Date(now).toISOString(),
  };
  cards = [{ id: id("card"), meter: "sms.segment", scope: "organization", org_id: "demo-org", brand_id: null, workspace_id: null, currency: "USD", price: null, markup_bp: 2_500, created_at: new Date(first).toISOString(), updated_at: new Date(first).toISOString() }];
  const start = Math.min(first, now - 10 * DAY);
  push({ kind: "topup", meter: null, quantity: 0, unit_price: 0, price: 0, amount: 100 * USD, source: "api", description: "Top-up (by hand)", created_at: "" }, start + 3_600_000);
  topups.push({ id: id("topup"), amount: 100 * USD, currency: "USD", status: "succeeded", trigger: "manual", provider: "fake", provider_ref: "fake_ch_demo", error: null, created_at: new Date(start + 3_600_000).toISOString(), completed_at: new Date(start + 3_600_000).toISOString() });
  let rnd = 7;
  const next = () => (rnd = (rnd * 9301 + 49297) % 233280) / 233280;
  for (let t = start + DAY / 2; t < now - 3_600_000; t += DAY / 3) {
    use("sms.segment", 4 + Math.floor(next() * 40), t);
    if (next() > 0.4) use("email.message", 20 + Math.floor(next() * 200), t + 600_000);
    if (next() > 0.7) use("whatsapp.message", 1 + Math.floor(next() * 12), t + 1_200_000);
    if (next() > 0.8) use("ai.credit", 5 + Math.floor(next() * 30), t + 1_800_000);
  }
  const failed = [...ledger].reverse().find((e) => e.kind === "usage" && e.meter === "sms.segment");
  if (failed) push({ kind: "reversal", meter: failed.meter, quantity: failed.quantity, unit_price: failed.unit_price, price: failed.price, amount: failed.price, source: "inbox", description: "Refund: the message was not sent (HTTP 400: Invalid To number)", created_at: "" }, now - 1_800_000);
  refresh();
}

function refresh() {
  const since = Date.parse(wallet.month_start);
  wallet.month_spent = -ledger.filter((e) => (e.kind === "usage" || e.kind === "reversal") && Date.parse(e.created_at) >= since).reduce((s, e) => s + e.amount, 0);
  wallet.available = wallet.mode === "prepaid" ? wallet.balance : wallet.credit_limit === null ? null : wallet.balance + wallet.credit_limit;
  wallet.status =
    wallet.monthly_cap !== null && wallet.month_spent >= wallet.monthly_cap
      ? "capped"
      : wallet.mode === "prepaid" && wallet.balance <= 0
        ? "empty"
        : wallet.balance < 0 || (wallet.low_balance_at !== null && wallet.balance < wallet.low_balance_at)
          ? "low"
          : "ok";
}

const out = (e: Entry) => structuredClone(e);

/** The CSV the export button downloads in the demo. */
export function demoExport(): string {
  seed();
  const dec = (m: number) => `${m < 0 ? "-" : ""}${Math.floor(Math.abs(m) / USD)}.${String(Math.abs(m) % USD).padStart(6, "0")}`;
  return ["created_at,kind,meter,description,quantity,unit_price,price,amount,balance_after,currency", ...[...ledger].reverse().map((e) => [e.created_at, e.kind, e.meter ?? "", `"${e.description.replace(/"/g, '""')}"`, e.quantity, dec(e.unit_price), dec(e.price), dec(e.amount), dec(e.balance_after), e.currency].join(","))].join("\n");
}

/** The answer for a billing or usage call; undefined when the path is not one. */
export function demoBilling(method: string, path: string, body: unknown): unknown {
  const [url, qs] = path.split("?");
  if (!/^\/api\/v1\/(billing|usage)\//.test(url!)) return undefined;
  seed();
  const q = new URLSearchParams(qs ?? "");
  const input = (body ?? {}) as Json;
  const route = `${method} ${url}`;
  if (route === "GET /api/v1/billing/wallet") return structuredClone(wallet);
  if (route === "PATCH /api/v1/billing/wallet") {
    const fields: Record<string, string> = {};
    for (const k of ["low_balance_at", "recharge_below", "recharge_amount", "monthly_cap", "credit_limit"] as const) {
      const v = input[k];
      if (typeof v === "number" && v % 10_000 !== 0) fields[k] = "must be a whole number of USD minor units";
    }
    if (input.auto_recharge === true && !(input.recharge_amount ?? wallet.recharge_amount)) fields.recharge_amount = "is required for auto-recharge";
    if (Object.keys(fields).length) throw new DemoMiss(422, "The settings are not valid", "validation_failed", fields);
    const { payment_method, ...rest } = input;
    Object.assign(wallet, rest);
    if (payment_method !== undefined) {
      wallet.payment_method = typeof payment_method === "string" ? `…${payment_method.slice(-4)}` : null;
      if (!wallet.payment_method) wallet.auto_recharge = false;
    }
    wallet.updated_at = new Date().toISOString();
    refresh();
    return structuredClone(wallet);
  }
  if (route === "GET /api/v1/billing/ledger") {
    const kind = q.get("kind") as EntryKind | null;
    const meter = q.get("meter");
    const from = q.get("from");
    const to = q.get("to");
    const rows = [...ledger].reverse().filter((e) => (!kind || e.kind === kind) && (!meter || e.meter === meter) && (!from || e.created_at.slice(0, 10) >= from) && (!to || e.created_at.slice(0, 10) <= to));
    const start = Number(q.get("cursor") ?? 0);
    const limit = Number(q.get("limit") ?? 50);
    const page = rows.slice(start, start + limit);
    return { data: page.map(out), next_cursor: start + limit < rows.length ? String(start + limit) : null };
  }
  if (route === "GET /api/v1/billing/usage") {
    const from = q.get("from") ?? wallet.month_start.slice(0, 10);
    const to = q.get("to");
    const group = (q.get("group") ?? "day") as "day" | "month";
    const rows = ledger.filter((e) => (e.kind === "usage" || e.kind === "reversal") && e.created_at.slice(0, 10) >= from && (!to || e.created_at.slice(0, 10) <= to));
    const by = new Map<string, { meter: string; label: string; quantity: number; price: number; cost: number }>();
    const series = new Map<string, { period: string; price: number; meters: Record<string, unknown> }>();
    for (const e of rows) {
      const sign = e.kind === "usage" ? 1 : -1;
      const m = by.get(e.meter!) ?? { meter: e.meter!, label: meta(e.meter!)[1], quantity: 0, price: 0, cost: 0 };
      m.quantity += sign * e.quantity;
      m.price -= e.amount;
      m.cost += sign * (e.cost ?? 0);
      by.set(e.meter!, m);
      const key = group === "day" ? `${e.created_at.slice(0, 10)}T00:00:00Z` : `${e.created_at.slice(0, 7)}-01T00:00:00Z`;
      const s = series.get(key) ?? { period: key, price: 0, meters: {} };
      s.price -= e.amount;
      series.set(key, s);
    }
    const meters = [...by.values()].sort((a, b) => a.meter.localeCompare(b.meter));
    return { currency: wallet.currency, from, to, group, price: meters.reduce((s, m) => s + m.price, 0), cost: meters.reduce((s, m) => s + m.cost, 0), meters, series: [...series.values()].sort((a, b) => a.period.localeCompare(b.period)) };
  }
  if (route === "GET /api/v1/billing/topups") return { data: structuredClone([...topups].reverse()), next_cursor: null };
  if (route === "POST /api/v1/billing/topups") {
    const amount = Number(input.amount);
    if (!Number.isInteger(amount) || amount < USD || amount > 10_000 * USD || amount % 10_000 !== 0) throw new DemoMiss(422, "The top-up is not valid", "validation_failed", { amount: "must be between $1.00 and $10,000.00 in whole cents" });
    if (!wallet.payment_method) throw new DemoMiss(422, "Add a payment method before topping up", "no_payment_method");
    const now = new Date().toISOString();
    const declined = wallet.payment_method.toLowerCase().includes("0002");
    const t: Topup = { id: id("topup"), amount, currency: wallet.currency, status: declined ? "failed" : "succeeded", trigger: "manual", provider: "fake", provider_ref: declined ? null : `fake_ch_${counter}`, error: declined ? "The card was declined" : null, created_at: now, completed_at: now };
    topups.push(t);
    if (!declined) push({ kind: "topup", meter: null, quantity: 0, unit_price: 0, price: 0, amount, source: "api", description: "Top-up (by hand)", created_at: "" }, Date.now());
    refresh();
    return { ...structuredClone(t), wallet: structuredClone(wallet) };
  }
  if (route === "GET /api/v1/billing/meters") {
    return { data: METERS.map(([meter, label, unit, units]): Meter => ({ meter, label, unit, units, currency: wallet.currency, ...priceOf(meter) })) };
  }
  if (route === "GET /api/v1/billing/rate-cards") return { data: structuredClone(cards) };
  if (route === "POST /api/v1/billing/rate-cards") {
    if (cards.some((c) => c.meter === input.meter && c.scope === input.scope && c.currency === input.currency)) throw new DemoMiss(409, "That meter already has a rate card at this level and currency; change it instead", "rate_card_exists");
    const now = new Date().toISOString();
    const card: RateCard = { id: id("card"), meter: String(input.meter), scope: input.scope as RateCard["scope"], org_id: "demo-org", brand_id: input.scope === "brand" ? "demo-brand" : null, workspace_id: input.scope === "workspace" ? "demo-ws-1" : null, currency: String(input.currency), price: (input.price as number | null) ?? null, markup_bp: (input.markup_bp as number | null) ?? null, created_at: now, updated_at: now };
    cards.push(card);
    return structuredClone(card);
  }
  const one = /^\/api\/v1\/billing\/rate-cards\/([^/]+)$/.exec(url!);
  if (one) {
    const card = cards.find((c) => c.id === one[1]);
    if (!card) throw new DemoMiss(404, "Rate card not found");
    if (method === "DELETE") {
      cards = cards.filter((c) => c !== card);
      return null; // handled: undefined would mean "not a billing call"
    }
    if ("price" in input) Object.assign(card, { price: input.price ?? null, markup_bp: null });
    if ("markup_bp" in input) Object.assign(card, { markup_bp: input.markup_bp ?? null, price: null });
    card.updated_at = new Date().toISOString();
    return structuredClone(card);
  }
  throw new DemoMiss(501, "This is not available in the demo. Run go-high yourself for the full product.");
}
