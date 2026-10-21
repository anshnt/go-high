// Money on the payments screens: amounts are integers of minor units with a currency, as the API sends them. Totals,
// tax and discounts are always worked out by the server (POST /api/v1/invoices/preview); this file only turns amounts
// into text and text into amounts, exactly, with no float arithmetic on money. No React, so node can test it.
import { LOCALE, minorDigits, parseMoney } from "../records/format.ts";

export { minorDigits, parseMoney };

/** The currencies the server takes (app/payments/money.py), for pickers. */
export const CURRENCIES = ["usd", "eur", "gbp", "cad", "aud", "nzd", "chf", "sek", "nok", "dkk", "pln", "czk", "huf", "ron", "bgn", "inr", "sgd", "hkd", "mxn", "brl", "zar", "aed", "sar", "ils", "try", "php", "thb", "myr", "idr", "cny", "twd", "jpy", "krw", "vnd", "clp", "isk", "ugx"];

const formats = new Map<string, Intl.NumberFormat>();

/** 123456 usd -> "$1,234.56"; 1000 jpy -> "¥1,000". Every minor digit is shown: invoices are exact. */
export function money(amount: number, currency: string): string {
  const code = currency.toUpperCase();
  let f = formats.get(code);
  if (!f) {
    const d = minorDigits(code);
    try {
      f = new Intl.NumberFormat(LOCALE, { style: "currency", currency: code, minimumFractionDigits: d, maximumFractionDigits: d });
    } catch {
      f = new Intl.NumberFormat(LOCALE, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
    formats.set(code, f);
  }
  return f.format(amount / 10 ** minorDigits(code));
}

/** What an amount field shows while editing: "1234.50", no grouping, no symbol. */
export function toInput(amount: number | null | undefined, currency: string): string {
  if (amount === null || amount === undefined) return "";
  const d = minorDigits(currency.toUpperCase());
  if (d === 0) return String(amount);
  const sign = amount < 0 ? "-" : "";
  const abs = Math.abs(amount);
  return `${sign}${Math.floor(abs / 10 ** d)}.${String(abs % 10 ** d).padStart(d, "0")}`;
}

/** "12.5" -> 1250 for USD, or an error to show. Negative amounts and more decimals than the currency has are refused. */
export function readAmount(text: string, currency: string): { amount: number } | { error: string } {
  if (!text.trim()) return { error: "Enter an amount" };
  const minor = parseMoney(text, currency.toUpperCase());
  if (minor === null) {
    const d = minorDigits(currency.toUpperCase());
    return { error: d === 0 ? "Enter a whole amount" : `Enter an amount with at most ${d} decimals` };
  }
  if (minor < 0) return { error: "Enter a positive amount" };
  if (minor > 9_999_999_999) return { error: "That amount is too large" };
  return { amount: minor };
}

/** Basis points as a percentage: 825 -> "8.25%". */
export const percent = (bp: number) => `${(bp / 100).toLocaleString(LOCALE, { maximumFractionDigits: 2 })}%`;

/** "8.25" -> 825 basis points, or null. */
export function readPercent(text: string, max = 100): number | null {
  const m = /^\s*(\d{1,3})(?:\.(\d{1,2}))?\s*%?\s*$/.exec(text);
  if (!m) return null;
  const bp = Number(m[1]) * 100 + Number((m[2] ?? "").padEnd(2, "0"));
  return bp <= max * 100 ? bp : null;
}

/** "every month", "every 3 months", "one time". */
export function every(interval: string | null, count = 1): string {
  if (!interval) return "one time";
  return count === 1 ? `every ${interval}` : `every ${count} ${interval}s`;
}

/** A price as one line: "$20.00 every month", "Tiered, every month". */
export function priceText(p: { scheme: string; unit_amount: number | null; currency: string; type: string; interval: string | null; interval_count: number }): string {
  const amount = p.scheme === "tiered" ? "Tiered" : money(p.unit_amount ?? 0, p.currency);
  return p.type === "recurring" ? `${amount} ${every(p.interval, p.interval_count)}` : amount;
}

/** Per currency totals ({usd: 1200, eur: 300}) as one line, largest first. */
export function totalsText(sums: { currency: string; amount: number }[]): string {
  if (!sums.length) return money(0, "usd");
  return [...sums].sort((a, b) => b.amount - a.amount).map((s) => money(s.amount, s.currency)).join(" + ");
}
