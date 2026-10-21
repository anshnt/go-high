// Money on the billing screens. The API speaks integer micros (millionths of the currency's major unit, README "Usage
// ledger and wallet"), so a 0.79 cent SMS segment is 7900 and nothing is ever a float on the wire. Amounts are turned into
// text here and typed amounts back into micros with string arithmetic, never through a JavaScript number with a fraction.
// Pure: no DOM, no Vite, tested in node.

export const MICROS = 1_000_000;
const EXPONENTS: Record<string, number> = { JPY: 0, KRW: 0, VND: 0, CLP: 0, ISK: 0, UGX: 0, XAF: 0, XOF: 0, BHD: 3, KWD: 3, OMR: 3, JOD: 3, TND: 3 };
const SYMBOLS: Record<string, string> = { USD: "$", EUR: "€", GBP: "£", CAD: "CA$", AUD: "A$", NZD: "NZ$", INR: "₹", JPY: "¥", BRL: "R$", MXN: "MX$", ZAR: "R", SGD: "S$" };
export const CURRENCIES = ["USD", "EUR", "GBP", "CAD", "AUD", "NZD", "INR", "SGD", "AED", "ZAR", "BRL", "MXN", "CHF", "SEK", "NOK", "DKK", "PLN", "JPY", "KWD"];

export const exponent = (currency: string) => EXPONENTS[currency] ?? 2;
/** Micros in one minor unit (10 000 for a cent). */
export const minorStep = (currency: string) => MICROS / 10 ** exponent(currency);

/**
 * "$12.50", "-$0.0158", "¥3". At least the currency's minor digits, more when the amount has them (up to six), so a
 * sub-cent price is never shown as $0.00. `minor: true` rounds to the minor unit for a headline balance.
 */
export function formatMoney(micros: number, currency: string, opts: { minor?: boolean } = {}): string {
  let value = Math.abs(Math.trunc(micros));
  const exp = exponent(currency);
  if (opts.minor) {
    const step = minorStep(currency);
    value = Math.round(value / step) * step; // whole minor units: a balance in the header
  }
  const sign = micros < 0 && value > 0 ? "-" : "";
  const whole = Math.floor(value / MICROS);
  const frac = String(value % MICROS).padStart(6, "0");
  const places = Math.max(exp, frac.replace(/0+$/, "").length);
  const digits = `${whole.toLocaleString("en-US")}${places ? `.${frac.slice(0, places)}` : ""}`;
  const symbol = SYMBOLS[currency];
  return symbol ? `${sign}${symbol}${digits}` : `${sign}${currency} ${digits}`;
}

/** For an input's value: "12.50" (no symbol, no grouping), or "" for null. */
export function moneyInput(micros: number | null | undefined, currency: string): string {
  if (micros === null || micros === undefined) return "";
  const exp = exponent(currency);
  const sign = micros < 0 ? "-" : "";
  const value = Math.abs(micros);
  const frac = String(value % MICROS).padStart(6, "0");
  const places = Math.max(exp, frac.replace(/0+$/, "").length);
  return `${sign}${Math.floor(value / MICROS)}${places ? `.${frac.slice(0, places)}` : ""}`;
}

export type Parsed = { ok: true; micros: number } | { ok: false; error: string };

/**
 * A typed amount in major units ("12.5", "1,000", "$3") as micros. `whole` (the default) asks for whole minor units, as
 * top-ups, caps and alerts are; a price per unit may have six decimals. `negative` allows a minus sign (an adjustment).
 */
export function parseMoney(text: string, currency: string, opts: { whole?: boolean; negative?: boolean } = {}): Parsed {
  const whole = opts.whole ?? true;
  const cleaned = text.trim().replace(/[\s,]/g, "").replace(/^([-+]?)[^\d.-]+/, "$1");
  const m = /^([-+]?)(\d*)(?:\.(\d*))?$/.exec(cleaned);
  if (!cleaned || !m || (!m[2] && !m[3])) return { ok: false, error: "Enter an amount, like 25.00" };
  if (m[1] === "-" && !opts.negative) return { ok: false, error: "The amount cannot be negative" };
  const decimals = m[3] ?? "";
  const allowed = whole ? exponent(currency) : 6;
  if (decimals.replace(/0+$/, "").length > allowed) {
    return { ok: false, error: allowed === 0 ? `${currency} has no decimals` : `Use at most ${allowed} decimal${allowed === 1 ? "" : "s"}` };
  }
  const intPart = m[2] || "0";
  if (intPart.length > 9) return { ok: false, error: "The amount is too large" };
  const micros = Number(intPart) * MICROS + Number(decimals.padEnd(6, "0").slice(0, 6) || "0");
  return { ok: true, micros: m[1] === "-" ? -micros : micros };
}

/** "25 %" from basis points (2500), "-100 %" for free. */
export const percent = (bp: number) => `${(bp / 100).toLocaleString("en-US", { maximumFractionDigits: 2 })} %`;

/** Basis points from a typed percentage ("25", "12.5"); null when it is not one. */
export function parsePercent(text: string): number | null {
  const m = /^\s*(-?\d{1,5})(?:\.(\d{1,2}))?\s*%?\s*$/.exec(text);
  if (!m) return null;
  const size = Math.abs(Number(m[1])) * 100 + Number((m[2] ?? "").padEnd(2, "0"));
  const bp = m[1].startsWith("-") ? -size : size;
  return bp >= -10_000 && bp <= 1_000_000 ? bp : null;
}
