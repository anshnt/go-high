// One validator for the form, the inline editors and the memory client, like `records.validate` on the server.
import type { FieldDef } from "./types.ts";
import { isMoney } from "./format.ts";
import { isComputed, valueType } from "./schema.ts";

export function isEmptyValue(v: unknown): boolean {
  return v === null || v === undefined || v === "" || (Array.isArray(v) && v.length === 0);
}

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;

/** A user-facing message, or null when the value is fine. Empty values only fail `required`. */
export function validateValue(field: FieldDef, value: unknown): string | null {
  if (isComputed(field)) return `${field.label} is calculated and cannot be edited.`;
  if (isEmptyValue(value)) return field.rules.required ? `${field.label} is required.` : null;
  const { min, max, max_length } = field.rules;
  switch (valueType(field)) {
    case "text":
    case "long_text":
      if (typeof value !== "string") return "Enter text.";
      return max_length && value.length > max_length ? `Keep it under ${max_length} characters.` : null;
    case "email":
      return typeof value === "string" && EMAIL.test(value) ? null : "Enter a valid email address, like name@example.com.";
    case "phone": {
      const digits = typeof value === "string" ? value.replace(/\D/g, "") : "";
      return typeof value === "string" && /^[+\d\s().-]+$/.test(value) && digits.length >= 7 && digits.length <= 15 ? null : "Enter a valid phone number with area code.";
    }
    case "url":
      try {
        const u = new URL(String(value));
        return u.protocol === "http:" || u.protocol === "https:" ? null : "Start with http:// or https://.";
      } catch {
        return "Enter a full web address, like https://example.com.";
      }
    case "number":
      if (typeof value !== "number" || !Number.isFinite(value)) return "Enter a number.";
      if (min !== undefined && value < min) return `Must be at least ${min}.`;
      return max !== undefined && value > max ? `Must be at most ${max}.` : null;
    case "money":
      if (!isMoney(value) || !Number.isInteger(value.amount) || !/^[A-Z]{3}$/.test(value.currency)) return "Enter an amount.";
      if (min !== undefined && value.amount < min) return min === 0 ? "The amount cannot be negative." : "That amount is too low.";
      return max !== undefined && value.amount > max ? "That amount is too high." : null;
    case "date":
      return typeof value === "string" && DAY.test(value) && !Number.isNaN(Date.parse(value)) ? null : "Pick a valid date.";
    case "datetime":
      return typeof value === "string" && !Number.isNaN(Date.parse(value)) ? null : "Pick a valid date and time.";
    case "boolean":
      return typeof value === "boolean" ? null : "Choose yes or no.";
    case "select":
    case "stage":
      return field.options.choices?.some((c) => c.id === value) ? null : "Choose one of the options.";
    case "multi_select":
      return Array.isArray(value) && value.every((v) => field.options.choices?.some((c) => c.id === v)) ? null : "Choose from the options.";
    case "user":
    case "record":
      return typeof value === "string" ? null : "Choose a record.";
    default:
      return null;
  }
}

/** Typed text from an input to the stored value: trims, lower-cases email, puts https:// in front of a bare web address. */
export function normalizeText(field: FieldDef, raw: string): string {
  const t = raw.trim();
  const type = valueType(field);
  if (type === "url" && t && !/^[a-z][a-z0-9+.-]*:/i.test(t)) return `https://${t}`;
  return type === "email" ? t.toLowerCase() : t;
}
