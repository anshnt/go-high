// What the browser checks before it sends an answer, so most mistakes are caught at the field. The server checks
// everything again with the record engine's validators and has the last word.
import { present } from "./logic.ts";
import type { Field } from "./types.ts";

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;

/** The message for an answer that cannot be sent, or null. */
export function check(f: Field, raw: unknown): string | null {
  const v = f.validation ?? {};
  if (!present(f, raw)) {
    if (!f.required) return null;
    return f.type === "consent" || f.type === "checkbox" ? "This box must be ticked" : `${f.label} is required`;
  }
  const bad = (what: string) => `${f.label} ${what}`;
  if (f.type === "short_text" || f.type === "long_text" || f.type === "email" || f.type === "phone") {
    if (typeof raw !== "string") return bad("must be text");
    const text = raw.trim();
    if (f.type === "email" && !EMAIL.test(text)) return bad("is not an email address");
    if (f.type === "phone" && text.replace(/\D/g, "").length < 6) return bad("is not a phone number");
    if (v.min_length != null && text.length < v.min_length) return bad(`must be at least ${v.min_length} characters`);
    if (v.max_length != null && text.length > v.max_length) return bad(`must be at most ${v.max_length} characters`);
  } else if (f.type === "number" || f.type === "rating") {
    if (typeof raw !== "number" || !Number.isFinite(raw)) return bad("must be a number");
    const [min, max] = f.type === "rating" ? [1, 5] : [v.min, v.max];
    if ((f.type === "rating" || v.integer) && !Number.isInteger(raw)) return bad("must be a whole number");
    if (min != null && raw < min) return bad(`must be at least ${min}`);
    if (max != null && raw > max) return bad(`must be at most ${max}`);
  } else if (f.type === "date") {
    if (typeof raw !== "string" || !DATE.test(raw)) return bad("must be a date like 2026-10-17");
  } else if (f.type === "select") {
    if (!f.options?.some((o) => o.id === raw)) return bad("is not one of the choices");
  } else if (f.type === "multi_select") {
    if (!Array.isArray(raw) || raw.some((x) => !f.options?.some((o) => o.id === x))) return bad("is not one of the choices");
    if (v.min_items != null && raw.length < v.min_items) return bad(`needs at least ${v.min_items} choices`);
    if (v.max_items != null && raw.length > v.max_items) return bad(`has more than ${v.max_items} choices`);
  }
  return null;
}
